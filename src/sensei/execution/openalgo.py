"""OpenAlgo execution adapter — "The Trader"'s hands for P2+ (PRD §4.7).

Talks to a self-hosted OpenAlgo instance (github.com/marketcalls/openalgo)
at http://127.0.0.1:5000/api/v1. OpenAlgo abstracts the broker (Zerodha
per owner decision 2026-07-08); Sensei never imports a broker SDK.

Execution discipline (PRD + owner decisions):
- LIMIT-first entries in CNC, priced inside the approved entry zone.
- Immediately after a confirmed entry fill: an OCO GTT bracket —
  stop-loss + target living AT THE BROKER, surviving local downtime.
- Kill-switch support: cancel all open orders in one call.

This adapter is P2 infrastructure: nothing in the paper loop calls it.  The
current build is intentionally sandbox-only; ``off`` and ``live`` fail before
any network call.  A future live adapter must be introduced through the
governed kernel only after reconciliation and protection readiness evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "execution.yaml"


@dataclass(frozen=True)
class ExecConfig:
    mode: str = "off"                    # off | sandbox | live
    host: str = "http://127.0.0.1:5000"
    api_key: str = ""
    strategy_tag: str = "sensei"         # OpenAlgo tags every order with this

    def __post_init__(self) -> None:
        if self.mode not in {"off", "sandbox", "live"}:
            raise ValueError("execution mode must be off, sandbox, or live")

    @classmethod
    def load(cls) -> "ExecConfig":
        if not CONFIG_FILE.exists():
            return cls()
        raw = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        return cls(**raw)


class OpenAlgoError(RuntimeError):
    pass


class OpenAlgoExecutor:
    def __init__(self, config: ExecConfig | None = None,
                 client: httpx.Client | None = None):
        self.cfg = config or ExecConfig.load()
        self.http = client or httpx.Client(base_url=self.cfg.host, timeout=15)

    def _post(self, endpoint: str, payload: dict) -> dict:
        if self.cfg.mode != "sandbox":
            raise OpenAlgoError(
                "OpenAlgo is sandbox-only in this build; off/live network "
                "execution is disabled"
            )
        body = {"apikey": self.cfg.api_key, "strategy": self.cfg.strategy_tag,
                **payload}
        resp = self.http.post(f"/api/v1/{endpoint}", json=body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise OpenAlgoError(f"{endpoint}: {data}")
        return data

    # ---- entries ----

    def place_limit_buy(self, symbol: str, quantity: int, price: float) -> str:
        """LIMIT-first CNC entry. Returns broker order id."""
        data = self._post("placeorder", {
            "symbol": symbol, "exchange": "NSE", "action": "BUY",
            "pricetype": "LIMIT", "product": "CNC",
            "quantity": str(quantity), "price": str(round(price, 2)),
            "trigger_price": "0", "disclosed_quantity": "0",
        })
        return str(data["orderid"])

    def order_status(self, order_id: str) -> dict:
        return self._post("orderstatus", {"orderid": order_id})

    def modify_limit_price(self, order_id: str, symbol: str, quantity: int,
                           new_price: float) -> None:
        """Reprice an unfilled entry toward the market — only ever called
        with prices inside the approved entry zone."""
        self._post("modifyorder", {
            "orderid": order_id, "symbol": symbol, "exchange": "NSE",
            "action": "BUY", "pricetype": "LIMIT", "product": "CNC",
            "quantity": str(quantity), "price": str(round(new_price, 2)),
            "trigger_price": "0", "disclosed_quantity": "0",
        })

    def cancel_order(self, order_id: str) -> None:
        self._post("cancelorder", {"orderid": order_id})

    # ---- exits: the bracket lives at the broker ----

    def place_bracket(self, symbol: str, quantity: int, *,
                      stop_trigger: float, target_trigger: float) -> str:
        """OCO GTT: stop-loss + target for an existing long CNC position.
        Whichever triggers first fires a SELL; the other auto-cancels.
        Survives local machine downtime (PRD §12). Returns GTT id."""
        data = self._post("placegttorder", {
            "trigger_type": "OCO", "exchange": "NSE", "symbol": symbol,
            "action": "SELL", "product": "CNC", "quantity": quantity,
            "pricetype": "MARKET", "price": 0,
            "triggerprice_sl": round(stop_trigger, 2),
            "triggerprice_tg": round(target_trigger, 2),
            "stoploss": None, "target": None,
        })
        return str(data.get("gttorderid") or data.get("orderid"))

    def cancel_gtt(self, gtt_id: str) -> None:
        self._post("cancelgttorder", {"orderid": gtt_id})

    # ---- portfolio truth from the broker ----

    def positions(self) -> list[dict]:
        return self._post("positionbook", {}).get("data", [])

    def holdings(self) -> list[dict]:
        return self._post("holdings", {}).get("data", [])

    def funds(self) -> dict:
        return self._post("funds", {}).get("data", {})

    # ---- kill-switch ----

    def cancel_all(self) -> dict:
        """Owner kill-switch: cancel every open order under our strategy tag.
        Note: does NOT cancel GTT brackets — those are protective exits and
        must outlive a halt; cancel_gtt is deliberate and per-position."""
        return self._post("cancelallorder", {})
