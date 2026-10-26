"""Trazabilidad: eventos JSON, tramos por etapa, llamadas a modelos y datos que no deben salir."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from vfxglow import telemetry


def _events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [record.vexora for record in caplog.records if hasattr(record, "vexora")]


def test_json_lines_carry_time_service_and_the_job_context(caplog: pytest.LogCaptureFixture) -> None:
    formatter = telemetry.JsonFormatter()
    with caplog.at_level(logging.INFO, logger="vexora.events"), telemetry.job_context("job1", "trace1"):
        telemetry.event("job.started", queue_wait_ms=12)
        line = json.loads(formatter.format(caplog.records[-1]))
    assert line["event"] == "job.started" and line["job_id"] == "job1" and line["trace_id"] == "trace1"
    assert line["queue_wait_ms"] == 12 and line["timestamp"].endswith("Z") and line["level"] == "info"
    assert {"service", "env", "version"} <= set(line)


def test_pipeline_messages_become_json_without_server_paths() -> None:
    record = logging.LogRecord("vfxglow.api", logging.INFO, __file__, 1, "Video final: %s", ("/Users/alguien/runs/v-1/output/baile.mp4",), None)
    line = json.loads(telemetry.JsonFormatter().format(record))
    assert line["event"] == "log" and line["message"] == "Video final: baile.mp4"


def test_a_span_measures_its_stage_and_adds_it_to_the_job_summary(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="vexora.events"), telemetry.job_context("job1", "trace1") as summary:
        with telemetry.span("analyze"):
            telemetry.annotate(cache_hit=True)
            with telemetry.span("deep"):
                pass
    events = _events(caplog)
    names = [(e["event"], e["stage"]) for e in events]
    assert names == [("stage.started", "analyze"), ("stage.started", "deep"), ("stage.finished", "deep"), ("stage.finished", "analyze")]
    finished = events[-1]
    assert finished["outcome"] == "ok" and finished["cache_hit"] is True and finished["duration_ms"] >= 0
    assert events[1]["parent_span_id"] == events[0]["span_id"]
    assert set(summary["stages"]) == {"analyze", "deep"} and summary["cache_hits"] == ["analyze"]


def test_a_failing_span_names_the_stage_that_failed(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="vexora.events"), telemetry.job_context("job1", "trace1") as summary:
        with pytest.raises(RuntimeError), telemetry.span("render"):
            raise RuntimeError("se rompió")
    assert summary["failed_stage"] == "render"
    assert _events(caplog)[-1]["outcome"] == "error" and _events(caplog)[-1]["error"] == {"kind": "RuntimeError"}


def test_llm_calls_add_tokens_and_cost_only_when_the_price_is_known(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    prices = tmp_path / "precios.yaml"
    prices.write_text("models:\n  barato: {tier: economico, input_per_mtok: 1.0, output_per_mtok: 4.0}\n  sin_precio: {tier: premium}\n", encoding="utf-8")
    monkeypatch.setenv(telemetry.PRICES_ENV, str(prices))
    telemetry._prices.cache_clear()
    try:
        with caplog.at_level(logging.INFO, logger="vexora.events"), telemetry.job_context("job1", "trace1") as summary:
            telemetry.llm_call("openai", "barato", "scene", 1_000_000, 500_000, 900)
            telemetry.llm_call("gemini", "sin_precio", "deep", 10, 10, 1000)
            telemetry.llm_call("gemini", "barato", "deep", 0, 0, cache_hit=True)
    finally:
        telemetry._prices.cache_clear()
    calls = _events(caplog)
    assert calls[0]["cost_usd_est"] == 3.0 and calls[0]["tier"] == "economico"
    assert "cost_usd_est" not in calls[1]  # sin precio: no se inventa
    assert calls[2]["cache_hit"] is True
    assert summary["llm"] == {"calls": 2, "tokens_in": 1_000_010, "tokens_out": 500_010, "cost_usd_est": 3.0}


def test_no_personal_data_or_keys_in_the_trace() -> None:
    assert telemetry.redact("/api/jobs/a/original?k=123.abc&first=true") == "original?k=***&first=true"
    reference = telemetry.user_ref("uid-ana")
    assert reference.startswith("sha256:") and "uid-ana" not in reference
    assert telemetry.user_ref(None) is None


def test_setup_writes_json_events_to_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(telemetry.DIR_ENV, raising=False)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        telemetry.setup("vexora-test", tmp_path, console="text")
        telemetry.event("job.queued", job_id="j1")
        for handler in root.handlers:
            handler.flush()
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(lines[-1])["event"] == "job.queued" and json.loads(lines[-1])["service"] == "vexora-test"
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_the_hook_follows_each_stage_and_the_current_one_is_in_the_summary() -> None:
    seen: list[tuple[str, str, str | None]] = []
    with telemetry.job_context("job1", "trace1", on_change=lambda kind, stage, summary: seen.append((kind, stage, summary["current"]))) as summary:
        with telemetry.span("direct"):
            with telemetry.span("deep"):
                pass
    assert seen == [("started", "direct", "direct"), ("started", "deep", "deep"), ("finished", "deep", "direct"), ("finished", "direct", None)]
    assert summary["current"] is None and set(summary["stages"]) == {"direct", "deep"}
    assert set(summary["started_at"]) == {"direct", "deep"} and summary["started_at"]["deep"] >= summary["started_at"]["direct"]


def test_the_checkpoint_only_stops_a_job_that_was_asked_to_stop() -> None:
    import threading

    telemetry.checkpoint()  # sin trabajo: nada
    stop = threading.Event()
    with telemetry.job_context("job1", "trace1", cancel=stop):
        telemetry.checkpoint()
        stop.set()
        with pytest.raises(telemetry.Cancelled):
            telemetry.checkpoint()
    telemetry.checkpoint()  # fuera del trabajo vuelve a no hacer nada
