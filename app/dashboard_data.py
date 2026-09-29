"""Tính số liệu cho 6 panel dashboard từ structured log (data/logs.jsonl).

Mọi phép tổng hợp bám theo `config/dashboard.yaml`; module này không render gì.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from .metrics import percentile


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DashboardData:
    window: Window
    latency_points: list[tuple[datetime, int, int]]  # (ts, latency_ms, ttft_ms)
    latency: dict[str, float]
    traffic_per_minute: list[tuple[datetime, int]]
    traffic_total: int
    error_rate_per_minute: list[tuple[datetime, float]]
    error_rate_pct: float
    error_breakdown: dict[str, int]
    tool_success_rate_pct: float | None
    cost_cumulative: list[tuple[datetime, float]]
    cost_per_minute: list[tuple[datetime, float]]
    cost_total: float
    tokens: dict[str, int]
    quality_points: list[tuple[datetime, float]]
    quality_mean: float | None
    event_counts: dict[str, int] = field(default_factory=dict)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # bỏ qua dòng hỏng thay vì làm sập dashboard
        if isinstance(record, dict) and "ts" in record and "event" in record:
            events.append({**record, "_ts": parse_ts(record["ts"])})
    return sorted(events, key=lambda e: e["_ts"])


def resolve_window(events: list[dict], minutes: int, end: datetime | None = None) -> Window:
    """Cửa sổ `minutes` phút kết thúc tại `end` (mặc định: event mới nhất)."""
    if end is None:
        if not events:
            raise ValueError("Không có event nào trong log")
        end = events[-1]["_ts"]
    return Window(start=end - timedelta(minutes=minutes), end=end)


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _minutes_in(window: Window) -> list[datetime]:
    minutes, cursor = [], _minute(window.start)
    while cursor <= window.end:
        minutes.append(cursor)
        cursor += timedelta(minutes=1)
    return minutes


def compute(events: list[dict], window: Window) -> DashboardData:
    in_window = [e for e in events if window.start <= e["_ts"] <= window.end]
    by_event: dict[str, list[dict]] = {}
    for e in in_window:
        by_event.setdefault(e["event"], []).append(e)

    responses = by_event.get("response_sent", [])
    received = by_event.get("request_received", [])
    failed = by_event.get("request_failed", [])
    minutes = _minutes_in(window)

    latencies = [int(e["latency_ms"]) for e in responses]
    ttfts = [int(e["ttft_ms"]) for e in responses]
    received_by_min = Counter(_minute(e["_ts"]) for e in received)
    failed_by_min = Counter(_minute(e["_ts"]) for e in failed)

    tool_events = [e for e in in_window if e.get("tool_success") is not None]
    tool_ok = sum(1 for e in tool_events if e["tool_success"] is True)

    cost_by_min: Counter[datetime] = Counter()
    cumulative, running = [], 0.0
    for e in responses:
        cost_by_min[_minute(e["_ts"])] += float(e["cost_usd"])
        running += float(e["cost_usd"])
        cumulative.append((e["_ts"], round(running, 6)))

    quality = [(e["_ts"], float(e["quality_score"])) for e in responses]

    return DashboardData(
        window=window,
        latency_points=[(e["_ts"], int(e["latency_ms"]), int(e["ttft_ms"])) for e in responses],
        latency={
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "ttft_p95": percentile(ttfts, 95),
        },
        traffic_per_minute=[(m, received_by_min.get(m, 0)) for m in minutes],
        traffic_total=len(received),
        error_rate_per_minute=[
            (m, round(failed_by_min.get(m, 0) / received_by_min[m] * 100, 2) if received_by_min.get(m) else 0.0)
            for m in minutes
        ],
        error_rate_pct=round(len(failed) / len(received) * 100, 2) if received else 0.0,
        error_breakdown=dict(Counter(str(e.get("error_type")) for e in failed)),
        tool_success_rate_pct=round(tool_ok / len(tool_events) * 100, 2) if tool_events else None,
        cost_cumulative=cumulative,
        cost_per_minute=[(m, round(cost_by_min.get(m, 0.0), 6)) for m in minutes],
        cost_total=round(running, 6),
        tokens={
            "tokens_in": sum(int(e["tokens_in"]) for e in responses),
            "tokens_out": sum(int(e["tokens_out"]) for e in responses),
        },
        quality_points=quality,
        quality_mean=round(mean(q for _, q in quality), 4) if quality else None,
        event_counts={k: len(v) for k, v in by_event.items()},
    )
