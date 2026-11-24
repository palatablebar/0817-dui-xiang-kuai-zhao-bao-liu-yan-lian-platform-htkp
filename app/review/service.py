from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.modules.pipeline import run


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    # 演练按来源内容定型：同一来源重跑复用原批次、原结论和原依据，
    # 即使规则版本已更新也不重新计算，避免新增演练或改写已签发结果。
    run_id = sha256(fingerprint.encode()).hexdigest()
    try:
        return store.load(run_id)
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise
    report = run(data)
    report["manifest"] = dict(
        sha256=fingerprint,
        version=RULE_VERSION,
        created=now(),
        duration_ms=round((monotonic() - start) * 1000, 3),
        bytes=len(data),
        run_id=run_id,
    )
    return store.register(run_id, report)


FINAL_STATUSES = ("APPROVED", "PARTIAL")
REVIEW_STATUSES = ("APPROVED", "PARTIAL", "HELD")


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in REVIEW_STATUSES
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = store.load(run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] in FINAL_STATUSES:
        raise DomainIssue("RUN_FINALIZED")
    if status != "HELD":
        # 释放只能使用当次演练已经算出的选项；对账不一致时一律挡住执行。
        release = current["report"].get("release") or {}
        options = {item.get("status"): item for item in release.get("options", [])}
        option = options.get(status)
        if not release.get("reconciled") or not (option and option.get("available")):
            raise DomainIssue("UNRESOLVED_ISSUES")
    return store.revise(run_id, revision, status, note.strip(), now())
