from datetime import datetime, timedelta, timezone

import pytest

from sensei.data.news import (
    NewsEvent,
    NewsEventCategory,
    NewsRiskBook,
    NewsRiskLevel,
    NewsRiskPolicy,
    NewsSecretStore,
    NseCorporateEventSource,
    RssNewsRefresher,
    SignedNewsSnapshot,
    event_identity,
)


NOW = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)
SECRET = b"news-risk-test-secret-at-least-32-bytes"


def _event(title: str, *, published_at=NOW, symbols=()):
    affected_symbols = tuple(symbols)
    return NewsEvent(
        event_id=event_identity(
            source="RBI",
            source_url="https://rbi.org.in/press/test",
            published_at=published_at,
            title=title,
            affected_symbols=affected_symbols,
        ),
        title=title,
        source="RBI",
        source_url="https://rbi.org.in/press/test",
        published_at=published_at,
        affected_symbols=affected_symbols,
    )


def test_policy_blocks_critical_global_shock_and_explains_source():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW,
        events=(_event("State of emergency and exchange market closure announced"),),
        successful_sources=("RBI",),
        failed_sources=(),
        issuer_id="market-news",
        secret=SECRET,
    )

    decision = NewsRiskPolicy().assess(
        snapshot,
        instrument_id="NSE:INFY",
        as_of=NOW + timedelta(minutes=5),
    )

    assert decision.level is NewsRiskLevel.BLOCK
    assert decision.blocked is True
    assert decision.event_ids == (snapshot.events[0].event_id,)
    assert "market closure" in decision.reason.lower()


def test_policy_marks_macro_policy_news_as_caution_not_a_trade_signal():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW,
        events=(_event("Central bank announces unexpected interest rate decision"),),
        successful_sources=("RBI",), failed_sources=(),
        issuer_id="market-news", secret=SECRET,
    )

    decision = NewsRiskPolicy().assess(
        snapshot, instrument_id="NSE:TCS", as_of=NOW,
    )

    assert decision.level is NewsRiskLevel.CAUTION
    assert decision.blocked is False


def test_policy_fails_closed_for_stale_or_unverifiable_news():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW - timedelta(hours=2), events=(),
        successful_sources=("RBI",), failed_sources=(),
        issuer_id="market-news", secret=SECRET,
    )
    policy = NewsRiskPolicy(maximum_snapshot_age=timedelta(minutes=60))

    assert policy.assess(
        snapshot, instrument_id="NSE:INFY", as_of=NOW,
    ).level is NewsRiskLevel.UNKNOWN
    with pytest.raises(ValueError, match="signature"):
        NewsRiskBook.verify(snapshot, secret=b"wrong-secret-at-least-32-bytes")


def test_policy_requires_only_essential_nse_company_coverage():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=(), successful_sources=("RBI_RELEASES",),
        failed_sources=("NSE_CORPORATE",), issuer_id="market-news", secret=SECRET,
    )

    decision = NewsRiskPolicy(
        required_sources=frozenset({"NSE_CORPORATE"})
    ).assess(snapshot, instrument_id="NSE:INFY", as_of=NOW)

    assert decision.level is NewsRiskLevel.UNKNOWN
    assert decision.blocked


def test_optional_macro_feed_failure_does_not_create_unknown_state():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=(), successful_sources=("NSE_CORPORATE",),
        failed_sources=("RBI_RELEASES",), issuer_id="market-news", secret=SECRET,
    )

    decision = NewsRiskPolicy(
        required_sources=frozenset({"NSE_CORPORATE"})
    ).assess(snapshot, instrument_id="NSE:INFY", as_of=NOW)

    assert decision.level is NewsRiskLevel.CLEAR


def test_old_headlines_expire_and_do_not_block_new_entries():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW,
        events=(_event(
            "War triggers market closure",
            published_at=NOW - timedelta(days=2),
        ),),
        successful_sources=("RBI",), failed_sources=(),
        issuer_id="market-news", secret=SECRET,
    )

    decision = NewsRiskPolicy(
        maximum_event_age=timedelta(hours=12),
    ).assess(snapshot, instrument_id="NSE:INFY", as_of=NOW)

    assert decision.level is NewsRiskLevel.CLEAR


def test_instrument_specific_critical_event_only_blocks_that_symbol():
    event = _event(
        "Accounting fraud investigation and trading suspension",
        symbols=("NSE:INFY",),
    )
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=(event,), successful_sources=("NSE",),
        failed_sources=(), issuer_id="market-news", secret=SECRET,
    )
    policy = NewsRiskPolicy()

    assert policy.assess(
        snapshot, instrument_id="NSE:INFY", as_of=NOW,
    ).blocked
    assert not policy.assess(
        snapshot, instrument_id="NSE:TCS", as_of=NOW,
    ).blocked


def test_rss_refresher_deduplicates_and_tags_known_nse_symbols(tmp_path):
    rss = b"""<?xml version='1.0'?>
    <rss><channel><item><title>INFY trading suspension announced</title>
    <link>https://nseindia.com/notice/1</link>
    <pubDate>Mon, 20 Jul 2026 03:00:00 GMT</pubDate></item></channel></rss>"""
    book = NewsRiskBook(tmp_path / "news.json", secret=SECRET)
    refresher = RssNewsRefresher(
        book=book,
        issuer_id="market-news",
        secret=SECRET,
        fetch=lambda _url: rss,
    )

    snapshot = refresher.refresh(
        feeds={"NSE": "https://nseindia.com/rss/notices.xml"},
        known_instruments=("NSE:INFY", "NSE:TCS"),
        observed_at=NOW,
    )

    assert snapshot.successful_sources == ("NSE",)
    assert snapshot.events[0].affected_symbols == ("NSE:INFY",)
    assert book.latest() == snapshot


def test_nse_corporate_results_are_symbol_scoped_and_advisory():
    payload = [{
        "seq_id": "123", "symbol": "INFY",
        "an_dt": "20-Jul-2026 08:15:00", "desc": "Financial Results",
        "attchmntText": "Quarterly results for period ended June 2026",
        "attchmntFile": "https://nsearchives.nseindia.com/infy-results.pdf",
    }]
    source = NseCorporateEventSource(fetch_json=lambda _url: payload)

    events = source.fetch(observed_at=NOW, known_instruments=("NSE:INFY",))
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=events, successful_sources=("NSE_CORPORATE",),
        failed_sources=(), issuer_id="market-news", secret=SECRET,
    )
    decision = NewsRiskPolicy().assess(
        snapshot, instrument_id="NSE:INFY", as_of=NOW,
    )

    assert len(events) == 1
    assert events[0].affected_symbols == ("NSE:INFY",)
    assert decision.level is NewsRiskLevel.CAUTION
    assert not decision.blocked


def test_nse_corporate_critical_event_blocks_only_affected_symbol():
    payload = [{
        "symbol": "INFY", "an_dt": "20-Jul-2026 08:15:00",
        "desc": "Trading Suspension", "attchmntText": "Trading suspension notice",
        "attchmntFile": "https://nsearchives.nseindia.com/infy-suspension.pdf",
    }]
    events = NseCorporateEventSource(fetch_json=lambda _url: payload).fetch(
        observed_at=NOW, known_instruments=("NSE:INFY", "NSE:TCS"),
    )
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=events, successful_sources=("NSE_CORPORATE",),
        failed_sources=(), issuer_id="market-news", secret=SECRET,
    )
    policy = NewsRiskPolicy()

    assert policy.assess(snapshot, instrument_id="NSE:INFY", as_of=NOW).blocked
    assert not policy.assess(snapshot, instrument_id="NSE:TCS", as_of=NOW).blocked


@pytest.mark.parametrize("description", [
    "Suspension of Trading",
    "Company suspended from trading",
    "Resignation of Auditor",
    "Qualified Opinion issued by statutory auditor",
])
def test_official_nse_critical_wording_is_normalized_and_blocked(description):
    payload = [{
        "symbol": "INFY", "an_dt": "20-Jul-2026 08:15:00",
        "desc": description, "attchmntText": "Official exchange filing",
        "attchmntFile": "https://nsearchives.nseindia.com/critical.pdf",
    }]
    events = NseCorporateEventSource(fetch_json=lambda _url: payload).fetch(
        observed_at=NOW, known_instruments=("NSE:INFY",),
    )
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=events, successful_sources=("NSE_CORPORATE",),
        failed_sources=(), issuer_id="market-news", secret=SECRET,
    )

    assert events[0].category in {
        NewsEventCategory.TRADING_SUSPENSION,
        NewsEventCategory.AUDITOR_EVENT,
    }
    assert NewsRiskPolicy().assess(
        snapshot, instrument_id="NSE:INFY", as_of=NOW,
    ).blocked


def test_nse_schema_drift_fails_required_source_instead_of_clearing():
    source = NseCorporateEventSource(
        fetch_json=lambda _url: [{"unexpected": "response"}]
    )

    with pytest.raises(ValueError, match="schema"):
        source.fetch(observed_at=NOW, known_instruments=("NSE:INFY",))


def test_news_credential_is_dedicated_owner_only_material(tmp_path):
    path = tmp_path / "news-secret"

    created = NewsSecretStore.load_or_create(path)

    assert len(created) == 32
    assert NewsSecretStore.load(path) == created
    assert path.stat().st_mode & 0o777 == 0o600


def test_news_refresh_failure_cannot_suppress_scheduler_safety_work():
    from sensei.automation.application import GovernedSchedulerApplication

    calls = []
    app = object.__new__(GovernedSchedulerApplication)

    class Runner:
        def run_once(self, now):
            calls.append("safety-work")
            return "completed"

    app.runner = Runner()
    app._refresh_news_if_due = lambda now: (_ for _ in ()).throw(
        RuntimeError("feed outage")
    )
    app._record_news_refresh_failure = lambda now, error: calls.append(
        type(error).__name__
    )

    result = app.run_once(NOW)

    assert result == "completed"
    assert calls == ["safety-work", "RuntimeError"]
