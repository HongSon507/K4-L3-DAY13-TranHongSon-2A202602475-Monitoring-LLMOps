"""Dựng dashboard 6 panel (HTML + SVG, không cần dependency) từ data/logs.jsonl.

Panel, đơn vị, time range, refresh và threshold đều đọc từ config/dashboard.yaml.

    python scripts/build_dashboard.py                  # -> data/dashboard.html
    python scripts/build_dashboard.py --watch          # dựng lại mỗi refresh_seconds
"""
from __future__ import annotations

import argparse
import html
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.dashboard_data import DashboardData, compute, load_events, resolve_window

W, H = 520, 220
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 14, 30
SERIES = ("var(--series-1)", "var(--series-2)")

CSS = """
:root { color-scheme: light; --surface-0:#f4f4f2; --surface-1:#fcfcfb; --text-primary:#0b0b0b;
  --text-secondary:#52514e; --text-muted:#8a8984; --grid:#e4e3df; --series-1:#2a78d6; --series-2:#eb6834;
  --threshold:#0b0b0b; --good:#008300; --critical:#c62a2a; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --surface-0:#111110; --surface-1:#1a1a19; --text-primary:#ffffff; --text-secondary:#c3c2b7;
  --text-muted:#8f8e86; --grid:#2e2e2c; --series-1:#3987e5; --series-2:#d95926; --threshold:#ffffff;
  --good:#3fb950; --critical:#ff6b6b; } }
:root[data-theme="dark"] { color-scheme: dark; --surface-0:#111110; --surface-1:#1a1a19;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e86; --grid:#2e2e2c;
  --series-1:#3987e5; --series-2:#d95926; --threshold:#ffffff; --good:#3fb950; --critical:#ff6b6b; }
* { box-sizing: border-box; }
body { margin:0; padding:20px 16px; background:var(--surface-0); color:var(--text-primary);
  font:14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { max-width:1640px; margin:0 auto 16px; display:flex; flex-wrap:wrap; gap:8px 24px; align-items:baseline; }
h1 { font-size:20px; margin:0; } .meta { color:var(--text-secondary); font-size:13px; }
.grid { max-width:1640px; margin:0 auto; display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(min(100%,500px),1fr)); }
.panel { background:var(--surface-1); border:1px solid var(--grid); border-radius:10px; padding:14px 16px; min-width:0; }
.panel h2 { font-size:15px; margin:0; display:flex; justify-content:space-between; gap:8px; }
.unit { color:var(--text-muted); font-weight:400; font-size:12px; }
.stats { margin:8px 0 4px; color:var(--text-secondary); font-size:13px; }
.stats b { color:var(--text-primary); font-variant-numeric:tabular-nums; }
.badge { font-size:12px; font-weight:600; white-space:nowrap; }
.badge.ok { color:var(--good); } .badge.breach { color:var(--critical); }
.legend { display:flex; gap:14px; font-size:12px; color:var(--text-secondary); }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:-1px; }
svg { width:100%; height:auto; display:block; } svg text { fill:var(--text-muted); font-size:11px; }
svg .thr { stroke:var(--threshold); stroke-width:1.5; stroke-dasharray:6 4; }
svg .thr-label { fill:var(--text-primary); font-weight:600; }
svg .gridline { stroke:var(--grid); stroke-width:1; }
"""


def esc(value: object) -> str:
    return html.escape(str(value))


def fmt(value: float | None, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


class Frame:
    """Hệ trục chung: x theo thời gian (hoặc chỉ số), y tuyến tính từ 0."""

    def __init__(self, x0: float, x1: float, y_max: float) -> None:
        self.x0, self.x1 = x0, x1 if x1 > x0 else x0 + 1
        self.y_max = y_max if y_max > 0 else 1

    def x(self, value: float) -> float:
        return PAD_L + (value - self.x0) / (self.x1 - self.x0) * (W - PAD_L - PAD_R)

    def y(self, value: float) -> float:
        return H - PAD_B - value / self.y_max * (H - PAD_T - PAD_B)


def axes(frame: Frame, x_labels: list[tuple[float, str]], y_digits: int) -> str:
    parts = []
    for i in range(5):
        v = frame.y_max * i / 4
        yy = frame.y(v)
        parts.append(f'<line class="gridline" x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text x="{PAD_L - 6}" y="{yy + 4:.1f}" text-anchor="end">{fmt(v, y_digits)}</text>')
    for xv, label in x_labels:
        parts.append(f'<text x="{frame.x(xv):.1f}" y="{H - 10}" text-anchor="middle">{esc(label)}</text>')
    return "".join(parts)


def threshold_line(frame: Frame, value: float, label: str) -> str:
    yy = frame.y(value)
    return (
        f'<line class="thr" x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
        f'<text class="thr-label" x="{PAD_L + 4}" y="{yy - 5:.1f}">{esc(label)}</text>'
    )


def time_labels(data: DashboardData) -> tuple[float, float, list[tuple[float, str]]]:
    x0, x1 = data.window.start.timestamp(), data.window.end.timestamp()
    ticks = [x0 + (x1 - x0) * i / 4 for i in range(5)]
    labels = [(t, datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")) for t in ticks]
    return x0, x1, labels


def line_chart(data, series, y_max_hint, thr, y_digits=0, tip_unit="", connect=False):
    """series: list of (name, [(datetime, value)]). Luôn chung một trục y.

    connect=False vẽ mỗi request một chấm, tránh nối qua khoảng không có traffic.
    """
    x0, x1, labels = time_labels(data)
    values = [v for _, pts in series for _, v in pts]
    frame = Frame(x0, x1, max(values + [thr[0], y_max_hint]) * 1.15)
    body = [axes(frame, labels, y_digits)]
    for idx, (name, pts) in enumerate(series):
        color = SERIES[idx]
        coords = [(frame.x(t.timestamp()), frame.y(v), t, v) for t, v in pts]
        if connect and len(coords) > 1:
            path = " ".join(f"{'M' if i == 0 else 'L'}{cx:.1f},{cy:.1f}" for i, (cx, cy, _, _) in enumerate(coords))
            body.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for cx, cy, t, v in coords:
            body.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{color}" stroke="var(--surface-1)" stroke-width="2">'
                f"<title>{esc(name)} {t:%H:%M:%S}: {fmt(v, y_digits)} {esc(tip_unit)}</title></circle>"
            )
    body.append(threshold_line(frame, *thr))
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>'


def bar_chart(data, pts, thr, y_digits=0, tip_unit=""):
    x0, x1, labels = time_labels(data)
    frame = Frame(x0, x1 + 60, max([v for _, v in pts] + [thr[0]]) * 1.15)
    slot = (W - PAD_L - PAD_R) / max(1, len(pts))
    bw = max(2.0, min(18.0, slot - 2))
    body = [axes(frame, labels, y_digits)]
    for t, v in pts:
        if v <= 0:
            continue
        cx, top = frame.x(t.timestamp() + 30), frame.y(v)
        body.append(
            f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{frame.y(0) - top:.1f}" '
            f'rx="2" fill="var(--series-1)"><title>{t:%H:%M}: {fmt(v, y_digits)} {esc(tip_unit)}</title></rect>'
        )
    body.append(threshold_line(frame, *thr))
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>'


def hbar_chart(items, thr):
    frame_max = max([v for _, v in items] + [thr[0]]) * 1.15
    row_h, chart_w = 54, W - 110 - PAD_R
    body = []
    for i, (name, v) in enumerate(items):
        yy = PAD_T + 20 + i * row_h
        width = v / frame_max * chart_w
        body.append(f'<text x="100" y="{yy + 17}" text-anchor="end">{esc(name)}</text>')
        body.append(
            f'<rect x="110" y="{yy}" width="{max(width, 2):.1f}" height="26" rx="3" fill="{SERIES[i]}">'
            f"<title>{esc(name)}: {v:,} tokens</title></rect>"
        )
        body.append(f'<text x="{110 + width + 6:.1f}" y="{yy + 17}" style="fill:var(--text-primary)">{v:,}</text>')
    tx = 110 + thr[0] / frame_max * chart_w
    body.append(f'<line class="thr" x1="{tx:.1f}" x2="{tx:.1f}" y1="{PAD_T}" y2="{H - PAD_B}"/>')
    body.append(f'<text class="thr-label" x="{tx - 4:.1f}" y="{H - 12}" text-anchor="end">{esc(thr[1])}</text>')
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>'


def badge(value: float | None, threshold: dict) -> str:
    if value is None:
        return '<span class="badge">— không có dữ liệu</span>'
    ok = value <= threshold["value"] if threshold["operator"] == "lte" else value >= threshold["value"]
    return '<span class="badge ok">✓ OK</span>' if ok else '<span class="badge breach">✕ BREACH</span>'


def thr_text(threshold: dict, unit: str) -> str:
    op = "≤" if threshold["operator"] == "lte" else "≥"
    return f"{'SLO' if threshold['aggregation'] == 'p95' else 'Threshold'} {threshold['aggregation']} {op} {threshold['value']} {unit}"


def legend(names: list[str]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{SERIES[i]}"></i>{esc(n)}</span>' for i, n in enumerate(names)
    ) + "</div>"


def render_panel(panel: dict, data: DashboardData) -> str:
    pid, unit, thr = panel["id"], panel["unit"], panel["threshold"]
    label = thr_text(thr, unit)
    line = (thr["value"], label)
    if pid == "latency":
        lat = data.latency
        value = lat["p95"]
        stats = f"P50 <b>{fmt(lat['p50'])}</b> · P95 <b>{fmt(lat['p95'])}</b> · P99 <b>{fmt(lat['p99'])}</b> · TTFT P95 <b>{fmt(lat['ttft_p95'])}</b> ms"
        chart = legend(["latency_ms", "ttft_ms"]) + line_chart(
            data,
            [("latency", [(t, l) for t, l, _ in data.latency_points]), ("ttft", [(t, f) for t, _, f in data.latency_points])],
            0, line, tip_unit="ms",
        )
    elif pid == "traffic":
        active = [v for _, v in data.traffic_per_minute if v]
        value = max(active) if active else 0
        stats = f"Tổng <b>{data.traffic_total}</b> request · peak <b>{value}</b> req/min · rate TB <b>{fmt(data.traffic_total / 60, 2)}</b> req/min"
        chart = bar_chart(data, data.traffic_per_minute, line, tip_unit="req/min")
    elif pid == "errors":
        value = data.error_rate_pct
        breakdown = ", ".join(f"{k}: {v}" for k, v in data.error_breakdown.items()) or "không có lỗi"
        stats = (
            f"Error rate <b>{fmt(value, 2)}%</b> · Retrieval success <b>{fmt(data.tool_success_rate_pct, 1)}%</b>"
            f" · Breakdown: <b>{esc(breakdown)}</b>"
        )
        chart = bar_chart(data, data.error_rate_per_minute, line, y_digits=1, tip_unit="% lỗi")
    elif pid == "cost":
        value = data.cost_total
        stats = f"Tổng <b>${fmt(value, 4)}</b> trong cửa sổ · đường = chi phí cộng dồn"
        chart = line_chart(data, [("cumulative cost", data.cost_cumulative)], 0, line, y_digits=2, tip_unit="USD", connect=True)
    elif pid == "tokens":
        value = max(data.tokens.values())
        stats = f"Input <b>{data.tokens['tokens_in']:,}</b> · Output <b>{data.tokens['tokens_out']:,}</b> tokens"
        chart = hbar_chart(list(data.tokens.items()), line)
    elif pid == "quality":
        value = data.quality_mean
        stats = f"Mean quality <b>{fmt(value, 3)}</b> ({len(data.quality_points)} responses)"
        chart = line_chart(data, [("quality", data.quality_points)], 1.0, line, y_digits=2, tip_unit="")
    else:
        raise ValueError(f"Panel không hỗ trợ: {pid}")
    return (
        f'<section class="panel"><h2><span>{esc(panel["title"])} <span class="unit">({esc(unit)})</span></span>'
        f"{badge(value, thr)}</h2><div class=\"stats\">{stats}</div>{chart}</section>"
    )


def build(config_path: Path, log_path: Path, out_path: Path) -> Path:
    dashboard = yaml.safe_load(config_path.read_text(encoding="utf-8"))["dashboard"]
    events = load_events(log_path)
    window = resolve_window(events, dashboard["time_range_minutes"])
    data = compute(events, window)
    panels = "".join(render_panel(p, data) for p in dashboard["panels"])
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{dashboard['refresh_seconds']}">
<title>Day13 LLMOps Dashboard</title><style>{CSS}</style></head><body>
<header><h1>{esc(dashboard['title'])}</h1>
<span class="meta">Time range: last {dashboard['time_range_minutes']} min · {window.start:%Y-%m-%d %H:%M} → {window.end:%H:%M} UTC
 · refresh {dashboard['refresh_seconds']}s · source: {esc(log_path.name)} · events: {sum(data.event_counts.values())}</span></header>
<main class="grid">{panels}</main></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ structured log")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "dashboard.html")
    parser.add_argument("--watch", action="store_true", help="Dựng lại liên tục theo refresh_seconds")
    args = parser.parse_args()

    while True:
        try:
            out = build(args.config, args.logs, args.out)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Không dựng được dashboard: {exc}")
            return 1
        print(f"Đã ghi {out}")
        if not args.watch:
            return 0
        time.sleep(yaml.safe_load(args.config.read_text(encoding="utf-8"))["dashboard"]["refresh_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())
