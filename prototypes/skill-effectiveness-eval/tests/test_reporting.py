"""Evidence-report tests."""

from __future__ import annotations

from skill_eval.reporting import render_report
from skill_eval.results import NormalizedRun, ResultsDocument, ScoreRecord


def _run(condition: str, *, task: str | None, tokens: int, seconds: float, invoked: int) -> NormalizedRun:
    scores = {
        "symposium_capability_scorer": ScoreRecord(
            value=invoked,
            explanation=None,
            metadata={"skill_available": condition == "symposium"},
        )
    }
    if task is not None:
        scores["api_notes_scorer"] = ScoreRecord(value=task, explanation=None, metadata={})
    return NormalizedRun(
        run_id=f"smoke-p1-{condition}",
        attempt_id="smoke-20260825T150000Z",
        phase="smoke",
        pair=1,
        order=1,
        condition=condition,
        status="passed",
        error_kind=None,
        inspect_status="success",
        error=None,
        total_time=seconds,
        working_time=seconds,
        model_usage={"model": {"total_tokens": tokens, "total_cost": 0.01}},
        event_counts={},
        provider_requests=2,
        tool_calls=1,
        scores=scores,
        inspect_log="sample.eval",
    )


def _document(runs: tuple[NormalizedRun, ...]) -> ResultsDocument:
    return ResultsDocument(
        experiment_id="example",
        configuration={},
        framework_versions={},
        controls={"passed": True},
        generated_at="2026-08-28T00:00:00Z",
        runs=runs,
    )


def test_completed_smoke_pair_renders_gates_and_deltas() -> None:
    document = _document(
        (
            _run("baseline", task="C", tokens=120, seconds=20.0, invoked=0),
            _run("symposium", task="C", tokens=80, seconds=15.0, invoked=1),
        )
    )

    report = render_report(document)

    assert "Smoke readiness: PASS" in report
    assert "| smoke | 1 | passed | passed | +0 | -40 | -5.0 | yes |" in report


def test_missing_task_score_does_not_become_an_incorrect_delta() -> None:
    document = _document(
        (
            _run("baseline", task=None, tokens=120, seconds=20.0, invoked=0),
            _run("symposium", task="C", tokens=80, seconds=15.0, invoked=1),
        )
    )

    report = render_report(document)

    assert "Smoke readiness: FAIL" in report
    assert "| smoke | 1 | passed | passed | - | -40 | -5.0 | yes |" in report
