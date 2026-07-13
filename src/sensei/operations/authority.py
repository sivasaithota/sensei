"""Small cryptographic primitive for independently trusted local facts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

_ISSUER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_SIGNATURE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
_MINIMUM_SECRET_BYTES = 32


@dataclass(frozen=True)
class HmacFactSigner:
    """Sign one domain fact without exposing the key in logs or repr output."""

    issuer_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _validate_issuer(self.issuer_id)
        _validate_secret(self.secret)

    def sign(self, fact_type: str, fact: Mapping[str, object]) -> str:
        material = _material(self.issuer_id, fact_type, fact)
        digest = hmac.new(self.secret, material, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"


class HmacFactVerifier:
    """Verify facts against independently configured issuer credentials."""

    def __init__(self, trusted_secrets: Mapping[str, bytes]) -> None:
        if not trusted_secrets:
            raise ValueError("at least one trusted fact issuer is required")
        normalized: dict[str, bytes] = {}
        for issuer_id, secret in trusted_secrets.items():
            _validate_issuer(issuer_id)
            _validate_secret(secret)
            normalized[issuer_id] = bytes(secret)
        self._trusted_secrets = normalized

    @property
    def trusted_issuer_ids(self) -> frozenset[str]:
        return frozenset(self._trusted_secrets)

    def verify(
        self,
        *,
        issuer_id: str,
        fact_type: str,
        fact: Mapping[str, object],
        signature: str,
    ) -> bool:
        secret = self._trusted_secrets.get(issuer_id)
        if secret is None or _SIGNATURE.fullmatch(signature) is None:
            return False
        try:
            material = _material(issuer_id, fact_type, fact)
        except (TypeError, ValueError):
            return False
        expected = hmac.new(secret, material, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.removeprefix("hmac-sha256:"), expected)


def _material(
    issuer_id: str,
    fact_type: str,
    fact: Mapping[str, object],
) -> bytes:
    _validate_issuer(issuer_id)
    if not isinstance(fact_type, str) or not fact_type.strip():
        raise ValueError("fact_type must not be blank")
    if not isinstance(fact, Mapping):
        raise TypeError("fact must be a mapping")
    canonical = json.dumps(
        {
            "schema": "sensei-signed-fact-v1",
            "issuer_id": issuer_id,
            "fact_type": fact_type,
            "fact": fact,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return canonical.encode("utf-8")


def _validate_issuer(issuer_id: str) -> None:
    if not isinstance(issuer_id, str) or _ISSUER.fullmatch(issuer_id) is None:
        raise ValueError("issuer_id is invalid")


def _validate_secret(secret: bytes) -> None:
    if not isinstance(secret, bytes) or len(secret) < _MINIMUM_SECRET_BYTES:
        raise ValueError("fact authority secrets must be at least 32 bytes")
