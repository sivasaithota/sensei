import json
from datetime import date, datetime, timezone

import httpx
import pytest

from sensei.data.truedata import (
    Capability,
    PrivateArtifactStore,
    Service,
    TrialPlan,
    TrueDataClient,
    TrueDataConfig,
    TrueDataError,
    TrueDataRequest,
    download_plan,
    expand_detail_plan,
    expand_plan_from_masters,
    extract_record_ids,
    extract_symbols,
    probe_entitlements,
    record_corporate_announcements,
    store_corporate_announcement,
)
from sensei.data.truedata_cli import main as truedata_main


def _config(tmp_path):
    return TrueDataConfig(
        username="trial-user",
        password="trial-password",
        store=tmp_path,
    )


def test_config_reads_credentials_from_environment_without_persisting_them(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TRUEDATA_USERNAME", "trial-user")
    monkeypatch.setenv("TRUEDATA_PASSWORD", "trial-password")
    monkeypatch.setenv("SENSEI_TRUEDATA_DIR", str(tmp_path))

    config = TrueDataConfig.from_environment()

    assert config.username == "trial-user"
    assert config.store == tmp_path
    assert "trial-password" not in repr(config)


def test_client_authenticates_and_never_places_credentials_in_data_request_url(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "auth.truedata.in":
            return httpx.Response(200, json={"access_token": "short-lived-token"})
        assert request.headers["authorization"] == "Bearer short-lived-token"
        return httpx.Response(200, content=b"timestamp,open,high,low,close,volume\n")

    client = TrueDataClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )
    payload = client.fetch(
        TrueDataRequest(
            service=Service.HISTORY,
            endpoint="getbars",
            params={"symbol": "RELIANCE", "interval": "eod"},
        )
    )

    assert payload.content.startswith(b"timestamp")
    request_url = str(seen[-1].url)
    assert "trial-user" not in request_url
    assert "trial-password" not in request_url
    assert "short-lived-token" not in request_url


def test_request_rejects_secret_bearing_params():
    with pytest.raises(ValueError, match="credentials"):
        TrueDataRequest(
            service=Service.HISTORY,
            endpoint="getbars",
            params={"symbol": "TCS", "password": "do-not-store"},
        )


def test_artifact_store_is_content_verified_and_resumable(tmp_path):
    store = PrivateArtifactStore(tmp_path)
    request = TrueDataRequest(
        service=Service.HISTORY,
        endpoint="getbars",
        params={"symbol": "TCS", "interval": "eod"},
    )
    payload = type("Payload", (), {
        "content": b"timestamp,open,high,low,close,volume\n2026-08-17,1,2,1,2,10\n",
        "content_type": "text/csv",
        "retrieved_at": datetime(2026, 8, 18, tzinfo=timezone.utc),
        "source_uri": "https://history.truedata.in/getbars",
        "status_code": 200,
    })()

    stored = store.save(request, payload)

    assert stored.payload_path.stat().st_mode & 0o077 == 0
    assert store.verified(request) is not None
    stored.payload_path.write_bytes(b"tampered")
    assert store.verified(request) is None


def test_artifact_store_preserves_retrieval_revisions(tmp_path):
    store = PrivateArtifactStore(tmp_path)
    request = TrueDataRequest(Service.HISTORY, "getbars", {"symbol": "TCS"})

    def payload(content, minute):
        return type("Payload", (), {
            "content": content,
            "content_type": "text/csv",
            "retrieved_at": datetime(2026, 8, 18, 10, minute, tzinfo=timezone.utc),
            "source_uri": request.safe_source_uri,
            "status_code": 200,
        })()

    first = store.save(request, payload(b"date,close\n2026-08-18,1\n", 1))
    second = store.save(
        request,
        payload(b"date,close\n2026-08-18,2\n", 2),
        replace_checkpoint=True,
    )

    revisions = list((second.manifest_path.parent / "revisions").glob("*.json"))
    assert first.payload_path.exists()
    assert second.payload_path.exists()
    assert first.payload_path != second.payload_path
    assert len(revisions) == 2


def test_corporate_announcement_is_stored_privately_without_credentials(tmp_path):
    store = PrivateArtifactStore(tmp_path)
    content = json.dumps(
        {
            "id": 89016,
            "Symbol_Nse": "TCS",
            "HeadLine": "Board meeting outcome",
            "Tradedate": "18/08/2026 10:00:00",
        }
    )

    artifact, stored = store_corporate_announcement(
        store,
        content,
        retrieved_at=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    manifest = json.loads(artifact.manifest_path.read_text())
    assert stored is True
    assert manifest["request"]["endpoint"] == "websocket-announcement"
    assert manifest["request"]["params"] == {"announcement_id": "89016"}
    assert manifest["source_uri"] == "wss://corp.truedata.in:9092"
    assert "trial-password" not in artifact.manifest_path.read_text()


def test_corporate_announcement_deduplicates_replayed_message(tmp_path):
    store = PrivateArtifactStore(tmp_path)
    content = json.dumps({"id": 89016, "HeadLine": "Result"})

    first, first_stored = store_corporate_announcement(store, content)
    second, second_stored = store_corporate_announcement(store, content)

    assert first_stored is True
    assert second_stored is False
    assert first.payload_path == second.payload_path
    assert len(list((first.manifest_path.parent / "revisions").glob("*.json"))) == 1


def test_corporate_announcement_rejects_unidentified_or_oversized_messages(tmp_path):
    store = PrivateArtifactStore(tmp_path)

    with pytest.raises(TrueDataError, match="announcement id"):
        store_corporate_announcement(store, json.dumps({"HeadLine": "Missing id"}))

    with pytest.raises(TrueDataError, match="safety limit"):
        store_corporate_announcement(store, "x" * 1_000_001)


def test_corporate_recorder_reconnects_and_checkpoints_without_secret_metadata(tmp_path):
    class Clock:
        value = -0.25

        def __call__(self):
            self.value += 0.25
            return self.value

    class Connection:
        messages = iter(
            (
                json.dumps({"success": True, "message": "connected"}),
                json.dumps({"id": 42, "HeadLine": "Quarterly results"}),
            )
        )

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def recv(self, *, timeout):
            assert timeout > 0
            try:
                return next(self.messages)
            except StopIteration:
                raise TimeoutError from None

    attempts = []

    def connector(uri, **kwargs):
        attempts.append((uri, kwargs))
        if len(attempts) == 1:
            raise OSError("temporary connection failure")
        return Connection()

    result = record_corporate_announcements(
        _config(tmp_path),
        duration_seconds=2,
        connector=connector,
        sleeper=lambda _delay: None,
        clock=Clock(),
    )

    assert result.received == 2
    assert result.stored == 1
    assert result.ignored == 1
    assert result.rejected == 0
    assert result.reconnects == 1
    assert result.connected is True
    assert result.authorization_failed is False
    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1
    assert "trial-password" not in manifests[0].read_text()


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), float("-inf"), 0])
def test_corporate_recorder_requires_a_finite_positive_duration(tmp_path, duration):
    with pytest.raises(ValueError, match="duration"):
        record_corporate_announcements(_config(tmp_path), duration_seconds=duration)


def test_corporate_recorder_fails_closed_when_every_connection_attempt_fails(tmp_path):
    class Clock:
        value = -0.5

        def __call__(self):
            self.value += 0.5
            return self.value

    result = record_corporate_announcements(
        _config(tmp_path),
        duration_seconds=2,
        connector=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
        sleeper=lambda _delay: None,
        clock=Clock(),
    )

    assert result.connected is False
    assert result.authorization_failed is False
    assert result.reconnects > 0


def test_corporate_recorder_stops_on_negative_authorization_control_frame(tmp_path):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def recv(self, *, timeout):
            return json.dumps({"success": False, "message": "denied"})

    result = record_corporate_announcements(
        _config(tmp_path),
        duration_seconds=60,
        connector=lambda *_args, **_kwargs: Connection(),
    )

    assert result.connected is False
    assert result.authorization_failed is True
    assert result.received == 1


def test_corporate_recorder_fails_on_message_less_denial_after_connection(tmp_path):
    class Connection:
        messages = iter(({"success": True}, {"success": False, "error": "denied"}))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def recv(self, *, timeout):
            return json.dumps(next(self.messages))

    result = record_corporate_announcements(
        _config(tmp_path),
        duration_seconds=60,
        connector=lambda *_args, **_kwargs: Connection(),
    )

    assert result.connected is True
    assert result.authorization_failed is True
    assert result.received == 2


def test_artifact_verification_rejects_declared_size_above_bound(tmp_path):
    request = TrueDataRequest(Service.HISTORY, "getbars", {"symbol": "TCS"})
    store = PrivateArtifactStore(tmp_path, max_artifact_bytes=10)
    with pytest.raises(TrueDataError, match="safety limit"):
        store.save(
            request,
            type("Payload", (), {
                "content": b"date,close\n2026-08-18,1\n",
                "content_type": "text/csv",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })(),
        )


def test_downloader_skips_a_verified_request_on_resume(tmp_path):
    request = TrueDataRequest(Service.HISTORY, "getbars", {"symbol": "TCS"})
    store = PrivateArtifactStore(tmp_path)

    class Client:
        calls = 0

        def fetch(self, _request):
            self.calls += 1
            return type("Payload", (), {
                "content": b"date,close\n2026-08-18,1\n",
                "content_type": "text/csv",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": "https://history.truedata.in/getbars",
                "status_code": 200,
            })()

    client = Client()
    first = download_plan(TrialPlan("trial", (request,)), client=client, store=store)
    second = download_plan(TrialPlan("trial", (request,)), client=client, store=store)

    assert first.stored == 1 and first.skipped == 0
    assert second.stored == 0 and second.skipped == 1
    assert client.calls == 1


def test_transient_responses_are_retried_without_leaking_credentials(tmp_path):
    attempts = 0

    def handler(request):
        nonlocal attempts
        if request.url.host == "auth.truedata.in":
            return httpx.Response(200, json={"access_token": "token"})
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=b"ok")

    client = TrueDataClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )
    result = client.fetch(TrueDataRequest(Service.CORPORATE, "getResultList", {}))

    assert result.content == b"ok"
    assert attempts == 2


def test_master_transport_failure_drops_secret_bearing_exception_context(tmp_path):
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    client = TrueDataClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
        maximum_attempts=1,
    )

    with pytest.raises(TrueDataError) as raised:
        client.fetch(TrueDataRequest(Service.MASTER, "getAllSymbols", {"segment": "eq"}))

    assert raised.value.__cause__ is None
    assert "trial-password" not in str(raised.value)


def test_authentication_failure_drops_secret_bearing_exception_context(tmp_path):
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    client = TrueDataClient(
        _config(tmp_path),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )

    with pytest.raises(TrueDataError) as raised:
        client.authenticate()

    assert raised.value.__cause__ is None
    assert "trial-password" not in str(raised.value)


def test_trial_plan_covers_vendor_enabled_bulk_endpoints():
    plan = TrialPlan.for_trial(
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 17),
        corporate_start=date(2026, 8, 17),
        segments=("eq", "in"),
        symbols=("RELIANCE",),
    )

    endpoints = {request.endpoint for request in plan.requests}
    assert {
        "getAllSymbols",
        "getbars",
        "getbhavcopy",
        "getResultList",
        "getSHPListByDate",
        "getcorpactionrange",
        "getsymbolchangehistory",
    } <= endpoints
    assert all("password" not in request.params for request in plan.requests)

    corp_actions = next(
        request for request in plan.requests if request.endpoint == "getcorpactionrange"
    )
    assert corp_actions.service is Service.HISTORY
    assert set(corp_actions.params) == {"exdatefrom", "exdateto", "response"}
    masters = [request for request in plan.requests if request.endpoint == "getAllSymbols"]
    assert masters and all(request.params["csvHeader"] is True for request in masters)


def test_confirmed_corporate_plan_does_not_assume_market_history_entitlement():
    plan = TrialPlan.for_trial(
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        capabilities=(Capability.CORPORATE,),
    )

    assert {request.service for request in plan.requests} == {Service.CORPORATE}
    assert {request.endpoint for request in plan.requests} == {
        "getResultList",
        "getSHPListByDate",
    }


def test_bounded_entitlement_probe_reports_each_service_without_storing_payloads():
    seen = []

    class Client:
        def fetch(self, request):
            seen.append(request)
            content = (
                b"No Data exists for Symbol/Date Range"
                if request.service is Service.CORPORATE
                else b"symbol,status\nRELIANCE,ready\n"
                if request.service is Service.MASTER
                else b"date,status\n2026-08-18,ready\n"
            )
            return type("Payload", (), {
                "content": content,
                "content_type": "text/plain" if request.service is Service.CORPORATE else "text/csv",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })()

    results = probe_entitlements(Client(), as_of=date(2026, 8, 18))

    assert {result.capability for result in results} == set(Capability)
    assert all(result.accessible for result in results)
    assert {request.endpoint for request in seen} == {
        "getResultList",
        "getbhavcopystatus",
        "getAllSymbols",
    }


def test_entitlement_probe_only_calls_selected_capabilities_and_fails_unknown_json():
    seen = []

    class Client:
        def fetch(self, request):
            seen.append(request)
            return type("Payload", (), {
                "content": b'{"message":"subscription inactive"}',
                "content_type": "application/json",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })()

    results = probe_entitlements(
        Client(),
        as_of=date(2026, 8, 18),
        capabilities=(Capability.CORPORATE,),
    )

    assert len(seen) == 1
    assert results == (
        type(results[0])(Capability.CORPORATE, False, "error"),
    )


def test_trial_plan_rejects_windows_beyond_vendor_trial_limits():
    with pytest.raises(ValueError, match="730"):
        TrialPlan.for_trial(
            as_of=date(2026, 8, 18),
            eod_start=date(2024, 8, 17),
            corporate_start=date(2026, 8, 18),
        )


def test_audit_reports_missing_and_verified_requests(tmp_path):
    plan = TrialPlan.for_trial(
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        segments=("eq",),
        symbols=(),
    )
    store = PrivateArtifactStore(tmp_path)

    audit = store.audit(plan)

    assert audit.total == len(plan.requests)
    assert audit.verified == 0
    assert audit.missing == audit.total


def test_audit_separates_integrity_from_no_data_coverage(tmp_path):
    request = TrueDataRequest(Service.HISTORY, "getbars", {"symbol": "DELISTED"})
    plan = TrialPlan("coverage", (request,))
    store = PrivateArtifactStore(tmp_path)
    store.save(
        request,
        type("Payload", (), {
            "content": b"No Data exists for <Symbol>",
            "content_type": "text/plain",
            "retrieved_at": datetime.now(timezone.utc),
            "source_uri": request.safe_source_uri,
            "status_code": 200,
        })(),
    )

    audit = store.audit(plan)

    assert audit.verified == 1
    assert audit.data == 0
    assert audit.no_data == 1


def test_audit_profiles_eod_date_and_duplicate_coverage(tmp_path):
    request = TrueDataRequest(
        Service.HISTORY,
        "getbars",
        {
            "symbol": "TCS",
            "from": "260817T00:00:00",
            "to": "260818T23:59:59",
        },
    )
    plan = TrialPlan("coverage", (request,))
    store = PrivateArtifactStore(tmp_path)
    store.save(
        request,
        type("Payload", (), {
            "content": (
                b"date,close\n2026-08-17,1\n2026-08-18,2\n2026-08-18,2\n"
            ),
            "content_type": "text/csv",
            "retrieved_at": datetime.now(timezone.utc),
            "source_uri": request.safe_source_uri,
            "status_code": 200,
        })(),
    )

    audit = store.audit(plan)

    assert audit.eod_requests == 1
    assert audit.eod_with_data == 1
    assert audit.eod_rows == 3
    assert audit.eod_earliest == "2026-08-17"
    assert audit.eod_latest == "2026-08-18"
    assert audit.eod_duplicate_dates == 1
    assert audit.eod_range_gaps == 0


def test_audit_rejects_eod_csv_without_parseable_dates(tmp_path):
    request = TrueDataRequest(Service.HISTORY, "getbars", {"symbol": "TCS"})
    plan = TrialPlan("invalid-eod", (request,))
    store = PrivateArtifactStore(tmp_path)
    store.save(
        request,
        type("Payload", (), {
            "content": b"date,close\nnot-a-date,1\n",
            "content_type": "text/csv",
            "retrieved_at": datetime.now(timezone.utc),
            "source_uri": request.safe_source_uri,
            "status_code": 200,
        })(),
    )

    audit = store.audit(plan)

    assert audit.data == 0
    assert audit.error == 1
    assert audit.eod_invalid == 1


def test_vendor_error_payload_is_evidence_but_is_retried_on_resume(tmp_path):
    request = TrueDataRequest(Service.CORPORATE, "getResultList", {})
    plan = TrialPlan("errors", (request,))
    store = PrivateArtifactStore(tmp_path)

    class Client:
        calls = 0

        def fetch(self, _request):
            self.calls += 1
            return type("Payload", (), {
                "content": b"API calls quota exceeded!",
                "content_type": "text/plain",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })()

    client = Client()
    first = download_plan(plan, client=client, store=store)
    second = download_plan(plan, client=client, store=store)

    assert first.failed == 1 and first.stored == 0
    assert second.failed == 1 and second.skipped == 0
    assert client.calls == 2
    assert store.audit(plan).error == 1


def test_unknown_html_response_fails_closed(tmp_path):
    request = TrueDataRequest(Service.HISTORY, "getbars", {"symbol": "TCS"})
    plan = TrialPlan("proxy", (request,))
    store = PrivateArtifactStore(tmp_path)

    class Client:
        def fetch(self, _request):
            return type("Payload", (), {
                "content": b"<html><title>Gateway</title></html>",
                "content_type": "text/html",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })()

    result = download_plan(plan, client=Client(), store=store)

    assert result.failed == 1
    assert store.audit(plan).error == 1


def test_client_rejects_oversized_responses_before_storage(tmp_path):
    def handler(request):
        if request.url.host == "auth.truedata.in":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(200, content=b"x" * 11)

    config = _config(tmp_path)
    client = TrueDataClient(
        config,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
        max_response_bytes=10,
    )

    with pytest.raises(TrueDataError, match="safety limit"):
        client.fetch(TrueDataRequest(Service.HISTORY, "getbars", {}))


def test_plan_round_trip_contains_no_credentials(tmp_path):
    plan = TrialPlan.for_trial(
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        segments=("eq",),
        symbols=("TCS",),
    )
    path = tmp_path / "plan.json"

    plan.write(path)
    restored = TrialPlan.read(path)

    assert restored == plan
    encoded = path.read_text()
    assert "password" not in encoded.lower()
    assert json.loads(encoded)["stamp"].startswith("PRELIMINARY_VENDOR_TRIAL")


def test_cli_plans_and_audits_without_credentials(tmp_path, capsys):
    plan_path = tmp_path / "trial-plan.json"
    store_path = tmp_path / "private-store"

    assert truedata_main(
        [
            "plan",
            "--as-of",
            "2026-08-18",
            "--eod-start",
            "2026-08-18",
            "--corporate-start",
            "2026-08-18",
            "--output",
            str(plan_path),
        ]
    ) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "PLANNED"
    assert planned["admissible"] is False
    assert planned["requests_by_service"] == {"corporate": 2}

    assert truedata_main(
        ["audit", "--plan", str(plan_path), "--store", str(store_path)]
    ) == 1
    audited = json.loads(capsys.readouterr().out)
    assert audited["verified"] == 0
    assert audited["missing"] == audited["total"]


def test_cli_records_corporate_announcements_to_selected_private_store(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("TRUEDATA_USERNAME", "trial-user")
    monkeypatch.setenv("TRUEDATA_PASSWORD", "trial-password")

    def record(config, *, duration_seconds):
        assert config.store == tmp_path
        assert duration_seconds == 60
        return type(
            "Result",
            (),
            {
                "received": 3,
                "stored": 2,
                "duplicates": 1,
                "ignored": 2,
                "rejected": 0,
                "reconnects": 1,
                "connected": True,
                "authorization_failed": False,
            },
        )()

    monkeypatch.setattr(
        "sensei.data.truedata_cli.record_corporate_announcements", record
    )

    assert truedata_main(
        [
            "record-announcements",
            "--store",
            str(tmp_path),
            "--duration-seconds",
            "60",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "RECORDING_COMPLETE"
    assert output["stored"] == 2
    assert output["admissible"] is False


def test_cli_reports_failed_recording_when_no_connection_was_established(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("TRUEDATA_USERNAME", "trial-user")
    monkeypatch.setenv("TRUEDATA_PASSWORD", "trial-password")
    result = type(
        "Result",
        (),
        {
            "received": 0,
            "stored": 0,
            "duplicates": 0,
            "ignored": 0,
            "rejected": 0,
            "reconnects": 3,
            "connected": False,
            "authorization_failed": False,
        },
    )()
    monkeypatch.setattr(
        "sensei.data.truedata_cli.record_corporate_announcements",
        lambda *_args, **_kwargs: result,
    )

    assert truedata_main(
        [
            "record-announcements",
            "--store",
            str(tmp_path),
            "--duration-seconds",
            "1",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "RECORDING_FAILED"


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/csv", b"symbol,id\nRELIANCE,1\nTCS,2\n"),
        (
            "application/json",
            b'{"Records":[{"Symbol":"INFY"},{"symbol":"HDFCBANK"}]}',
        ),
    ],
)
def test_symbol_master_discovery_supports_csv_and_json(content_type, content):
    assert extract_symbols(content, content_type=content_type) == tuple(
        sorted({"RELIANCE", "TCS"} if b"RELIANCE" in content else {"INFY", "HDFCBANK"})
    )


def test_downloaded_master_expands_plan_to_every_discovered_symbol(tmp_path):
    bootstrap = TrialPlan.for_trial(
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        segments=("eq",),
    )
    store = PrivateArtifactStore(tmp_path)
    master = next(
        request for request in bootstrap.requests if request.endpoint == "getAllSymbols"
    )
    store.save(
        master,
        type("Payload", (), {
            "content": b"symbol,id\nRELIANCE,1\nTCS,2\n",
            "content_type": "text/csv",
            "retrieved_at": datetime.now(timezone.utc),
            "source_uri": master.safe_source_uri,
            "status_code": 200,
        })(),
    )

    expanded = expand_plan_from_masters(
        bootstrap,
        store=store,
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        segments=("eq",),
    )

    eod_symbols = {
        request.params["symbol"]
        for request in expanded.requests
        if request.endpoint == "getbars"
    }
    assert eod_symbols == {"RELIANCE", "TCS"}


def test_symbol_change_history_adds_old_and_new_aliases_to_equity_plan(tmp_path):
    bootstrap = TrialPlan.for_trial(
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        segments=("eq",),
    )
    store = PrivateArtifactStore(tmp_path)
    samples = {
        "getAllSymbols": b"symbol,id\nOTHER,1\n",
        "getsymbolchangehistory": b"old_symbol,new_symbol\nOLDNAME,CURRENT\n",
    }
    for request in bootstrap.requests:
        if request.endpoint not in samples:
            continue
        store.save(
            request,
            type("Payload", (), {
                "content": samples[request.endpoint],
                "content_type": "text/csv",
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })(),
        )

    expanded = expand_plan_from_masters(
        bootstrap,
        store=store,
        as_of=date(2026, 8, 18),
        eod_start=date(2026, 8, 18),
        corporate_start=date(2026, 8, 18),
        segments=("eq",),
    )

    symbols = {
        request.params["symbol"]
        for request in expanded.requests
        if request.endpoint == "getbars"
    }
    assert symbols == {"CURRENT", "OLDNAME", "OTHER"}


def test_downloaded_lists_expand_to_fundamental_shareholding_and_attachment_details(
    tmp_path,
):
    requests = (
        TrueDataRequest(Service.CORPORATE, "getResultList", {"date": "2026-08-18"}),
        TrueDataRequest(Service.CORPORATE, "getSHPListByDate", {"date": "2026-08-18"}),
        TrueDataRequest(Service.CORPORATE, "annoucements", {"from": "260818"}),
    )
    plan = TrialPlan("lists", requests)
    store = PrivateArtifactStore(tmp_path)
    samples = (
        (requests[0], b'{"Records":[{"Id":9729}]}', "application/json"),
        (requests[1], b'{"Records":[{"id":306234}]}', "application/json"),
        (requests[2], b"id,trade_date\n78176,2026-08-18\n", "text/csv"),
    )
    for request, content, content_type in samples:
        store.save(
            request,
            type("Payload", (), {
                "content": content,
                "content_type": content_type,
                "retrieved_at": datetime.now(timezone.utc),
                "source_uri": request.safe_source_uri,
                "status_code": 200,
            })(),
        )

    expanded = expand_detail_plan(plan, store=store)
    endpoints = {request.endpoint for request in expanded.requests}

    assert endpoints - {request.endpoint for request in plan.requests} == {
        "getAllResultItemsById",
        "getAllShpById",
        "getannouncementbyid",
        "announcementfile2",
    }
    by_endpoint = {request.endpoint: request for request in expanded.requests}
    assert by_endpoint["announcementfile2"].params == {"id": "78176"}


def test_record_id_extraction_handles_csv_and_json_lists():
    assert extract_record_ids(b"id,name\n12,A\n13,B\n", content_type="text/csv") == ("12", "13")
    assert extract_record_ids(
        b'{"Records":[{"Id":44},{"Id":45}]}', content_type="application/json"
    ) == ("44", "45")
