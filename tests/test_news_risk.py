from datetime import datetime, timedelta, timezone

import pytest

from sensei.data.news import (
    FinancialMetric,
    CorporateMetricCache,
    NewsEventCategory,
    NseCorporateEventSource,
    NdmaDisasterEventSource,
    SebiEnforcementEventSource,
    NewsEvent,
    NewsRiskBook,
    NewsRiskLevel,
    NewsRiskPolicy,
    NewsSecretStore,
    RssNewsRefresher,
    SignedNewsSnapshot,
    event_identity,
    build_news_event,
)


NOW = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)
SECRET = b"news-risk-test-secret-at-least-32-bytes"


def _event(title: str, *, published_at=NOW, symbols=()):
    affected_symbols = tuple(symbols)
    return build_news_event(
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


def test_policy_fails_closed_when_authoritative_india_source_is_missing():
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=(), successful_sources=("FED", "ECB"),
        failed_sources=("NSE_CORPORATE",), issuer_id="market-news", secret=SECRET,
    )

    decision = NewsRiskPolicy(
        required_sources=frozenset({"NSE_CORPORATE"})
    ).assess(snapshot, instrument_id="NSE:INFY", as_of=NOW)

    assert decision.level is NewsRiskLevel.UNKNOWN
    assert decision.blocked


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


def test_upstream_identity_stays_stable_when_enrichment_content_changes():
    first = build_news_event(
        title="Results filed", source="NSE_CORPORATE",
        source_url="https://nseindia.com/filing/1", published_at=NOW,
        source_event_id="123",
    )
    enriched = build_news_event(
        title="Results filed", source="NSE_CORPORATE",
        source_url="https://nseindia.com/filing/1", published_at=NOW,
        source_event_id="123",
        financial_metrics=(FinancialMetric("revenue", 100.0, "INR_CRORE"),),
    )

    assert first.event_id == enriched.event_id
    assert first.content_digest != enriched.content_digest


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


def test_nse_corporate_source_structures_quarterly_results_and_metrics():
    payload = [{
        "seq_id": "123",
        "symbol": "INFY",
        "an_dt": "19-Jul-2026 08:30:00",
        "desc": "Financial Results",
        "attchmntText": (
            "Financial results for quarter ended June 30, 2026: "
            "revenue Rs 12,500 crore, up 8.5%; "
            "net profit Rs 2,400 crore, down 3.0%"
        ),
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/infy.pdf",
        "smIndustry": "Computers - Software",
    }]
    source = NseCorporateEventSource(fetch_json=lambda _url: payload)

    events = source.fetch(observed_at=NOW, known_instruments=("NSE:INFY",))

    assert len(events) == 1
    event = events[0]
    assert event.category is NewsEventCategory.FINANCIAL_RESULTS
    assert event.affected_symbols == ("NSE:INFY",)
    assert event.attachment_url.endswith("infy.pdf")
    assert event.reporting_period == "quarter ended June 30, 2026"
    assert FinancialMetric("revenue", 12_500.0, "INR_CRORE", 8.5) in event.financial_metrics
    assert FinancialMetric("net_profit", 2_400.0, "INR_CRORE", -3.0) in event.financial_metrics


def test_nse_result_attachment_metrics_are_extracted_once_and_cached(tmp_path):
    payload = [{
        "seq_id": "124", "symbol": "INFY",
        "an_dt": "19-Jul-2026 08:30:00", "desc": "Financial Results",
        "attchmntText": "Results for quarter ended June 2026",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/results.pdf",
    }]
    reads = []
    source = NseCorporateEventSource(
        fetch_json=lambda _url: payload,
        metric_cache=CorporateMetricCache(tmp_path / "metrics.json"),
        attachment_text=lambda url: (
            reads.append(url) or (
                "sha256:filing-v1",
                "Revenue Rs 900 crore, up 12%; EBITDA Rs 180 crore",
            )
        ),
    )

    first = source.fetch(observed_at=NOW, known_instruments=("NSE:INFY",))
    second = source.fetch(observed_at=NOW, known_instruments=("NSE:INFY",))

    # The URL is mutable; each refresh verifies the bytes, then reuses extraction.
    assert len(reads) == 2
    assert first[0].financial_metrics == second[0].financial_metrics
    assert FinancialMetric("revenue", 900.0, "INR_CRORE", 12.0) in first[0].financial_metrics


def test_material_company_filings_have_deterministic_entry_policy():
    result = _event("Quarterly financial results filed", symbols=("NSE:INFY",))
    result = result.with_category(NewsEventCategory.FINANCIAL_RESULTS)
    insolvency = _event("Insolvency petition admitted", symbols=("NSE:TCS",)).with_category(
        NewsEventCategory.INSOLVENCY
    )
    snapshot = SignedNewsSnapshot.issue(
        observed_at=NOW, events=(result, insolvency),
        successful_sources=("NSE_CORPORATE",), failed_sources=(),
        issuer_id="market-news", secret=SECRET,
    )
    policy = NewsRiskPolicy()

    result_decision = policy.assess(snapshot, instrument_id="NSE:INFY", as_of=NOW)
    assert result_decision.level is NewsRiskLevel.CAUTION
    assert not result_decision.blocked
    assert policy.assess(snapshot, instrument_id="NSE:TCS", as_of=NOW).blocked


def test_ndma_alerts_are_structured_by_region_and_severity():
    payload = [{
        "identifier": 42,
        "severity": "ALERT",
        "effective_start_time": "Sun Jul 19 07:21:00 IST 2026",
        "effective_end_time": "Sun Jul 19 10:21:00 IST 2026",
        "disaster_type": "Flash Flood",
        "area_description": "Mumbai and Thane districts of Maharashtra",
        "warning_message": "Severe flash flooding is likely",
    }]
    source = NdmaDisasterEventSource(fetch_json=lambda _url: payload)

    events = source.fetch(
        observed_at=NOW,
        company_regions={"NSE:RELIANCE": ("Maharashtra",)},
    )

    assert events[0].category is NewsEventCategory.NATURAL_DISASTER
    assert events[0].affected_symbols == ("NSE:RELIANCE",)
    assert events[0].regions == ("Maharashtra",)


def test_sebi_orders_are_authoritative_and_scoped_to_known_symbols():
    listing = b"""<html><head><title>SEBI | Orders</title></head><body>
      <table><tr><td>Jul 19, 2026</td><td>
      <a href='/enforcement/orders/jul-2026/order-in-reliance_102814.html'>
      Order in the matter of RELIANCE</a></td></tr>
      <tr><td>Jul 19, 2026</td><td><a href='/other.html'>Unknown Co</a></td></tr>
      </table></body></html>"""
    source = SebiEnforcementEventSource(fetch_html=lambda _url: listing)

    events = source.fetch(
        observed_at=NOW,
        known_instruments=("NSE:RELIANCE", "NSE:TCS"),
    )

    assert len(events) == 1
    assert events[0].category is NewsEventCategory.ENFORCEMENT
    assert events[0].affected_symbols == ("NSE:RELIANCE",)
    assert events[0].source == "SEBI_ORDERS"


def test_sebi_markup_failure_is_not_reported_as_successful_coverage():
    source = SebiEnforcementEventSource(
        fetch_html=lambda _url: b"<html><title>Access denied</title></html>"
    )

    with pytest.raises(ValueError, match="schema"):
        source.fetch(observed_at=NOW, known_instruments=("NSE:INFY",))
