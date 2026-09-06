"""Credential-safe operator CLI for quarantined AccelPix EOD capture."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from sensei.data.accelpix import (
    ACCELPIX_STAMP,
    AccelPixClient,
    AccelPixConfig,
    AccelPixError,
    AccelPixPlan,
    AccelPixRequest,
    AccelPixStore,
    download_plan,
    normalize_eod_plan,
    symbols_from_master,
    validate_eod_payload,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensei-accelpix",
        description="Private, quarantined AccelPix EOD ingestion",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="test authentication without storing vendor data")
    probe_eod = sub.add_parser(
        "probe-eod", help="validate one bounded EOD response without storing it"
    )
    probe_eod.add_argument("--ticker", required=True)
    probe_eod.add_argument("--start", type=_date, required=True)
    probe_eod.add_argument("--end", type=_date, required=True)
    probe_eod.add_argument(
        "--required-session", type=_date, action="append", default=[],
        help="require this exchange session in the response; repeat for multiple dates",
    )

    master = sub.add_parser("capture-master", help="capture and hash the symbol master")
    master.add_argument("--store", type=Path, default=None)

    plan = sub.add_parser("plan", help="create a credential-free exact EOD plan")
    plan.add_argument("--symbols", type=Path, required=True)
    plan.add_argument(
        "--master-store",
        type=Path,
        required=True,
        help="private store containing the hash-verified AccelPix master",
    )
    plan.add_argument("--start", type=_date, required=True)
    plan.add_argument("--end", type=_date, required=True)
    plan.add_argument("--maximum-symbols", type=int, default=250)
    plan.add_argument("--output", type=Path, required=True)

    download = sub.add_parser("download", help="run or resume an exact EOD plan")
    download.add_argument("--plan", type=Path, required=True)
    download.add_argument("--store", type=Path, default=None)
    download.add_argument(
        "--retry-terminal",
        action="store_true",
        help="explicitly retry previously checkpointed 4xx failures",
    )

    audit = sub.add_parser("audit", help="verify captured bytes without network access")
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--store", type=Path, required=True)

    normalize = sub.add_parser("normalize", help="write validated private EOD Parquet")
    normalize.add_argument("--plan", type=Path, required=True)
    normalize.add_argument("--store", type=Path, required=True)
    normalize.add_argument("--output", type=Path, required=True)
    return parser


def _load_symbols(path: Path, *, maximum: int) -> tuple[str, ...]:
    if maximum <= 0 or maximum > 20_000:
        raise AccelPixError("maximum symbol count is outside the safety limit")
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise AccelPixError("symbols file is missing or exceeds the safety limit")
    text = path.read_text(encoding="utf-8-sig")
    symbols: list[str]
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(text.splitlines())
        if not reader.fieldnames or "symbol" not in reader.fieldnames:
            raise AccelPixError("CSV symbols file must contain a symbol column")
        symbols = [str(row.get("symbol") or "") for row in reader]
    else:
        symbols = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    normalized = tuple(sorted({value.strip().upper() for value in symbols if value.strip()}))
    if not normalized:
        raise AccelPixError("symbols file contains no instruments")
    if len(normalized) > maximum:
        raise AccelPixError(
            f"symbols file contains {len(normalized)} instruments; limit is {maximum}"
        )
    return normalized


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _config(store: Path | None = None) -> AccelPixConfig:
    config = AccelPixConfig.from_environment()
    if store is None:
        return config
    return AccelPixConfig(
        api_token=config.api_token,
        store=store,
        request_interval_seconds=config.request_interval_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            symbols = _load_symbols(args.symbols, maximum=args.maximum_symbols)
            master_symbols = frozenset(symbols_from_master(AccelPixStore(args.master_store)))
            unsupported = sorted(set(symbols) - master_symbols)
            if unsupported:
                raise AccelPixError(
                    f"{len(unsupported)} requested symbols are absent from the verified equity master"
                )
            plan = AccelPixPlan.for_eod(
                symbols=symbols,
                start=args.start,
                end=args.end,
            )
            plan.write(args.output)
            _print(
                {
                    "status": "PLANNED",
                    "stamp": ACCELPIX_STAMP,
                    "admissible": False,
                    "plan_id": plan.plan_id,
                    "requests": len(plan.requests),
                    "path": str(args.output),
                }
            )
            return 0

        if args.command == "probe":
            config = _config()
            AccelPixClient(config).fetch(AccelPixRequest.master())
            _print(
                {
                    "status": "AUTHENTICATED",
                    "stamp": ACCELPIX_STAMP,
                    "admissible": False,
                }
            )
            return 0

        if args.command == "probe-eod":
            if args.start > args.end or (args.end - args.start).days > 7:
                raise AccelPixError("EOD probe must be bounded to at most five sessions")
            required = set(args.required_session)
            if any(not args.start <= session <= args.end for session in required):
                raise AccelPixError("required session is outside the probe window")
            request = AccelPixRequest.eod(args.ticker, args.start, args.end)
            payload = AccelPixClient(_config()).fetch(
                request
            )
            rows = validate_eod_payload(request, payload.content)
            if not rows and not required:
                raise AccelPixError("EOD probe returned no sessions")
            if len(rows) > 5:
                raise AccelPixError("EOD probe returned more than five sessions")
            observed = {row["date"].date() for row in rows}
            missing = sorted(required - observed)
            _print(
                {
                    "status": ("REQUIRED_SESSIONS_MISSING" if missing else
                               "REQUIRED_SESSIONS_PRESENT" if required else "EOD_SCHEMA_VALID"),
                    "stamp": ACCELPIX_STAMP,
                    "admissible": False,
                    "rows": len(rows),
                    "observed_sessions": [str(session) for session in sorted(observed)],
                    "required_sessions": [str(session) for session in sorted(required)],
                    "missing_sessions": [str(session) for session in missing],
                    "adjustment_factors_verified": False,
                }
            )
            return 2 if missing else 0

        if args.command == "capture-master":
            config = _config(args.store)
            request = AccelPixRequest.master()
            store = AccelPixStore(config.store)
            if store.verified(request) is None:
                payload = AccelPixClient(config).fetch(request)
                store.put(
                    request,
                    content=payload.content,
                    content_type=payload.content_type,
                    retrieved_at=payload.retrieved_at,
                )
            _print(
                {
                    "status": "VERIFIED",
                    "stamp": ACCELPIX_STAMP,
                    "admissible": False,
                    "expected": 1,
                    "verified": 1,
                    "missing": 0,
                }
            )
            return 0

        plan = AccelPixPlan.read(args.plan)
        if args.command == "download":
            config = _config(args.store)
            result = download_plan(
                plan,
                client=AccelPixClient(config),
                store=AccelPixStore(config.store),
                retry_terminal=args.retry_terminal,
            )
            status = "VERIFIED" if result.missing == 0 else "INCOMPLETE"
        elif args.command == "audit":
            result = AccelPixStore(args.store).audit(plan)
            status = "VERIFIED" if result.missing == 0 else "INCOMPLETE"
        elif args.command == "normalize":
            counts = normalize_eod_plan(
                plan,
                store=AccelPixStore(args.store),
                output=args.output,
            )
            _print(
                {
                    "status": "NORMALIZED",
                    "stamp": ACCELPIX_STAMP,
                    "admissible": False,
                    **counts,
                    "path": str(args.output),
                }
            )
            return 0
        else:  # pragma: no cover - argparse enforces the command set
            raise AccelPixError("unknown command")

        _print(
            {
                "status": status,
                "stamp": ACCELPIX_STAMP,
                "admissible": False,
                "expected": result.expected,
                "verified": result.verified,
                "missing": result.missing,
                "failures": result.failures,
            }
        )
        return 0 if result.missing == 0 else 2
    except (AccelPixError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error": str(exc),
                    "admissible": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
