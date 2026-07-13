from sensei.paper.engine import ClosedTrade


def test_legacy_playbook_passage_cannot_authorize_trading(tmp_path, monkeypatch):
    import json

    import sensei.backtest.playbook as playbook

    playbook_dir = tmp_path / "playbook"
    playbook_dir.mkdir()
    (playbook_dir / "current.json").write_text(
        json.dumps(
            {
                "version": "legacy",
                "strategies": [
                    {
                        "name": "source_unfaithful_hammer",
                        "adopted": True,
                        "out_of_sample": {"trades": 100},
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(playbook, "PLAYBOOK_DIR", playbook_dir)

    assert playbook.adopted_strategies() == []


def test_one_post_mortem_cannot_create_a_global_veto(tmp_path, monkeypatch):
    import sensei.paper.coach as coach

    ledger = tmp_path / "mistake-ledger.jsonl"
    monkeypatch.setattr(coach, "LEDGER_FILE", ledger)
    monkeypatch.setattr(
        coach,
        "structured_call",
        lambda **kwargs: {
            "category": "wrong-thesis/wrong-outcome",
            "thesis_assessment": "The setup was weak.",
            "execution_assessment": "The fill was conformant.",
            "lesson": "Investigate this setup in a comparison cohort.",
            "mistake_pattern": "breakout after weak breadth",
        },
    )
    trade = ClosedTrade(
        thesis_id="TH-1",
        symbol="TEST",
        direction="BUY",
        entry_price=100,
        exit_price=95,
        quantity=1,
        opened="2026-01-01",
        closed="2026-01-02",
        exit_reason="stop",
        pnl=-5,
        narrative="fixture",
    )

    review = coach.run_post_mortem(trade, client=False)

    assert review["mistake_pattern"] == "breakout after weak breadth"
    assert not ledger.exists()
