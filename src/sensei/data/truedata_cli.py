"""Private command-line control surface for the TrueData trial harness."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from sensei.data.truedata import (
    Capability,
    STAMP,
    PrivateArtifactStore,
    TrialPlan,
    TrueDataClient,
    TrueDataConfig,
    TrueDataError,
    download_plan,
    expand_detail_plan,
    expand_plan_from_masters,
    probe_entitlements,
    record_corporate_announcements,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _symbols(path: str | None) -> tuple[str, ...]:
    if path is None:
        return ()
    source = Path(path)
    if source.stat().st_size > 5_000_000:
        raise TrueDataError("symbols file exceeds the safety limit")
    values = {
        line.strip().upper()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if len(values) > 20_000:
        raise TrueDataError("symbols file exceeds the instrument safety limit")
    return tuple(sorted(values))


def _validate_trial_dates(as_of: date, eod_start: date, corporate_start: date) -> None:
    if eod_start > as_of or corporate_start > as_of:
        raise TrueDataError("trial start dates must not be after --as-of")
    if (as_of - eod_start).days > 730:
        raise TrueDataError("trial EOD window must not exceed 730 days")
    if (as_of - corporate_start).days > 92:
        raise TrueDataError("trial corporate window must not exceed 92 days")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensei-truedata",
        description="Quarantined private TrueData trial ingestion",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    today = date.today()
    def dates(command: argparse.ArgumentParser) -> None:
        command.add_argument("--as-of", type=_date, default=today)
        command.add_argument(
            "--eod-start", type=_date, default=today - timedelta(days=730)
        )
        command.add_argument(
            "--corporate-start", type=_date, default=today - timedelta(days=92)
        )
        command.add_argument(
            "--segments", nargs="+", choices=("eq", "in"), default=("eq", "in")
        )
        command.add_argument(
            "--capabilities",
            nargs="+",
            choices=tuple(capability.value for capability in Capability),
            default=(Capability.CORPORATE.value,),
            help="default is the confirmed corporate/fundamental trial scope",
        )

    plan = sub.add_parser("plan", help="create a credential-free trial plan")
    dates(plan)
    plan.add_argument("--symbols", help="optional newline-delimited NSE symbols")
    plan.add_argument("--output", type=Path, required=True)

    download = sub.add_parser("download", help="run or resume a saved plan")
    download.add_argument("--plan", type=Path, required=True)
    download.add_argument("--store", type=Path, default=None)
    download.add_argument("--stop-on-error", action="store_true")

    audit = sub.add_parser("audit", help="verify local artifacts without network")
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--store", type=Path, required=True)

    expand = sub.add_parser(
        "expand", help="expand a bootstrap plan from verified downloaded masters"
    )
    dates(expand)
    expand.add_argument("--bootstrap-plan", type=Path, required=True)
    expand.add_argument("--store", type=Path, required=True)
    expand.add_argument("--output", type=Path, required=True)

    run = sub.add_parser(
        "run", help="download masters, discover symbols, then run/resume the full trial"
    )
    dates(run)
    run.add_argument("--store", type=Path, default=None)
    run.add_argument("--plan-output", type=Path, required=True)
    run.add_argument("--stop-on-error", action="store_true")

    sub.add_parser("probe", help="test authentication only; does not download data")
    entitlements = sub.add_parser(
        "entitlements", help="probe bounded corporate/history/master access without storage"
    )
    entitlements.add_argument("--as-of", type=_date, default=today)
    entitlements.add_argument(
        "--required",
        nargs="+",
        choices=tuple(capability.value for capability in Capability),
        default=(Capability.CORPORATE.value,),
    )
    announcements = sub.add_parser(
        "record-announcements",
        help="checkpoint the private corporate WebSocket feed with reconnects",
    )
    announcements.add_argument("--store", type=Path, default=None)
    announcements.add_argument(
        "--duration-seconds", type=float, default=86_400.0
    )
    return parser


def _print(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            _validate_trial_dates(args.as_of, args.eod_start, args.corporate_start)
            plan = TrialPlan.for_trial(
                as_of=args.as_of,
                eod_start=args.eod_start,
                corporate_start=args.corporate_start,
                segments=tuple(args.segments),
                symbols=_symbols(args.symbols),
                capabilities=tuple(args.capabilities),
            )
            plan.write(args.output)
            services: dict[str, int] = {}
            for request in plan.requests:
                services[request.service.value] = services.get(request.service.value, 0) + 1
            _print(
                {
                    "status": "PLANNED",
                    "stamp": STAMP,
                    "admissible": False,
                    "plan_id": plan.plan_id,
                    "path": str(args.output),
                    "requests": len(plan.requests),
                    "requests_by_service": services,
                }
            )
            return 0

        if args.command == "audit":
            plan = TrialPlan.read(args.plan)
            result = PrivateArtifactStore(args.store).audit(plan)
            _print(
                {
                    "status": (
                        "INCOMPLETE"
                        if result.missing
                        else "ERROR_RESPONSES"
                        if result.error
                        else "QUALITY_ERRORS"
                        if result.eod_invalid or result.eod_duplicate_dates
                        else "COVERAGE_GAPS"
                        if result.no_data or result.eod_range_gaps
                        else "VERIFIED_DATA"
                    ),
                    "stamp": STAMP,
                    "admissible": False,
                    "plan_id": plan.plan_id,
                    "total": result.total,
                    "verified": result.verified,
                    "missing": result.missing,
                    "data": result.data,
                    "no_data": result.no_data,
                    "error": result.error,
                    "eod_requests": result.eod_requests,
                    "eod_with_data": result.eod_with_data,
                    "eod_rows": result.eod_rows,
                    "eod_earliest": result.eod_earliest,
                    "eod_latest": result.eod_latest,
                    "eod_duplicate_dates": result.eod_duplicate_dates,
                    "eod_invalid": result.eod_invalid,
                    "eod_range_gaps": result.eod_range_gaps,
                }
            )
            return (
                0
                if not (
                    result.missing
                    or result.error
                    or result.no_data
                    or result.eod_invalid
                    or result.eod_duplicate_dates
                    or result.eod_range_gaps
                )
                else 1
            )

        if args.command == "expand":
            _validate_trial_dates(args.as_of, args.eod_start, args.corporate_start)
            bootstrap = TrialPlan.read(args.bootstrap_plan)
            plan = expand_plan_from_masters(
                bootstrap,
                store=PrivateArtifactStore(args.store),
                as_of=args.as_of,
                eod_start=args.eod_start,
                corporate_start=args.corporate_start,
                segments=tuple(args.segments),
                capabilities=tuple(args.capabilities),
            )
            plan.write(args.output)
            _print(
                {
                    "status": "EXPANDED",
                    "stamp": STAMP,
                    "admissible": False,
                    "plan_id": plan.plan_id,
                    "path": str(args.output),
                    "requests": len(plan.requests),
                    "symbols": len(
                        {
                            request.params["symbol"]
                            for request in plan.requests
                            if request.endpoint == "getbars"
                        }
                    ),
                }
            )
            return 0

        config = TrueDataConfig.from_environment()
        if getattr(args, "store", None) is not None:
            config = TrueDataConfig(config.username, config.password, args.store)
        if args.command == "record-announcements":
            result = record_corporate_announcements(
                config,
                duration_seconds=args.duration_seconds,
            )
            _print(
                {
                    "status": (
                        "RECORDING_COMPLETE"
                        if result.connected and not result.authorization_failed
                        else "RECORDING_FAILED"
                    ),
                    "stamp": STAMP,
                    "admissible": False,
                    "store": str(config.store),
                    "received": result.received,
                    "stored": result.stored,
                    "duplicates": result.duplicates,
                    "ignored": result.ignored,
                    "rejected": result.rejected,
                    "reconnects": result.reconnects,
                    "connected": result.connected,
                    "authorization_failed": result.authorization_failed,
                }
            )
            return 0 if result.connected and not result.authorization_failed else 2
        client = TrueDataClient(config)
        if args.command == "probe":
            client.authenticate()
            _print(
                {
                    "status": "AUTHENTICATED",
                    "stamp": STAMP,
                    "admissible": False,
                    "store": str(config.store),
                }
            )
            return 0

        if args.command == "entitlements":
            required = {Capability(value) for value in args.required}
            results = probe_entitlements(
                client,
                as_of=args.as_of,
                capabilities=tuple(required),
            )
            _print(
                {
                    "status": "PROBED",
                    "stamp": STAMP,
                    "admissible": False,
                    "entitlements": {
                        result.capability.value: {
                            "accessible": result.accessible,
                            "response_class": result.response_class,
                        }
                        for result in results
                    },
                }
            )
            return (
                0
                if all(
                    result.accessible
                    for result in results
                    if result.capability in required
                )
                else 1
            )

        if args.command == "run":
            _validate_trial_dates(args.as_of, args.eod_start, args.corporate_start)
            capabilities = tuple(Capability(value) for value in args.capabilities)
            if Capability.HISTORY in capabilities and Capability.MASTER not in capabilities:
                raise TrueDataError("history runs require the master capability for symbol discovery")
            probe_results = probe_entitlements(
                client, as_of=args.as_of, capabilities=capabilities
            )
            inaccessible = sorted(
                result.capability.value
                for result in probe_results
                if result.capability in capabilities and not result.accessible
            )
            if inaccessible:
                _print(
                    {
                        "status": "ENTITLEMENT_DENIED",
                        "stamp": STAMP,
                        "admissible": False,
                        "capabilities": inaccessible,
                    }
                )
                return 2
            bootstrap = TrialPlan.for_trial(
                as_of=args.as_of,
                eod_start=args.eod_start,
                corporate_start=args.corporate_start,
                segments=tuple(args.segments),
                capabilities=capabilities,
            )
            if Capability.MASTER in capabilities:
                discovery = tuple(
                    request
                    for request in bootstrap.requests
                    if request.endpoint in {"getAllSymbols", "getsymbolchangehistory"}
                )
                master_result = download_plan(
                    TrialPlan(f"{bootstrap.plan_id}-discovery", discovery),
                    client=client,
                    store=PrivateArtifactStore(config.store),
                    stop_on_error=True,
                )
                if master_result.failed:
                    _print(
                        {
                            "status": "DISCOVERY_FAILED",
                            "stamp": STAMP,
                            "admissible": False,
                            "failed": master_result.failed,
                            "failures": dict(master_result.failures),
                        }
                    )
                    return 2
                plan = expand_plan_from_masters(
                    bootstrap,
                    store=PrivateArtifactStore(config.store),
                    as_of=args.as_of,
                    eod_start=args.eod_start,
                    corporate_start=args.corporate_start,
                    segments=tuple(args.segments),
                    capabilities=capabilities,
                )
            else:
                plan = bootstrap
        else:
            plan = TrialPlan.read(args.plan)
        result = download_plan(
            plan,
            client=client,
            store=PrivateArtifactStore(config.store),
            stop_on_error=args.stop_on_error,
        )
        if args.command == "run" and result.failed == 0:
            plan = expand_detail_plan(
                plan, store=PrivateArtifactStore(config.store)
            )
            plan.write(args.plan_output)
            result = download_plan(
                plan,
                client=client,
                store=PrivateArtifactStore(config.store),
                stop_on_error=args.stop_on_error,
            )
        _print(
            {
                "status": "DOWNLOAD_COMPLETE" if result.failed == 0 else "PARTIAL",
                "stamp": STAMP,
                "admissible": False,
                "plan_id": plan.plan_id,
                "store": str(config.store),
                "total": result.total,
                "stored": result.stored,
                "skipped": result.skipped,
                "failed": result.failed,
                "failures": dict(result.failures),
            }
        )
        return 0 if result.failed == 0 else 2
    except (OSError, UnicodeError, TrueDataError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
