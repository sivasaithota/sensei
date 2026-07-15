"""Locally held trust material and verified runtime observations.

Secrets are operational state, never repository configuration.  Surveillance
is an observation signed by one of those independently configured producers;
an issuer label inside the observation cannot establish trust by itself.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import stat
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from io import StringIO

import httpx


class RuntimeTrustError(RuntimeError):
    """Runtime authority material or a signed observation is not trustworthy."""


class RuntimeSecretStore:
    """Create and load a complete, owner-readable-only HMAC trust store."""

    REQUIRED_ISSUERS = (
        "historian",
        "paper-admission",
        "desk-supervisor",
        "risk-officer",
        "devils-advocate",
        "compliance",
        "orchestrator",
        "market-data",
        "paper-gateway",
        "reconciliation",
        "operations-monitor",
        "paper-account",
        "market-surveillance",
    )

    @classmethod
    def bootstrap(cls, path: Path) -> dict[str, bytes]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeTrustError(f"runtime secret store already exists: {target}")
        material = {issuer: os.urandom(32) for issuer in cls.REQUIRED_ISSUERS}
        payload = {
            "schema_version": "1.0",
            "secrets": {
                issuer: base64.b64encode(secret).decode("ascii")
                for issuer, secret in material.items()
            },
        }
        try:
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise RuntimeTrustError(
                f"runtime secret store already exists: {target}"
            ) from exc
        with os.fdopen(descriptor, mode="w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        return material

    @classmethod
    def load(cls, path: Path) -> dict[str, bytes]:
        target = Path(path)
        try:
            metadata = target.lstat()
        except FileNotFoundError as exc:
            raise RuntimeTrustError(f"runtime secret store is missing: {target}") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
        ):
            raise RuntimeTrustError(
                "runtime secret store must be a regular owner file"
            )
        mode = stat.S_IMODE(metadata.st_mode)
        if mode != 0o600:
            raise RuntimeTrustError("runtime secret store must have mode 0600")
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            encoded = raw["secrets"]
            if raw["schema_version"] != "1.0" or not isinstance(encoded, dict):
                raise ValueError
            if set(encoded) != set(cls.REQUIRED_ISSUERS):
                raise ValueError
            material = {
                issuer: base64.b64decode(encoded[issuer], validate=True)
                for issuer in cls.REQUIRED_ISSUERS
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeTrustError("runtime secret store is invalid or incomplete") from exc
        if any(len(secret) < 32 for secret in material.values()):
            raise RuntimeTrustError("runtime secret material is too short")
        return material


class VerifiedSurveillanceSource:
    """Resolve exchange surveillance stage from a fresh signed daily snapshot."""

    def __init__(
        self,
        path: Path,
        *,
        issuer_id: str,
        secret: bytes,
        maximum_age: timedelta,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        self._path = Path(path)
        self._issuer_id = issuer_id
        self._secret = secret
        self._maximum_age = maximum_age
        self._clock = clock

    @staticmethod
    def publish(
        path: Path,
        *,
        stages: Mapping[str, int],
        session: date,
        observed_at: datetime,
        issuer_id: str,
        secret: bytes,
    ) -> None:
        _aware(observed_at)
        normalized = _stages(stages)
        fact = {
            "schema_version": "1.0",
            "issuer_id": issuer_id,
            "session": session.isoformat(),
            "observed_at": observed_at.isoformat(),
            "stages": normalized,
        }
        payload = {**fact, "signature": _sign(fact, secret)}
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def __call__(self, symbol: str, session: date) -> int | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            signature = payload.pop("signature")
            observed_at = datetime.fromisoformat(payload["observed_at"])
            snapshot_session = date.fromisoformat(payload["session"])
            stages = _stages(payload["stages"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if payload.get("schema_version") != "1.0" or payload.get("issuer_id") != self._issuer_id:
            raise RuntimeTrustError("surveillance producer identity is invalid")
        if not hmac.compare_digest(signature, _sign(payload, self._secret)):
            raise RuntimeTrustError("surveillance signature verification failed")
        now = self._clock()
        _aware(now)
        if observed_at > now or now - observed_at > self._maximum_age:
            return None
        if snapshot_session != session:
            return None
        return stages.get(symbol)


class NseSurveillanceRefresher:
    """Fetch NSE's official daily regulatory-indicator file and attest parsing."""

    URL = "https://nsearchives.nseindia.com/content/equities/REG_IND{day}.csv"

    def __init__(
        self,
        *,
        destination: Path,
        issuer_id: str,
        secret: bytes,
        fetch=None,
    ) -> None:
        self._destination = Path(destination)
        self._issuer_id = issuer_id
        self._secret = secret
        self._fetch = fetch or self._fetch_official

    def refresh(self, *, session: date, observed_at: datetime) -> dict[str, int]:
        _aware(observed_at)
        url = self.URL.format(day=session.strftime("%d%m%y"))
        content = self._fetch(url)
        stages = self.parse(content)
        if not stages:
            raise RuntimeTrustError("NSE regulatory indicator contained no active securities")
        VerifiedSurveillanceSource.publish(
            self._destination,
            stages=stages,
            session=session,
            observed_at=observed_at,
            issuer_id=self._issuer_id,
            secret=self._secret,
        )
        return stages

    @staticmethod
    def parse(content: bytes) -> dict[str, int]:
        try:
            text = content.decode("utf-8-sig")
        except (AttributeError, UnicodeDecodeError) as exc:
            raise RuntimeTrustError("NSE regulatory indicator encoding is invalid") from exc
        result: dict[str, int] = {}
        try:
            for row in csv.reader(StringIO(text)):
                if not row or row[0].strip().lower() in {"scripcode", "scrip code"}:
                    continue
                if len(row) < 10 or row[3].strip() != "A":
                    continue
                symbol = row[1].strip()
                raw_stages = (int(row[5]), int(row[6]), int(row[9]))
                active = [stage for stage in raw_stages if stage != 100]
                stage = max(active, default=0)
                if not symbol or stage < 0:
                    raise ValueError
                result[symbol] = max(result.get(symbol, 0), stage)
        except (IndexError, ValueError) as exc:
            raise RuntimeTrustError("NSE regulatory indicator schema is invalid") from exc
        return dict(sorted(result.items()))

    @staticmethod
    def _fetch_official(url: str) -> bytes:
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": "Sensei paper surveillance adapter/1.0"},
                follow_redirects=True,
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeTrustError("official NSE surveillance download failed") from exc
        return response.content


def _stages(values: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(values, Mapping):
        raise ValueError("surveillance stages must be a mapping")
    normalized: dict[str, int] = {}
    for symbol, stage in values.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("surveillance symbol is invalid")
        if isinstance(stage, bool) or not isinstance(stage, int) or stage < 0:
            raise ValueError("surveillance stage is invalid")
        normalized[symbol.strip()] = stage
    return dict(sorted(normalized.items()))


def _sign(fact: Mapping[str, object], secret: bytes) -> str:
    message = json.dumps(fact, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


__all__ = [
    "NseSurveillanceRefresher",
    "RuntimeSecretStore",
    "RuntimeTrustError",
    "VerifiedSurveillanceSource",
]
