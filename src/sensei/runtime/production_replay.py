"""Production-faithful historical replay adapters with explicit assumptions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import dataclass
import json
import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path

from sensei.automation import (
    GovernedSchedulerApplication,
    SchedulerApplicationConfig,
)
from sensei.automation.evidence import (
    ImmutableJsonArtifactStore,
    StageEvidencePublisher,
)
from sensei.automation.governed_entry import CandidateMarketDataUnavailable
from sensei.automation.migration import (
    migrate_adopted_strategies,
    publish_pre_shadow_evidence,
)
from sensei.governance.evidence import DossierOutcome
from sensei.governance.lifecycle import EvidenceKind
from sensei.errors import ActionableSchedulerError
from sensei.operations import OperationalJournal
from sensei.runtime.historical_replay import (
    HistoricalDeskReplay,
    HistoricalDeskReplayReport,
    PointInTimePriceView,
    ReplaySessionResult,
)


class ReplayCurrentSessionBarUnavailable(
    CandidateMarketDataUnavailable,
    ActionableSchedulerError,
):
    """A held or evaluated instrument lacks an exact point-in-time bar."""

    reason_code = "REPLAY_CURRENT_SESSION_BAR_UNAVAILABLE"


class ReplayFrameCache:
    """Load each immutable replay price artifact at most once."""

    def __init__(self, *, loader: Callable[[Path], object] | None = None):
        if loader is None:
            import pandas as pd

            loader = pd.read_parquet
        self._loader = loader
        self._frames: dict[Path, object] = {}

    def load(self, path: Path):
        artifact = Path(path)
        if artifact not in self._frames:
            self._frames[artifact] = self._loader(artifact)
        return self._frames[artifact]


@dataclass(frozen=True)
class ReplayArtifactSandbox:
    root: Path
    config_path: Path
    journal_path: Path
    earnings_cache_path: Path

    @classmethod
    def materialize(
        cls, *, source_config_path: Path, root: Path
    ) -> "ReplayArtifactSandbox":
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        raw = json.loads(
            Path(source_config_path).read_text(encoding="utf-8")
        )
        if not isinstance(raw, dict):
            raise ValueError("scheduler config must be a JSON object")
        raw["surveillance_path"] = str(root / "surveillance.json")
        raw["legacy_positions_path"] = str(root / "no-legacy-positions.json")
        raw["provenance_path"] = str(root / "provenance")
        config_path = root / "scheduler.json"
        config_path.write_text(
            json.dumps(raw, sort_keys=True), encoding="utf-8"
        )
        return cls(
            root=root,
            config_path=config_path,
            journal_path=root / "operations.sqlite3",
            earnings_cache_path=root / "earnings_cache.json",
        )


def preregister_replay_plans(
    *,
    journal: OperationalJournal,
    config: SchedulerApplicationConfig,
    rules_path: Path,
    artifact_root: Path,
    occurred_at: datetime,
) -> tuple[str, ...]:
    """Register fixed current plans before observations and authorize PAPER."""

    if journal.read_all():
        raise ValueError("historical replay governance requires a clean journal")
    app = GovernedSchedulerApplication(journal=journal, config=config)
    records = migrate_adopted_strategies(
        journal,
        playbook_path=config.playbook_path,
        rules_path=Path(rules_path),
        artifact_root=config.provenance_path,
        occurred_at=occurred_at,
    ).registered
    publish_pre_shadow_evidence(
        journal,
        app.dossiers,
        records=records,
        playbook_path=config.playbook_path,
        provenance_root=config.provenance_path,
        artifact_root=Path(artifact_root) / "dossiers",
        issuer_id=config.dossier_issuer_id,
        producer_ids_by_kind={
            kind: next(iter(config.producers_by_kind[kind]))
            for kind in (
                EvidenceKind.EXAMINATION_DOSSIER,
                EvidenceKind.CONFORMANCE_DOSSIER,
                EvidenceKind.SHADOW_READINESS,
                EvidenceKind.LOCKED_CONFIRMATION,
            )
        },
        occurred_at=occurred_at,
    )
    for index in range(3):
        app.autopilot.reconcile(
            now=occurred_at,
            command_id=f"replay-preregister:{index}",
        )
    publisher = StageEvidencePublisher(
        journal,
        app.dossiers,
        ImmutableJsonArtifactStore(Path(artifact_root) / "dossiers"),
        issuer_id=config.dossier_issuer_id,
        producer_ids_by_kind={
            kind: next(iter(config.producers_by_kind[kind]))
            for kind in EvidenceKind
        },
    )
    for record in records:
        publisher.publish(
            lineage_id=record.lineage_id,
            plan_version_id=record.plan_id,
            evidence_kind=EvidenceKind.SHADOW_TRIAL,
            outcome=DossierOutcome.PASSED,
            evidence={
                "check": "preregistered_counterfactual_replay",
                "authority": "SIMULATION_ONLY",
                "observations": 0,
                "passed": True,
            },
            occurred_at=occurred_at,
        )
    app.autopilot.reconcile(
        now=occurred_at,
        command_id="replay-preregister:paper",
    )
    return tuple(record.plan_id for record in records)


def publish_replay_surveillance(
    *,
    journal: OperationalJournal,
    config: SchedulerApplicationConfig,
    symbols: tuple[str, ...],
    entry_at: datetime,
):
    """Publish a signed neutral assumption through the final preflight task."""

    import hashlib

    from sensei.automation import SchedulerLedger
    from sensei.automation.scheduling import (
        SchedulerTaskKind,
        SwingSessionPolicy,
    )
    from sensei.operations import EventAppend
    from sensei.runtime import RuntimeSecretStore, VerifiedSurveillanceSource

    observed_at = entry_at.replace(hour=8, minute=51, second=0, microsecond=0)
    content_sha = hashlib.sha256(
        b"sensei-counterfactual-neutral-surveillance-v1"
    ).hexdigest()
    secret = hashlib.sha256(
        b"sensei-historical-replay-surveillance-v1"
    ).digest()
    source_session = entry_at.date()
    from datetime import timedelta
    source_session -= timedelta(days=1)
    while source_session.weekday() >= 5:
        source_session -= timedelta(days=1)
    VerifiedSurveillanceSource.publish(
        config.surveillance_path,
        stages={symbol: 0 for symbol in symbols},
        session=entry_at.date(),
        observed_at=observed_at,
        issuer_id="historical-replay-surveillance",
        secret=secret,
        source_session=source_session,
        source_report_type="COUNTERFACTUAL_NEUTRAL_SURVEILLANCE",
        source_content_sha256=content_sha,
    )
    policy = SwingSessionPolicy(closed_dates=config.closed_dates)
    task = max(
        (
            value for value in policy.due_tasks(observed_at).tasks
            if value.kind is SchedulerTaskKind.SURVEILLANCE_PREFLIGHT
        ),
        key=lambda value: value.due_at,
    )
    claim = SchedulerLedger(journal).claim(task, occurred_at=observed_at)
    event = journal.append(EventAppend(
        stream_id=f"historical-replay-surveillance:{task.task_id}",
        event_type="SurveillancePreflightCompleted",
        payload={
            "schema_version": "1.0",
            "trading_date": entry_at.date().isoformat(),
            "symbols": len(symbols),
            "snapshot_sha256": hashlib.sha256(
                config.surveillance_path.read_bytes()
            ).hexdigest(),
            "source_session": source_session.isoformat(),
            "source_report_type": "COUNTERFACTUAL_NEUTRAL_SURVEILLANCE",
            "source_content_sha256": content_sha,
            "snapshot_ready": True,
            "can_authorize_trading": False,
            "authority": "SIMULATION_ONLY",
        },
        idempotency_key=f"historical-replay-surveillance:{task.task_id}",
        expected_version=0,
        occurred_at=observed_at,
        correlation_id=task.task_id,
    ))
    SchedulerLedger(journal).complete(
        task.task_id,
        claimant_id=claim.record.claimant_id,
        occurred_at=observed_at.replace(second=1),
        detail=f"simulation snapshot {event.event_id}",
        reason_codes=("SURVEILLANCE_PREFLIGHT_READY",),
    )
    return task


def publish_replay_ingestion(
    *,
    journal: OperationalJournal,
    prices_path: Path,
    source_session: date,
    target_session: date,
    occurred_at: datetime,
    eligible_symbols: Sequence[str] | None = None,
    failed_symbols: Sequence[str] | None = None,
):
    """Bind the replay entry universe to bars actually present as of source."""

    import pandas as pd
    from sensei.operations import EventAppend

    paths = tuple(sorted(Path(prices_path).glob("*.parquet")))
    eligible: list[str] = list(eligible_symbols or ())
    failed: list[str] = list(failed_symbols or ())
    if eligible_symbols is None or failed_symbols is None:
        eligible = []
        failed = []
        for path in paths:
            frame = pd.read_parquet(path, columns=["close"])
            sessions = set(pd.to_datetime(frame.index).date)
            (eligible if source_session in sessions else failed).append(path.stem)
    completeness = len(eligible) / len(paths) if paths else 0.0
    return journal.append(EventAppend(
        stream_id=f"historical-replay-ingestion:{target_session.isoformat()}",
        event_type="MarketDataIngestionCompleted",
        payload={
            "schema_version": "1.0",
            "authority": "SIMULATION_ONLY",
            "session": target_session.isoformat(),
            "source_session": source_session.isoformat(),
            "universe_symbols": [path.stem for path in paths],
            "eligible_symbols": eligible,
            "failed_symbols": failed,
            "excluded_symbols": [],
            "completeness": round(completeness, 8),
            "minimum_completeness": 0.99,
            "can_authorize_trading": False,
            "can_authorize_lifecycle": False,
        },
        idempotency_key=(
            "historical-replay-ingestion:"
            f"{source_session.isoformat()}:{target_session.isoformat()}"
        ),
        expected_version=0,
        occurred_at=occurred_at,
    ))


class ReplayProductionPaperSession(
    __import__(
        "sensei.runtime.production", fromlist=["ProductionPaperSession"]
    ).ProductionPaperSession
):
    """Production composition whose market adapters obey one replay clock."""

    def __init__(
        self, *, source_as_of: date, target_as_of: date,
        frame_cache: ReplayFrameCache | None = None, **kwargs,
    ):
        super().__init__(
            **kwargs,
            event_window=lambda _symbol, _on: (
                False,
                "counterfactual replay assumes no earnings blackout",
            ),
            surveillance_report_types=frozenset({
                "COUNTERFACTUAL_NEUTRAL_SURVEILLANCE"
            }),
            surveillance_issuer_id="historical-replay-surveillance",
            surveillance_secret=hashlib.sha256(
                b"sensei-historical-replay-surveillance-v1"
            ).digest(),
            allow_simulation_surveillance=True,
        )
        self._source_as_of = source_as_of
        self._target_as_of = target_as_of
        self._raw_frame_cache = frame_cache or ReplayFrameCache()
        self._frame_cache = {}

    def bind(self, *, source_as_of: date, target_as_of: date) -> None:
        self._source_as_of = source_as_of
        self._target_as_of = target_as_of
        self._frame_cache = {}

    def _bars(self, instrument_id):
        import pandas as pd

        symbol = instrument_id.split(":")[-1]
        cached = self._frame_cache.get(symbol)
        if cached is not None:
            return cached
        frame = self._raw_frame_cache.load(
            self._prices_path / f"{symbol}.parquet"
        )
        index = pd.to_datetime(frame.index)
        frame = frame.loc[index.date <= self._source_as_of].copy()
        if frame.empty or frame.index[-1].date() != self._source_as_of:
            raise ReplayCurrentSessionBarUnavailable(
                f"CURRENT_SESSION_BAR_MISSING:{symbol}:{self._source_as_of}"
            )
        delta = self._target_as_of - self._source_as_of
        frame.index = pd.to_datetime(frame.index) + pd.Timedelta(
            days=delta.days
        )
        self._frame_cache[symbol] = frame
        return frame

    def _quote(self, instrument_id, now):
        from sensei.orchestration import ExecutableQuote
        from sensei.runtime.production import _entry_limit_paise

        frame = self._bars(instrument_id)
        if frame.empty:
            return None
        paise = _entry_limit_paise(
            round(float(frame["close"].iloc[-1]) * 100)
        )
        snapshot = "snapshot:" + hashlib.sha256(
            f"replay:{instrument_id}:{paise}:{now.isoformat()}".encode()
        ).hexdigest()
        return ExecutableQuote(instrument_id, snapshot, paise, now)

    def _execution_observation(self, instrument_id, now):
        from sensei.execution.nse import NseMarketObservation

        frame = self._bars(instrument_id)
        row = frame.iloc[-1]
        reference = round(float(row["close"]) * 100)
        half_spread = max(5, round(reference * 0.0005))
        return NseMarketObservation(
            instrument_id=(
                instrument_id if instrument_id.startswith("NSE:")
                else f"NSE:{instrument_id}"
            ),
            observed_at=now,
            reference_price_paise=reference,
            best_bid_paise=max(1, reference - half_spread),
            best_ask_paise=reference,
            traded_volume=int(max(0, float(row["volume"]))),
            lower_circuit_paise=max(1, round(reference * 0.8)),
            upper_circuit_paise=round(reference * 1.2),
            evidence_source="POINT_IN_TIME_DAILY_BAR_REPLAY",
            spread_is_estimated=True,
            circuit_is_estimated=True,
        )

    def _regime(self):
        from sensei.data.regime import Regime

        above = golden = observed = 0
        for instrument in self._instruments():
            try:
                frame = self._bars(instrument)
            except CandidateMarketDataUnavailable:
                continue
            if len(frame) < 200:
                continue
            close = frame["close"]
            average_50 = close.tail(50).mean()
            average_200 = close.tail(200).mean()
            observed += 1
            above += int(close.iloc[-1] > average_200)
            golden += int(average_50 > average_200)
        return Regime(
            None,
            above / observed * 100 if observed else 0,
            golden / observed * 100 if observed else 0,
            observed,
        )


class ProductionHistoricalDeskReplay:
    """Persistent current-plan counterfactual over historical price sessions."""

    def __init__(
        self,
        *,
        source_config_path: Path,
        rules_path: Path,
        source_sessions: Sequence[date],
        workspace: Path,
        production_fingerprints,
    ) -> None:
        ordered = tuple(source_sessions)
        if len(ordered) < 2:
            raise ValueError("at least two source sessions are required")
        self._source_config_path = Path(source_config_path)
        self._rules_path = Path(rules_path)
        self._source_sessions = ordered
        self._workspace = Path(workspace)
        self._production_fingerprints = production_fingerprints

    def run(self) -> HistoricalDeskReplayReport:
        from zoneinfo import ZoneInfo

        sandbox = ReplayArtifactSandbox.materialize(
            source_config_path=self._source_config_path,
            root=self._workspace,
        )
        config = SchedulerApplicationConfig.from_json(sandbox.config_path)
        journal = OperationalJournal(sandbox.journal_path)
        synthetic_sessions = _future_weekdays(
            datetime.now(ZoneInfo("Asia/Kolkata")).date(),
            len(self._source_sessions) - 1,
        )
        preregister_at = datetime.combine(
            synthetic_sessions[0] - timedelta(days=1),
            datetime.min.time(),
            tzinfo=ZoneInfo("Asia/Kolkata"),
        )
        preregister_replay_plans(
            journal=journal,
            config=config,
            rules_path=self._rules_path,
            artifact_root=sandbox.root / "governance",
            occurred_at=preregister_at,
        )
        executor = _ProductionSessionExecutor(
            sandbox=sandbox,
            config=config,
            source_sessions=self._source_sessions,
            synthetic_sessions=synthetic_sessions,
        )
        return HistoricalDeskReplay(
            prices_path=config.prices_path,
            sessions=self._source_sessions[1:],
            execute_session=executor,
            production_fingerprints=self._production_fingerprints,
        ).run()


class _ProductionSessionExecutor:
    def __init__(
        self, *, sandbox, config, source_sessions, synthetic_sessions
    ) -> None:
        self._sandbox = sandbox
        self._config = config
        self._source_sessions = source_sessions
        self._synthetic_sessions = synthetic_sessions
        self._index = 0
        self._eligibility = _eligibility_by_session(
            config.prices_path, source_sessions
        )
        self._frame_cache = ReplayFrameCache()

    def __call__(
        self, source_session: date, _view: PointInTimePriceView
    ) -> ReplaySessionResult:
        from sensei.automation.scheduling import SchedulerTaskKind
        from zoneinfo import ZoneInfo

        current_index = self._index
        synthetic = self._synthetic_sessions[current_index]
        previous_synthetic = synthetic - timedelta(days=1)
        while previous_synthetic.weekday() >= 5:
            previous_synthetic -= timedelta(days=1)
        session = ReplayProductionPaperSession(
            source_as_of=self._source_sessions[current_index],
            target_as_of=previous_synthetic,
            journal_path=self._sandbox.journal_path,
            scheduler_config=self._config,
            risk_path=self._config.risk_path,
            playbook_path=self._config.playbook_path,
            prices_path=self._config.prices_path,
            provenance_path=self._config.provenance_path,
            frame_cache=self._frame_cache,
        )
        ist = ZoneInfo("Asia/Kolkata")
        entry_at = datetime(
            synthetic.year, synthetic.month, synthetic.day, 9, 21, tzinfo=ist
        )
        journal = OperationalJournal(self._sandbox.journal_path)
        publish_replay_ingestion(
            journal=journal,
            prices_path=self._config.prices_path,
            source_session=self._source_sessions[current_index],
            target_session=previous_synthetic,
            occurred_at=entry_at.replace(hour=8, minute=20),
            eligible_symbols=self._eligibility[
                self._source_sessions[current_index]
            ][0],
            failed_symbols=self._eligibility[
                self._source_sessions[current_index]
            ][1],
        )
        publish_replay_surveillance(
            journal=journal,
            config=self._config,
            symbols=tuple(
                path.stem for path in self._config.prices_path.glob("*.parquet")
            ),
            entry_at=entry_at,
        )
        before = len(journal.read_all())
        app = GovernedSchedulerApplication(
            journal=journal,
            config=self._config,
            entry_session=session,
            eod_session=session.eod,
            manages_legacy_positions=False,
            journal_path=self._sandbox.journal_path,
        )
        try:
            entry = app.run_once(entry_at).to_dict()
            session.bind(source_as_of=source_session, target_as_of=synthetic)
            eod_at = datetime(
                synthetic.year, synthetic.month, synthetic.day,
                18, 31, tzinfo=ist,
            )
            eod = app.run_once(eod_at).to_dict()
            events = journal.read_all()[before:]
            return _project_session_result(
                session=source_session,
                events=events,
                entry=entry,
                eod=eod,
                entry_kind=SchedulerTaskKind.ENTRY_SESSION.value,
                eod_kind=SchedulerTaskKind.END_OF_DAY_SESSION.value,
                journal=journal,
            )
        finally:
            self._index += 1


def _project_session_result(
    *, session, events, entry, eod, entry_kind, eod_kind, journal
):
    roles = tuple(sorted({
        str(event.payload.get("role"))
        for event in events if event.event_type == "DeskRoleCompleted"
    }))
    levels = tuple(sorted({
        str(event.payload.get("fact", {}).get("verdict", {}).get("level"))
        for event in events
        if event.event_type == "TradeCommitteeVerdictProduced"
    }))
    commands = tuple(
        str(event.payload.get("command", {}).get("kind"))
        for event in events if event.event_type == "PaperGatewayCommandExecuted"
    )
    task_items = tuple(entry.get("task_results", ())) + tuple(
        eod.get("task_results", ())
    )
    required = {entry_kind, eod_kind}
    task_states = {
        str(item.get("task", {}).get("kind")): str(
            item.get("outcome", {}).get("state")
        )
        for item in task_items
        if item.get("task", {}).get("kind") in required
    }
    blockers = tuple(sorted(
        f"{kind}:{task_states.get(kind, 'MISSING')}:"
        + ",".join(
            str(reason)
            for item in task_items
            if item.get("task", {}).get("kind") == kind
            for reason in item.get("outcome", {}).get("reason_codes", ())
        )
        + ":"
        + "|".join(
            str(item.get("outcome", {}).get("detail", ""))
            for item in task_items
            if item.get("task", {}).get("kind") == kind
        )
        for kind in required
        if task_states.get(kind) != "COMPLETED"
    ))
    all_events = journal.read_all()
    episode_ids = {
        event.stream_id.removeprefix("episode:")
        for event in all_events
        if event.event_type == "EpisodeStarted"
    }
    from sensei.learning.episodes import EpisodeStatus, TradeEpisodeJournal
    episodes = TradeEpisodeJournal(journal)
    states = tuple(episodes.get(episode_id) for episode_id in episode_ids)
    learned_ids = {
        event.correlation_id for event in all_events
        if event.event_type == "LearningObservationRecorded"
    }
    coherent_agent = _has_coherent_agent_cycle(all_events)
    coherent_lifecycle = bool(_coherent_learned_episode_ids(all_events))
    return ReplaySessionResult(
        session=session,
        completed=not blockers,
        role_names=roles,
        committee_levels=levels,
        gateway_commands=commands,
        open_positions=sum(
            state.status is EpisodeStatus.OPEN for state in states
        ),
        closed_episodes=sum(
            state.status is EpisodeStatus.CLOSED for state in states
        ),
        learned_episodes=len(learned_ids),
        blockers=blockers,
        coherent_agent_cycle=coherent_agent,
        coherent_trade_lifecycle=coherent_lifecycle,
    )


def _has_coherent_agent_cycle(events) -> bool:
    required_roles = {
        "orchestrator", "historian", "reporter", "crowd-reader", "analyst",
        "committee", "trader", "coach", "secretary",
    }
    by_id = {event.event_id: event for event in events}
    verdicts: dict[str, set[str]] = {}
    for event in events:
        if event.event_type == "TradeCommitteeVerdictProduced":
            verdicts.setdefault(str(event.correlation_id), set()).add(str(
                event.payload.get("fact", {}).get("verdict", {}).get("level")
            ))
    for terminal in events:
        if event_type := getattr(terminal, "event_type", None):
            if event_type != "DeskCycleCompleted":
                continue
        role_events = [
            by_id.get(str(event_id))
            for event_id in terminal.payload.get("role_event_ids", ())
        ]
        roles = {
            str(event.payload.get("role"))
            for event in role_events
            if event is not None and event.event_type == "DeskRoleCompleted"
        }
        thesis_id = str(terminal.payload.get("thesis_id", ""))
        if roles == required_roles and verdicts.get(thesis_id) == {
            "L1", "L2", "L3", "L4"
        }:
            return True
    return False


def _coherent_learned_episode_ids(events) -> tuple[str, ...]:
    required = (
        "EpisodeStarted", "ApprovalRecorded", "IntentAccepted",
        "OrderSubmitted", "EntryFillRecorded", "ProtectionVerified",
        "ExitFillRecorded", "EpisodeClosed", "CostsReconciled",
        "OutcomeAttributed", "ReviewRecorded",
    )
    learned = {
        str(event.correlation_id)
        for event in events
        if event.event_type == "LearningObservationRecorded"
    }
    qualifying = []
    for stream_id in {
        event.stream_id for event in events
        if event.stream_id.startswith("episode:")
    }:
        episode = [event for event in events if event.stream_id == stream_id]
        positions = {
            event_type: next(
                (index for index, event in enumerate(episode)
                 if event.event_type == event_type),
                None,
            )
            for event_type in required
        }
        episode_id = stream_id.removeprefix("episode:")
        indexes = tuple(positions[event_type] for event_type in required)
        if (
            episode_id in learned
            and all(index is not None for index in indexes)
            and tuple(indexes) == tuple(sorted(indexes))
        ):
            qualifying.append(episode_id)
    return tuple(sorted(qualifying))


def _future_weekdays(after: date, count: int) -> tuple[date, ...]:
    result = []
    candidate = after
    while len(result) < count:
        candidate += timedelta(days=1)
        if candidate.weekday() < 5:
            result.append(candidate)
    return tuple(result)


def complete_market_sessions(
    *,
    prices_path: Path,
    required_sessions: int,
    minimum_completeness: float = 0.99,
) -> tuple[date, ...]:
    """Select recent sessions meeting a preregistered universe coverage floor."""

    import pandas as pd
    from collections import Counter

    if required_sessions <= 0:
        raise ValueError("required_sessions must be positive")
    if not 0 < minimum_completeness <= 1:
        raise ValueError("minimum_completeness must be in (0, 1]")
    paths = tuple(sorted(Path(prices_path).glob("*.parquet")))
    if not paths:
        raise ValueError("price universe is empty")
    counts: Counter[date] = Counter()
    for path in paths:
        frame = pd.read_parquet(path, columns=["close"])
        counts.update(set(pd.to_datetime(frame.index).date))
    eligible = tuple(sorted(
        session for session, count in counts.items()
        if count / len(paths) >= minimum_completeness
    ))
    if len(eligible) < required_sessions:
        raise ValueError(
            f"only {len(eligible)} sessions meet "
            f"{minimum_completeness:.3f} completeness; "
            f"{required_sessions} required"
        )
    return eligible[-required_sessions:]


def _eligibility_by_session(
    prices_path: Path, sessions: Sequence[date]
) -> dict[date, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Scan parquet indexes once for the replay's exact session universe."""

    import pandas as pd

    requested = set(sessions)
    available = {session: [] for session in sessions}
    paths = tuple(sorted(Path(prices_path).glob("*.parquet")))
    all_symbols = {path.stem for path in paths}
    for path in paths:
        frame = pd.read_parquet(path, columns=["close"])
        for session in requested & set(pd.to_datetime(frame.index).date):
            available[session].append(path.stem)
    return {
        session: (
            tuple(sorted(symbols)),
            tuple(sorted(all_symbols - set(symbols))),
        )
        for session, symbols in available.items()
    }


def production_artifact_fingerprints(
    *, config_path: Path, journal_path: Path
) -> dict[str, str]:
    """Fingerprint every production input a replay composition can observe."""

    config = SchedulerApplicationConfig.from_json(config_path)
    files = (
        Path(journal_path),
        Path(config_path),
        config.surveillance_path,
        config.legacy_positions_path,
        config.playbook_path,
        config.risk_path,
        config.runtime_secrets_path,
        Path("data/earnings_cache.json"),
        Path("data/news-risk.json"),
        Path("data/corporate-metrics.json"),
    )
    result = {
        str(path): (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file() else "missing"
        )
        for path in files
    }
    for root in (config.prices_path, config.provenance_path):
        digest = hashlib.sha256()
        if root.is_dir():
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                digest.update(str(item.relative_to(root)).encode())
                digest.update(item.read_bytes())
        result[str(root)] = digest.hexdigest()
    return result


__all__ = [
    "ReplayArtifactSandbox",
    "preregister_replay_plans",
    "publish_replay_surveillance",
    "ProductionHistoricalDeskReplay",
    "ReplayProductionPaperSession",
    "complete_market_sessions",
    "production_artifact_fingerprints",
]
