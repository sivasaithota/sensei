"""Local dashboard — `sensei ui` (PRD §4.9 owner surface).

Stdlib-only HTTP server on localhost. Renders everything from the data
directory on each request: no state, no build step, no external assets
(the repo is local-only; the dashboard is too).
"""

from __future__ import annotations

import html
import json
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _positions() -> tuple[float, list[dict]]:
    f = DATA_DIR / "paper" / "positions.json"
    if not f.exists():
        return 50000.0, []
    state = json.loads(f.read_text())
    return state["cash"], state["positions"]


def _closed() -> list[dict]:
    f = DATA_DIR / "paper" / "closed_trades.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def _last_close(symbol: str) -> float | None:
    f = DATA_DIR / "prices" / f"{symbol}.parquet"
    if not f.exists():
        return None
    import pandas as pd
    return float(pd.read_parquet(f, columns=["close"])["close"].iloc[-1])


def _audit_events(limit: int = 200) -> list[dict]:
    f = DATA_DIR / "audit.jsonl"
    if not f.exists():
        return []
    lines = f.read_text().splitlines()
    return [json.loads(l) for l in lines[-limit:] if l.strip()]


def _ledger() -> list[dict]:
    f = DATA_DIR / "mistake_ledger.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def _playbook() -> dict | None:
    f = DATA_DIR / "playbook" / "current.json"
    return json.loads(f.read_text()) if f.exists() else None


def _kill_active() -> bool:
    return (DATA_DIR / "KILL").exists()


def _equity_curve() -> list[tuple[str, float]]:
    """Equity after each closed trade (realized only), starting at capital."""
    capital = 50000.0
    points = [("start", capital)]
    for t in sorted(_closed(), key=lambda t: t["closed"]):
        capital += t["pnl"]
        points.append((t["closed"], capital))
    return points


def _svg_equity(points: list[tuple[str, float]]) -> str:
    if len(points) < 2:
        return "<p class='muted'>Equity curve appears after the first closed trade.</p>"
    w, h, pad = 640, 160, 10
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    step = (w - 2 * pad) / (len(vals) - 1)
    pts = " ".join(f"{pad + i * step:.1f},{h - pad - (v - lo) / rng * (h - 2 * pad):.1f}"
                   for i, v in enumerate(vals))
    color = "#0a7d33" if vals[-1] >= vals[0] else "#b3261e"
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;max-width:{w}px">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>'
            f'</svg>')


def _e(x) -> str:
    return html.escape(str(x))


def render() -> str:
    cash, positions = _positions()
    closed = _closed()
    unrealized = 0.0
    pos_rows = []
    for p in positions:
        last = _last_close(p["symbol"])
        mkt = (last or p["entry_price"]) * p["quantity"]
        upnl = (last - p["entry_price"]) * p["quantity"] if last else 0.0
        unrealized += upnl
        cls = "pos" if upnl >= 0 else "neg"
        pos_rows.append(
            f"<tr><td><b>{_e(p['symbol'])}</b></td><td>{_e(p['direction'])} {p['quantity']}</td>"
            f"<td>₹{p['entry_price']:.2f}</td><td>{f'₹{last:.2f}' if last else '—'}</td>"
            f"<td>₹{p['stop_loss']:.2f}</td><td class='{cls}'>₹{upnl:+,.0f}</td>"
            f"<td>{_e(p['opened'])}</td></tr>"
            f"<tr class='thesis'><td colspan='7'>{_e(p['narrative'])}</td></tr>")

    realized = sum(t["pnl"] for t in closed)
    invested = sum(p["entry_price"] * p["quantity"] for p in positions)
    equity = cash + invested + unrealized
    wins = sum(1 for t in closed if t["pnl"] > 0)

    closed_rows = "".join(
        f"<tr><td>{_e(t['symbol'])}</td><td>{_e(t['opened'])} → {_e(t['closed'])}</td>"
        f"<td>₹{t['entry_price']:.2f} → ₹{t['exit_price']:.2f}</td>"
        f"<td>{_e(t['exit_reason'])}</td>"
        f"<td class='{'pos' if t['pnl'] >= 0 else 'neg'}'>₹{t['pnl']:+,.0f}</td></tr>"
        for t in reversed(closed[-30:])) or "<tr><td colspan='5' class='muted'>None yet</td></tr>"

    verdict_rows = []
    for ev in reversed([e for e in _audit_events() if e.get("event") == "verdict"][-24:]):
        ok = "✅" if ev.get("approved") else "⛔"
        verdict_rows.append(
            f"<tr><td>{_e(ev['ts'][:16])}</td><td>{_e(ev.get('thesis_id', ''))}</td>"
            f"<td>{ok} {_e(ev['level'])}:{_e(ev['agent'])}</td>"
            f"<td class='reason'>{_e(ev['reasoning'][:280])}</td></tr>")
    verdicts = "".join(verdict_rows) or "<tr><td colspan='4' class='muted'>None yet</td></tr>"

    ledger_items = "".join(f"<li>{_e(e['pattern'])} <span class='muted'>({_e(e['thesis_id'])})</span></li>"
                           for e in _ledger()) or "<li class='muted'>Empty — no repeated mistakes logged</li>"

    pb = _playbook()
    pb_rows = ""
    if pb:
        for s in pb["strategies"]:
            badge = "<span class='badge ok'>ADOPTED</span>" if s["adopted"] else "<span class='badge'>rejected</span>"
            o = s["out_of_sample"]
            pb_rows += (f"<tr><td>{_e(s['name'])} {badge}</td><td>{o['trades']}</td>"
                        f"<td>{o['hit_rate']:.0%}</td><td>{o['expectancy_pct']:+.2f}%</td></tr>")

    kill = ("<div class='kill'>⛔ KILL-SWITCH ACTIVE — trading halted</div>"
            if _kill_active() else "")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<title>Sensei — paper trading</title>
<style>
 body {{ font-family: -apple-system, sans-serif; margin: 2rem auto; max-width: 900px;
        padding: 0 1rem; color: #1c1c1e; }}
 h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.05rem; margin-top: 2rem; }}
 table {{ border-collapse: collapse; width: 100%; font-size: .85rem; }}
 td, th {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #eee; }}
 .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
 .card {{ background: #f5f5f7; border-radius: 10px; padding: .8rem 1.2rem; min-width: 130px; }}
 .card .v {{ font-size: 1.3rem; font-weight: 600; }} .card .k {{ font-size: .75rem; color: #666; }}
 .pos {{ color: #0a7d33; }} .neg {{ color: #b3261e; }} .muted {{ color: #999; }}
 .thesis td {{ font-size: .75rem; color: #555; background: #fafafa; }}
 .reason {{ font-size: .75rem; color: #555; }}
 .badge {{ font-size: .65rem; background: #ddd; border-radius: 4px; padding: 1px 6px; }}
 .badge.ok {{ background: #0a7d33; color: white; }}
 .kill {{ background: #b3261e; color: white; padding: .6rem 1rem; border-radius: 8px;
          font-weight: 600; margin-bottom: 1rem; }}
</style></head><body>
<h1>Sensei <span class="muted">· paper trading (P1) · {date.today().isoformat()}</span></h1>
{kill}
<div class="cards">
 <div class="card"><div class="v">₹{equity:,.0f}</div><div class="k">Equity</div></div>
 <div class="card"><div class="v">₹{cash:,.0f}</div><div class="k">Cash</div></div>
 <div class="card"><div class="v">₹{invested:,.0f}</div><div class="k">Invested</div></div>
 <div class="card"><div class="v {'pos' if unrealized >= 0 else 'neg'}">₹{unrealized:+,.0f}</div><div class="k">Unrealized P&L</div></div>
 <div class="card"><div class="v {'pos' if realized >= 0 else 'neg'}">₹{realized:+,.0f}</div><div class="k">Realized P&L</div></div>
 <div class="card"><div class="v">{wins}/{len(closed)}</div><div class="k">Wins / closed</div></div>
</div>

<h2>Equity curve (realized)</h2>
{_svg_equity(_equity_curve())}

<h2>Open positions</h2>
<table><tr><th>Symbol</th><th>Side/Qty</th><th>Entry</th><th>Last</th><th>Stop</th><th>Unrl P&L</th><th>Opened</th></tr>
{''.join(pos_rows) or "<tr><td colspan='7' class='muted'>None</td></tr>"}</table>

<h2>Closed trades (last 30)</h2>
<table><tr><th>Symbol</th><th>Held</th><th>Entry → Exit</th><th>Reason</th><th>P&L</th></tr>
{closed_rows}</table>

<h2>Recent approval-chain verdicts</h2>
<table><tr><th>When</th><th>Thesis</th><th>Verdict</th><th>Reasoning</th></tr>
{verdicts}</table>

<h2>Signal Playbook <span class="muted">v{_e(pb['version']) if pb else '—'}</span></h2>
<table><tr><th>Strategy</th><th>OOS trades</th><th>Hit rate</th><th>Expectancy</th></tr>
{pb_rows}</table>

<h2>Mistake ledger</h2>
<ul>{ledger_items}</ul>

<p class="muted">Auto-refreshes every 60s · reads ./data · local only</p>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(port: int = 8642) -> None:
    print(f"Sensei dashboard → http://localhost:{port}  (Ctrl-C to stop)")
    HTTPServer(("127.0.0.1", port), _Handler).serve_forever()
