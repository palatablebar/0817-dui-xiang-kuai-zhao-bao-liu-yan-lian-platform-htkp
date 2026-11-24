"""回收演练：把对象分成可回收、留存和隔离三类，并给出可审批的决策选项。

演练只生成结果，不会删除对象。可回收对象必须同时满足：所在业务组已通过、
没有合法保全、没有被活动快照引用、且已满保留期。留存对象始终保留原对象，
并附带可复核的依据（快照、引用记录、保全标记或保留期天数）。
"""

from collections import defaultdict

from app.business import by_kind
from app.modules.grouping import case_groups

RECLAIM = "RECLAIM"
LIVE_SNAPSHOT = "LIVE_SNAPSHOT"
LEGAL_HOLD = "LEGAL_HOLD"
RETENTION = "RETENTION"
UNRESOLVED = "UNRESOLVED"

PROTECTED = (LIVE_SNAPSHOT, LEGAL_HOLD)
RETAINED_REASONS = (LIVE_SNAPSHOT, LEGAL_HOLD, RETENTION)


def _control(rows):
    found = by_kind(rows, "control")
    return found[0] if found else None


def _snapshot_records(rows):
    return {row["snapshot"]: row["record"] for row in by_kind(rows, "snapshot")}


def _active_snapshots(rows):
    return {row["snapshot"] for row in by_kind(rows, "snapshot") if row["policy"]}


def _references(rows):
    found = defaultdict(list)
    for row in by_kind(rows, "ref"):
        found[row["object_id"]].append(row)
    return found


def _calculated_reason(row, control, live_references):
    """与 calculate.compute 保持同一优先级：保全、活动快照、保留期、回收。"""
    if row["policy"]:
        return LEGAL_HOLD
    if live_references:
        return LIVE_SNAPSHOT
    if control is None:
        return UNRESOLVED
    if control["day"] - row["day"] < control["policy"]:
        return RETENTION
    return RECLAIM


def _basis(row, reason, calculated, status, control, live_references, snapshots):
    basis = {
        "kind": reason,
        "record": row["record"],
        "group_status": status,
    }
    if reason == LIVE_SNAPSHOT:
        basis.update(
            snapshot_ids=sorted({ref["snapshot"] for ref in live_references}),
            references=sorted(ref["record"] for ref in live_references),
            snapshot_records=sorted(
                {
                    snapshots[ref["snapshot"]]
                    for ref in live_references
                    if ref["snapshot"] in snapshots
                }
            ),
            detail="活动快照仍引用该对象，必须留存原对象",
        )
    elif reason == LEGAL_HOLD:
        basis.update(
            policy=row["policy"],
            detail="对象标记合法保全，必须留存原对象",
        )
    elif reason == RETENTION:
        if control is None:
            basis["detail"] = "缺少控制行，无法核对保留期，暂不释放"
        else:
            basis.update(
                entry_day=row["day"],
                current_day=control["day"],
                retention_days=control["policy"],
                elapsed_days=control["day"] - row["day"],
                detail="尚未达到保留期，留存原对象",
            )
    elif reason == UNRESOLVED:
        basis.update(
            calculated=calculated,
            detail=(
                f"业务分组 {status} 尚未对平，暂不释放该对象"
                if status != "READY"
                else "缺少可回收计算依据，暂不释放该对象"
            ),
        )
    else:
        basis.update(
            entry_day=row["day"],
            current_day=control["day"] if control is not None else None,
            retention_days=control["policy"] if control is not None else None,
            elapsed_days=(
                control["day"] - row["day"] if control is not None else None
            ),
            detail="已满保留期，且没有活动快照或合法保全，列入可回收",
        )
    return basis


def _entry(row, reason, calculated, status, control, live_references, snapshots, line=None):
    entry = {
        "case": row["case"],
        "object_id": str(row["object_id"]),
        "record": row["record"],
        "size_bytes": row["size_bytes"],
        "reason": reason,
        "protected": reason in PROTECTED,
        "basis": _basis(
            row, reason, calculated, status, control, live_references, snapshots
        ),
    }
    if line is not None:
        entry["line"] = line
    return entry


def _check(name, label, expected, actual):
    return dict(
        name=name,
        label=label,
        expected=expected,
        actual=actual,
        ok=expected == actual,
    )


def _truth(name, label, ok):
    return dict(name=name, label=label, ok=bool(ok))


def _measure_value(objects, evidence):
    return sum(
        row["size_bytes"]
        for row in objects
        if evidence.get(str(row["object_id"])) == RECLAIM
    )


def _option(status, label, available, capacity, blockers):
    return dict(
        status=status,
        label=label,
        available=bool(available),
        bytes=capacity if available else 0,
        blockers=sorted(set(blockers)),
    )


def release_plan(intake, cases):
    """根据采信结果和业务判定生成一次回收演练。"""
    accepted_rows = list(intake.get("rows") or [])
    isolation = list(intake.get("isolation") or [])
    positions = intake.get("positions") or {}
    groups = dict(case_groups(accepted_rows))
    by_case = {case["case"]: case for case in cases}

    reclaimable, retained, group_plans = [], [], []
    protected_source = protected_retained = 0
    expected_reclaimable = 0
    potential_bytes = potential_objects = 0
    measured_bytes = 0
    measure_ok = calculated_ok = True

    for code in sorted(groups):
        rows = groups[code]
        case = by_case.get(code, {})
        status = case.get("status", "UNKNOWN")
        ready = status == "READY"
        measure = case.get("measure")
        measure = measure if isinstance(measure, dict) else None
        evidence = measure.get("evidence") if measure else None
        evidence = evidence if isinstance(evidence, dict) else {}
        if ready and measure is None:
            measure_ok = False

        control = _control(rows)
        snapshots = _snapshot_records(rows)
        active = _active_snapshots(rows)
        references = _references(rows)
        objects = sorted(by_kind(rows, "object"), key=lambda row: row["record"])
        object_ids = {str(row["object_id"]) for row in objects}

        if measure is not None:
            if set(evidence) != object_ids:
                measure_ok = False
            if measure.get("value") != _measure_value(objects, evidence):
                measure_ok = False

        group_reclaim_bytes = group_retained_bytes = 0
        group_reclaim_objects = group_retained_objects = 0

        for row in objects:
            live = [
                ref
                for ref in references.get(row["object_id"], [])
                if ref["snapshot"] in active
            ]
            calculated = _calculated_reason(row, control, live)
            expected = evidence.get(str(row["object_id"]))

            if calculated in PROTECTED:
                protected_source += 1
            if expected is not None and expected != calculated:
                calculated_ok = False
            if calculated == RECLAIM:
                potential_bytes += row["size_bytes"]
                potential_objects += 1

            # 只有计算依据确认是回收、且业务组已通过的对象才进入可回收。
            confirmed = ready and expected == RECLAIM and calculated == RECLAIM
            line = positions.get(row["record"])
            if confirmed:
                entry = _entry(
                    row, RECLAIM, calculated, status, control, live, snapshots, line
                )
                reclaimable.append(entry)
                group_reclaim_bytes += row["size_bytes"]
                group_reclaim_objects += 1
                continue

            reason = calculated if calculated in RETAINED_REASONS else UNRESOLVED
            entry = _entry(
                row, reason, calculated, status, control, live, snapshots, line
            )
            retained.append(entry)
            group_retained_bytes += row["size_bytes"]
            group_retained_objects += 1
            if reason in PROTECTED:
                protected_retained += 1

        if ready:
            expected_reclaimable += sum(
                1 for value in evidence.values() if value == RECLAIM
            )
            if measure is not None:
                measured_bytes += measure.get("value", 0)

        group_plans.append(
            dict(
                case=code,
                status=status,
                ready=ready,
                objects=len(objects),
                reclaimable_objects=group_reclaim_objects,
                retained_objects=group_retained_objects,
                reclaimable_bytes=group_reclaim_bytes,
                retained_bytes=group_retained_bytes,
            )
        )

    object_source_rows = len(by_kind(accepted_rows, "object"))
    capacity_bytes = sum(entry["size_bytes"] for entry in reclaimable)
    accepted = intake.get("accepted", 0)
    rejected = intake.get("rejected", 0)
    blank = intake.get("blank", 0)
    repeated = intake.get("repeated", 0)
    input_rows = intake.get("input", 0)
    accounted = accepted + rejected + blank + repeated
    reasons = intake.get("reasons") or {}
    retained_expected = object_source_rows - expected_reclaimable

    checks = [
        _check("source_rows", "源行", input_rows, accounted),
        _check("retained_rows", "保留行", retained_expected, len(retained)),
        _check("reclaimable_rows", "可回收行", expected_reclaimable, len(reclaimable)),
        _check("isolated_rows", "隔离行", rejected, len(isolation)),
        _check("accepted_rows", "采信行", accepted, len(accepted_rows)),
        _check(
            "object_rows",
            "对象行",
            object_source_rows,
            len(retained) + len(reclaimable),
        ),
        _check("protected_retained", "保全留存", protected_source, protected_retained),
        _check("capacity", "释放容量", measured_bytes, capacity_bytes),
        _truth("isolation_reasons", "隔离原因", sum(reasons.values()) == rejected),
        _truth("measure_rows", "计算值守恒", measure_ok),
        _truth("calculated_rows", "计算依据一致", calculated_ok),
    ]
    blockers = [item["name"] for item in checks if not item["ok"]]
    reconciled = not blockers

    pending = sorted(case["case"] for case in cases if case.get("status") != "READY")
    ready_count = sum(1 for case in cases if case.get("status") == "READY")
    rows_ok = (
        accounted == input_rows
        and accepted == len(accepted_rows)
        and rejected == len(isolation)
    )

    partial_blockers = list(blockers)
    if reconciled and capacity_bytes == 0:
        partial_blockers.append("no_safe_objects")

    approved_blockers = list(blockers)
    approved_blockers.extend(pending)
    if rejected:
        approved_blockers.append("isolated_rows")
    if not rows_ok:
        approved_blockers.append("source_rows")
    if not cases:
        approved_blockers.append("no_cases")

    partial_available = reconciled and capacity_bytes > 0
    approved_available = (
        reconciled
        and bool(cases)
        and ready_count == len(cases)
        and rejected == 0
        and rows_ok
    )

    if not reconciled:
        summary = "对账不一致，已阻止执行：" + "、".join(blockers)
    elif approved_available:
        summary = (
            f"整批可签发 · 将释放 {capacity_bytes} 字节 · "
            f"留存 {len(retained)} 个对象"
        )
    elif partial_available:
        wait = "、".join(pending) if pending else "隔离行"
        summary = f"可先释放 {capacity_bytes} 字节 · 整批签发待完成：{wait}"
    else:
        summary = "没有已确认安全的对象可以释放"

    return dict(
        unit="字节",
        capacity=dict(
            bytes=capacity_bytes,
            objects=len(reclaimable),
            groups=sorted({entry["case"] for entry in reclaimable}),
        ),
        potential=dict(bytes=potential_bytes, objects=potential_objects),
        reclaimable=reclaimable,
        retained=retained,
        quarantined=isolation,
        ignored=blank + repeated,
        groups=group_plans,
        pending=pending,
        reconciled=reconciled,
        blocked=not reconciled,
        reconciliation=dict(ok=reconciled, checks=checks, blockers=blockers),
        options=[
            _option(
                "PARTIAL",
                "先释放已确认安全的对象",
                partial_available,
                capacity_bytes,
                partial_blockers,
            ),
            _option("HELD", "等齐后整批处理", True, 0, []),
            _option(
                "APPROVED",
                "整批签发",
                approved_available,
                capacity_bytes,
                approved_blockers,
            ),
        ],
        needs_choice=partial_available and not approved_available,
        summary=summary,
    )
