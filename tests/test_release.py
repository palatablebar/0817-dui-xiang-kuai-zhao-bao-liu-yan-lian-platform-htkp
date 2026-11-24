import pytest

from app.business import DomainIssue
from app.intake.service import inspect
from app.modules.pipeline import run
from app.modules.reclaim import release_plan
from app.review.service import execute, review


def plan(data):
    return run(data)["release"]


def test_clean_plan_reports_capacity_and_retained_basis(clean):
    result = plan(clean)
    assert result["reconciled"] and not result["blocked"]
    assert result["capacity"] == {"bytes": 44, "objects": 2, "groups": ["0001", "0002"]}
    held = {entry["object_id"]: entry for entry in result["retained"]}
    assert held["1"]["reason"] == "LIVE_SNAPSHOT"
    assert held["1"]["basis"]["snapshot_ids"] == [11]
    assert held["1"]["basis"]["references"] == ["000105"]
    assert held["3"]["reason"] == "LEGAL_HOLD"
    assert held["3"]["basis"]["policy"] == 1
    assert all(entry["basis"]["detail"] for entry in result["retained"])


def test_clean_plan_offers_batch_release(clean):
    result = plan(clean)
    options = {item["status"]: item for item in result["options"]}
    assert options["APPROVED"]["available"] and options["APPROVED"]["bytes"] == 44
    assert options["PARTIAL"]["available"]
    assert not result["needs_choice"]


def test_dirty_plan_lets_operator_choose_partial_or_wait(dirty):
    result = plan(dirty)
    options = {item["status"]: item for item in result["options"]}
    assert result["reconciled"] and not result["blocked"]
    assert result["pending"] == ["0003", "0004"]
    assert options["PARTIAL"]["available"] and options["PARTIAL"]["bytes"] == 44
    assert not options["APPROVED"]["available"]
    assert "0003" in options["APPROVED"]["blockers"]
    assert options["HELD"]["available"]
    assert result["needs_choice"]


def test_pending_groups_never_release_objects(dirty):
    result = plan(dirty)
    released = {entry["case"] for entry in result["reclaimable"]}
    assert released == {"0001", "0002"}
    unresolved = {entry["case"] for entry in result["retained"] if entry["reason"] == "UNRESOLVED"}
    assert unresolved == {"0003", "0004"}


def test_protected_objects_stay_retained(dirty):
    result = plan(dirty)
    released = {(entry["case"], entry["object_id"]) for entry in result["reclaimable"]}
    assert ("0001", "1") not in released and ("0001", "3") not in released
    assert ("0002", "1") in released
    assert not any(entry["protected"] for entry in result["reclaimable"])
    protected = [entry for entry in result["retained"] if entry["protected"]]
    assert {entry["reason"] for entry in protected} == {"LIVE_SNAPSHOT", "LEGAL_HOLD"}


def test_quarantined_rows_are_reported_with_source_lines(dirty):
    result = plan(dirty)
    assert len(result["quarantined"]) == 5
    assert all(row["line"] > 1 for row in result["quarantined"])


def test_row_reconciliation_blocks_execution(dirty):
    intake = inspect(dirty)
    intake["accepted"] += 1
    cases = run(dirty)["cases"]
    result = release_plan(intake, cases)
    assert result["blocked"] and not result["reconciled"]
    assert "retained_rows" in result["reconciliation"]["blockers"] or (
        "accepted_rows" in result["reconciliation"]["blockers"]
    )
    options = {item["status"]: item for item in result["options"]}
    assert not options["PARTIAL"]["available"]
    assert not options["APPROVED"]["available"]


def test_capacity_mismatch_blocks_execution(dirty):
    intake = inspect(dirty)
    cases = run(dirty)["cases"]
    for case in cases:
        if case["case"] == "0002":
            case["measure"]["value"] = 99
    result = release_plan(intake, cases)
    assert result["blocked"]
    assert "capacity" in result["reconciliation"]["blockers"]


def test_missing_isolation_line_blocks_execution(dirty):
    intake = inspect(dirty)
    intake["isolation"] = intake["isolation"][:-1]
    result = release_plan(intake, run(dirty)["cases"])
    assert result["blocked"]
    assert "isolated_rows" in result["reconciliation"]["blockers"]


def test_partial_review_records_choice_and_is_final(store, dirty):
    run_row = execute(store, dirty)
    result = review(
        store, run_row["id"], dict(revision=0, status="PARTIAL", note="先释放安全对象")
    )
    assert result["status"] == "PARTIAL" and result["revision"] == 1
    assert result["report"]["release"]["capacity"]["bytes"] == 44
    with pytest.raises(DomainIssue, match="RUN_FINALIZED"):
        review(
            store,
            run_row["id"],
            dict(revision=1, status="APPROVED", note="再尝试整批签发"),
        )


def test_dirty_batch_cannot_be_fully_approved(store, dirty):
    run_row = execute(store, dirty)
    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        review(
            store, run_row["id"], dict(revision=0, status="APPROVED", note="整批签发")
        )
    stored = store.load(run_row["id"])
    assert stored["revision"] == 0 and stored["status"] == "PENDING"
    assert stored["report"]["release"]["capacity"]["bytes"] == 44


def test_failed_review_keeps_original_run_and_basis(store, dirty):
    run_row = execute(store, dirty)
    before = store.load(run_row["id"])
    with pytest.raises(DomainIssue, match="STALE_REVIEW"):
        review(store, run_row["id"], dict(revision=9, status="HELD", note="旧版本"))
    after = store.load(run_row["id"])
    assert after["revision"] == before["revision"]
    assert after["report"]["release"] == before["report"]["release"]


def test_approved_run_survives_same_source_rerun(store, clean):
    first = execute(store, clean)
    review(store, first["id"], dict(revision=0, status="APPROVED", note="整批复核通过"))
    again = execute(store, clean)
    assert again["id"] == first["id"]
    assert again["status"] == "APPROVED" and again["revision"] == 1
    assert len(store.list()) == 1


def test_approved_clean_run_cannot_be_downgraded(store, clean):
    run_row = execute(store, clean)
    review(store, run_row["id"], dict(revision=0, status="APPROVED", note="整批复核通过"))
    with pytest.raises(DomainIssue, match="RUN_FINALIZED"):
        review(store, run_row["id"], dict(revision=1, status="PARTIAL", note="改先释放"))


def test_http_partial_release_flow(client):
    run_row = client.post("/api/runs", data={"sample": "dirty"}).json
    assert run_row["report"]["release"]["needs_choice"] is True
    blocked = client.patch(
        "/api/runs/" + run_row["id"],
        json=dict(revision=0, status="APPROVED", note="尝试整批签发"),
    )
    assert blocked.status_code == 409 and blocked.json["code"] == "UNRESOLVED_ISSUES"
    assert client.get("/api/runs/" + run_row["id"]).json["revision"] == 0
    accepted = client.patch(
        "/api/runs/" + run_row["id"],
        json=dict(revision=0, status="PARTIAL", note="先释放确认安全的对象"),
    )
    assert accepted.status_code == 200 and accepted.json["status"] == "PARTIAL"
    packet = client.get("/api/runs/" + run_row["id"] + "/evidence").json
    assert packet["release"]["capacity"]["bytes"] == 44
    assert packet["review"]["status"] == "PARTIAL"
