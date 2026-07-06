"""The study loop (PRD §5.3):

    material → Scholar extracts rule specs → backtest gate → Playbook

`sensei study <file>` (or piped text). Extracted specs are saved to
data/studied_rules.json with provenance; the Playbook rebuild then
evaluates them alongside the seed strategies under identical adoption
thresholds. Rejected rules stay in the file with their stats visible —
rejection with reasons logged is a PRD requirement, not a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from sensei.backtest.playbook import PLAYBOOK_DIR, build_playbook
from sensei.agents.scholar import extract_rules

STUDIED_FILE = Path(__file__).resolve().parents[3] / "data" / "studied_rules.json"
PRINCIPLES_FILE = Path(__file__).resolve().parents[3] / "data" / "principles.jsonl"


def _persist_notes(notes: list[str], material_head: str) -> None:
    """Untestable principles are still knowledge — keep them durably so
    judgment agents (Analyst, Devil's Advocate, Coach) can draw on them."""
    import datetime
    with PRINCIPLES_FILE.open("a") as f:
        for n in notes:
            f.write(json.dumps({"ts": datetime.date.today().isoformat(),
                                "material": material_head[:80], "note": n}) + "\n")


def _load() -> list[dict]:
    if STUDIED_FILE.exists():
        return json.loads(STUDIED_FILE.read_text())
    return []


def study(material: str, client=None) -> dict:
    """Full loop: extract → persist specs → rebuild Playbook → report."""
    specs, notes = extract_rules(material, client=client)
    if notes:
        _persist_notes(notes, material.strip().splitlines()[0] if material.strip() else "")

    existing = _load()
    known = {r["name"] for r in existing}
    added = []
    for spec in specs:
        if spec.name in known:
            notes.append(f"'{spec.name}' already studied — skipped duplicate")
            continue
        existing.append(spec.model_dump())
        added.append(spec.name)
    STUDIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    STUDIED_FILE.write_text(json.dumps(existing, indent=2))

    playbook = build_playbook() if added else None
    verdicts = []
    if playbook:
        for s in playbook["strategies"]:
            if s["name"] in added:
                verdicts.append({
                    "name": s["name"],
                    "adopted": s["adopted"],
                    "out_of_sample": s["out_of_sample"],
                    "source": s.get("source", ""),
                })
    return {"extracted": [s.name for s in specs],
            "added_and_tested": verdicts,
            "untestable_notes": notes}
