from __future__ import annotations

import json
from pathlib import Path

from app.dashboard_data import compute, load_events, resolve_window
from scripts import build_dashboard


def _write_logs(path: Path) -> Path:
    records = [
        {"ts": "2026-09-29T07:00:00Z", "event": "request_received"},  # ngoài cửa sổ 60 phút
        {"ts": "2026-09-29T07:00:01Z", "event": "response_sent", "latency_ms": 9999, "ttft_ms": 50,
         "cost_usd": 1.0, "tokens_in": 1, "tokens_out": 1, "quality_score": 0.1, "tool_success": True},
        {"ts": "2026-09-29T08:00:00Z", "event": "request_received"},
        {"ts": "2026-09-29T08:00:01Z", "event": "response_sent", "latency_ms": 400, "ttft_ms": 50,
         "cost_usd": 0.002, "tokens_in": 30, "tokens_out": 100, "quality_score": 0.9, "tool_success": True},
        {"ts": "2026-09-29T08:01:00Z", "event": "request_received"},
        {"ts": "2026-09-29T08:01:01Z", "event": "request_failed", "error_type": "RuntimeError",
         "tool_success": False},
    ]
    lines = [json.dumps(r) for r in records] + ["not-json"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_compute_only_uses_last_60_minutes(tmp_path: Path) -> None:
    events = load_events(_write_logs(tmp_path / "logs.jsonl"))

    data = compute(events, resolve_window(events, 60))

    assert data.traffic_total == 2
    assert data.latency["p95"] == 400
    assert data.latency["ttft_p95"] == 50
    assert data.error_rate_pct == 50.0
    assert data.error_breakdown == {"RuntimeError": 1}
    assert data.tool_success_rate_pct == 50.0
    assert data.cost_total == 0.002
    assert data.tokens == {"tokens_in": 30, "tokens_out": 100}
    assert data.quality_mean == 0.9


def test_build_dashboard_renders_six_panels_with_thresholds(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    out = build_dashboard.build(
        repo / "config" / "dashboard.yaml", _write_logs(tmp_path / "logs.jsonl"), tmp_path / "d.html"
    )

    page = out.read_text(encoding="utf-8")
    assert page.count('class="panel"') == 6
    assert page.count('class="thr"') == 6
    assert "last 60 min" in page
    assert "SLO p95 ≤ 3000 ms" in page
    assert "BREACH" in page  # error rate 50% > 2%
