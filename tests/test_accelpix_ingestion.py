from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import pytest

from sensei.data import accelpix_cli
from sensei.data.accelpix import (
    ACCELPIX_STAMP,
    AccelPixClient,
    AccelPixConfig,
    AccelPixError,
    AccelPixPlan,
    AccelPixRequest,
    AccelPixRequestError,
    AccelPixStore,
    FetchedPayload,
    RequestKind,
    normalize_eod_plan,
    symbols_from_master,
    download_plan,
)


def _config(tmp_path: Path) -> AccelPixConfig:
    return AccelPixConfig(api_token="secret-token", store=tmp_path)


def test_config_loads_secret_from_environment_without_exposing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCELPIX_API_TOKEN", "secret-token")
    monkeypatch.setenv("SENSEI_ACCELPIX_DIR", str(tmp_path))

    config = AccelPixConfig.from_environment()

    assert config.api_token == "secret-token"
    assert "secret-token" not in repr(config)
    assert config.store == tmp_path


def test_request_identity_and_safe_uri_never_include_token() -> None:
    request = AccelPixRequest.eod("NIFTY 50", date(2020, 1, 1), date(2020, 1, 31))

    assert request.kind is RequestKind.EOD
    assert request.safe_source_uri.endswith("/NIFTY%2050/20200101/20200131")
    assert "token" not in request.safe_source_uri.lower()
    assert len(request.request_id) == 64


def test_client_sends_token_but_returns_a_credential_safe_payload(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "tkr": "TCS",
                    "td": "2024-01-01 00:00:00",
                    "op": 100,
                    "hp": 110,
                    "lp": 90,
                    "cp": 105,
                    "vol": 1000,
                    "oi": 0,
                    "eod": True,
                }
            ],
        )

    client = AccelPixClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )
    payload = client.fetch(
        AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    )

    assert seen[0].url.params["api_token"] == "secret-token"
    assert "secret-token" not in repr(payload)
    assert "secret-token" not in payload.source_uri


def test_master_request_preserves_json_format_parameter(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    client = AccelPixClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )

    client.fetch(AccelPixRequest.master())

    assert seen[0].url.params["fmt"] == "json"
    assert seen[0].url.params["api_token"] == "secret-token"


def test_client_honors_retry_after_for_throttling(tmp_path: Path) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=[])

    client = AccelPixClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=sleeps.append,
    )

    client.fetch(AccelPixRequest.master())

    assert 7.0 in sleeps


def test_download_persists_safe_terminal_failure(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"secret_vendor_message": "do not store"})

    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    plan = AccelPixPlan("test-plan", (request,))
    store = AccelPixStore(tmp_path / "store")
    client = AccelPixClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )

    with pytest.raises(AccelPixRequestError):
        download_plan(plan, client=client, store=store)

    failure = json.loads(store.failure_path(request).read_text(encoding="utf-8"))
    assert failure["classification"] == "authorization_error"
    assert failure["status_code"] == 403
    assert "secret_vendor_message" not in json.dumps(failure)
    assert store.audit(plan).failures == 1

    network_calls = 0

    def should_not_run(_: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(200, json=[])

    resumed_client = AccelPixClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(should_not_run)),
        sleeper=lambda _: None,
    )
    with pytest.raises(AccelPixError, match="terminal failure checkpoint"):
        download_plan(plan, client=resumed_client, store=store)
    assert network_calls == 0


@pytest.mark.parametrize(
    "content_type,body",
    [
        ("text/html", b"<html>login</html>"),
        ("application/json", b'{"error":"unauthorized"}'),
    ],
)
def test_client_does_not_store_success_status_error_bodies(
    tmp_path: Path, content_type: str, body: bytes
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    client = AccelPixClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )

    with pytest.raises(AccelPixError, match="valid JSON data array"):
        client.fetch(AccelPixRequest.master())


def test_plan_is_credential_free_and_bounded(tmp_path: Path) -> None:
    plan = AccelPixPlan.for_eod(
        symbols=("TCS", "INFY"),
        start=date(2019, 1, 1),
        end=date(2023, 12, 31),
    )
    path = tmp_path / "plan.json"
    plan.write(path)

    written = path.read_text()
    restored = AccelPixPlan.read(path)
    assert len(restored.requests) == 2
    assert "token" not in written.lower()
    assert restored.plan_id == plan.plan_id


def test_store_audit_detects_tampering(tmp_path: Path) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    store = AccelPixStore(tmp_path)
    artifact = store.put(
        request,
        content=b"[]",
        content_type="application/json",
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    plan = AccelPixPlan("test-plan", (request,))

    assert store.audit(plan).verified == 1
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    assert manifest["classification"] == "no_data"
    assert manifest["rows"] == 0
    assert manifest["status_code"] == 200
    artifact.payload_path.write_bytes(b"tampered")
    with pytest.raises(AccelPixError, match="(byte count|hash) mismatch"):
        store.audit(plan)


def test_store_audit_detects_manifest_byte_count_tampering(tmp_path: Path) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    store = AccelPixStore(tmp_path)
    artifact = store.put(
        request,
        content=b"[]",
        content_type="application/json",
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    manifest["bytes"] = 999
    artifact.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AccelPixError, match="byte count mismatch"):
        store.audit(AccelPixPlan("test-plan", (request,)))


def test_normalize_eod_plan_writes_canonical_parquet(tmp_path: Path) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    plan = AccelPixPlan("test-plan", (request,))
    store = AccelPixStore(tmp_path / "store")
    store.put(
        request,
        content=json.dumps(
            [
                {
                    "tkr": "TCS",
                    "td": "2024-01-01 00:00:00",
                    "op": 100,
                    "hp": 110,
                    "lp": 90,
                    "cp": 105,
                    "vol": 1000,
                    "oi": 0,
                    "eod": True,
                }
            ]
        ).encode(),
        content_type="application/json",
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    output = tmp_path / "eod.parquet"

    result = normalize_eod_plan(plan, store=store, output=output)
    frame = pd.read_parquet(output)

    assert result == {"symbols": 1, "rows": 1}
    assert frame.to_dict("records") == [
        {
            "symbol": "TCS",
            "date": pd.Timestamp("2024-01-01"),
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 1000,
            "open_interest": 0,
        }
    ]
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert manifest["stamp"] == ACCELPIX_STAMP
    assert manifest["admissible"] is False


def test_normalizer_rejects_invalid_ohlc(tmp_path: Path) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    plan = AccelPixPlan("test-plan", (request,))
    store = AccelPixStore(tmp_path / "store")
    store.put(
        request,
        content=b'[{"tkr":"TCS","td":"2024-01-01","op":100,"hp":90,"lp":95,"cp":100,"vol":1,"oi":0,"eod":true}]',
        content_type="application/json",
        retrieved_at=datetime.now(timezone.utc),
    )

    with pytest.raises(AccelPixError, match="invalid OHLC"):
        normalize_eod_plan(plan, store=store, output=tmp_path / "bad.parquet")


@pytest.mark.parametrize(
    "row,error",
    [
        (
            '{"tkr":"TCS","td":"2023-12-31","op":100,"hp":110,"lp":90,"cp":100,"vol":1,"oi":0,"eod":true}',
            "outside its request window",
        ),
        (
            '{"tkr":"TCS","td":"2024-01-01","op":100,"hp":110,"lp":90,"cp":100,"vol":1,"oi":0,"eod":false}',
            "not marked as EOD",
        ),
    ],
)
def test_normalizer_rejects_wrong_session_or_bar_kind(
    tmp_path: Path, row: str, error: str
) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    plan = AccelPixPlan("test-plan", (request,))
    store = AccelPixStore(tmp_path / "store")
    store.put(
        request,
        content=f"[{row}]".encode(),
        content_type="application/json",
        retrieved_at=datetime.now(timezone.utc),
    )

    with pytest.raises(AccelPixError, match=error):
        normalize_eod_plan(plan, store=store, output=tmp_path / "bad.parquet")


def test_normalizer_rejects_fractional_volume(tmp_path: Path) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    plan = AccelPixPlan("test-plan", (request,))
    store = AccelPixStore(tmp_path / "store")
    store.put(
        request,
        content=b'[{"tkr":"TCS","td":"2024-01-01","op":100,"hp":110,"lp":90,"cp":100,"vol":1.5,"oi":0,"eod":true}]',
        content_type="application/json",
        retrieved_at=datetime.now(timezone.utc),
    )

    with pytest.raises(AccelPixError, match="invalid volume"):
        normalize_eod_plan(plan, store=store, output=tmp_path / "bad.parquet")


def test_symbols_are_selected_from_verified_equity_master(tmp_path: Path) -> None:
    request = AccelPixRequest.master()
    store = AccelPixStore(tmp_path / "store")
    store.put(
        request,
        content=json.dumps(
            [
                {"xid": 1, "inst": "EQUITY", "tkr": "TCS"},
                {"xid": "1", "inst": "EQUITY", "tkr": "INFY"},
                {"xid": 2, "inst": "FUTSTK", "tkr": "TCS26SEP"},
            ]
        ).encode(),
        content_type="application/json",
        retrieved_at=datetime.now(timezone.utc),
    )

    assert symbols_from_master(store) == ("INFY", "TCS")


def test_cli_plan_reads_universe_csv_without_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    universe = tmp_path / "universe.csv"
    universe.write_text(
        "company,industry,symbol,Series,isin\n"
        "Tata Consultancy,IT,TCS,EQ,INE000000001\n"
        "Infosys,IT,INFY,EQ,INE000000002\n",
        encoding="utf-8",
    )
    output = tmp_path / "plan.json"
    master_store = AccelPixStore(tmp_path / "master")
    master_store.put(
        AccelPixRequest.master(),
        content=b'[{"xid":1,"inst":"EQUITY","tkr":"TCS"},{"xid":1,"inst":"EQUITY","tkr":"INFY"}]',
        content_type="application/json",
        retrieved_at=datetime.now(timezone.utc),
    )

    assert (
        accelpix_cli.main(
            [
                "plan",
                "--symbols",
                str(universe),
                "--master-store",
                str(master_store.root),
                "--start",
                "2021-09-01",
                "--end",
                "2026-09-01",
                "--maximum-symbols",
                "250",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PLANNED"
    assert result["requests"] == 2
    assert result["admissible"] is False
    assert "api_token" not in output.read_text(encoding="utf-8")


def test_cli_audit_is_read_only_and_reports_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = AccelPixRequest.eod("TCS", date(2024, 1, 1), date(2024, 1, 2))
    plan = AccelPixPlan("test-plan", (request,))
    plan_path = tmp_path / "plan.json"
    plan.write(plan_path)
    store = AccelPixStore(tmp_path / "store")
    store.put(
        request,
        content=b"[]",
        content_type="application/json",
        retrieved_at=datetime.now(timezone.utc),
    )

    assert (
        accelpix_cli.main(
            ["audit", "--plan", str(plan_path), "--store", str(store.root)]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "admissible": False,
        "expected": 1,
        "failures": 0,
        "missing": 0,
        "stamp": ACCELPIX_STAMP,
        "status": "VERIFIED",
        "verified": 1,
    }


def test_cli_eod_probe_rejects_empty_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ACCELPIX_API_TOKEN", "secret-token")
    monkeypatch.setattr(
        accelpix_cli.AccelPixClient,
        "fetch",
        lambda _self, request: FetchedPayload(
            content=b"[]",
            content_type="application/json",
            retrieved_at=datetime.now(timezone.utc),
            source_uri=request.safe_source_uri,
            status_code=200,
        ),
    )

    assert (
        accelpix_cli.main(
            [
                "probe-eod",
                "--ticker",
                "TCS",
                "--start",
                "2026-08-24",
                "--end",
                "2026-08-28",
            ]
        )
        == 2
    )
    assert "returned no sessions" in capsys.readouterr().err


@pytest.mark.parametrize("returned_dates,expected_status,exit_code", [
    ([], "REQUIRED_SESSIONS_MISSING", 2),
    (["2024-01-19", "2024-01-23"], "REQUIRED_SESSIONS_MISSING", 2),
    (["2024-01-19", "2024-01-20", "2024-01-23"], "REQUIRED_SESSIONS_PRESENT", 0),
])
def test_eod_probe_checks_required_special_session(returned_dates, expected_status, exit_code,
                                                  monkeypatch, capsys):
    monkeypatch.setenv("ACCELPIX_API_TOKEN", "secret-token")
    content = json.dumps([{"tkr": "TCS", "td": day, "op": 100, "hp": 110,
        "lp": 90, "cp": 105, "vol": 1000, "eod": True} for day in returned_dates]).encode()
    monkeypatch.setattr(accelpix_cli.AccelPixClient, "fetch", lambda _self, request:
        FetchedPayload(content=content, content_type="application/json",
            retrieved_at=datetime.now(timezone.utc), source_uri=request.safe_source_uri, status_code=200))
    result = accelpix_cli.main(["probe-eod", "--ticker", "TCS", "--start", "2024-01-19",
        "--end", "2024-01-23", "--required-session", "2024-01-20", "--required-session", "2024-01-23"])
    assert result == exit_code
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == expected_status
    assert report["missing_sessions"] == sorted({"2024-01-20", "2024-01-23"} - set(returned_dates))
    assert report["observed_sessions"] == returned_dates
    assert report["adjustment_factors_verified"] is False
    assert report["admissible"] is False
    assert "secret-token" not in output
    assert '"cp"' not in output


def test_required_session_outside_window_fails_before_credentials_or_network(monkeypatch, capsys):
    def unexpected_config(*args, **kwargs):
        pytest.fail("must reject the window before reading credentials")
    monkeypatch.setattr(accelpix_cli, "_config", unexpected_config)
    result = accelpix_cli.main(["probe-eod", "--ticker", "TCS", "--start", "2024-01-19",
        "--end", "2024-01-23", "--required-session", "2024-03-02"])
    assert result == 2
    assert "outside the probe window" in capsys.readouterr().err
