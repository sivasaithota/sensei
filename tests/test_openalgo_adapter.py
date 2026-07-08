import json

import httpx
import pytest

from sensei.execution.openalgo import ExecConfig, OpenAlgoError, OpenAlgoExecutor


def mock_executor(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url="http://127.0.0.1:5000", transport=transport)
    cfg = ExecConfig(mode="sandbox", api_key="test-key", strategy_tag="sensei")
    return OpenAlgoExecutor(cfg, client=client)


def test_limit_buy_payload_and_orderid():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "success", "orderid": "2507080001"})

    ex = mock_executor(handler)
    oid = ex.place_limit_buy("LODHA", 9, 1057.456)
    assert oid == "2507080001"
    assert seen["path"] == "/api/v1/placeorder"
    b = seen["body"]
    assert b["apikey"] == "test-key" and b["strategy"] == "sensei"
    assert b["pricetype"] == "LIMIT" and b["product"] == "CNC"
    assert b["price"] == "1057.46" and b["quantity"] == "9"


def test_oco_bracket_payload():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "success", "gttorderid": "G-77"})

    ex = mock_executor(handler)
    gtt = ex.place_bracket("LODHA", 9, stop_trigger=1004.15, target_trigger=1183.84)
    assert gtt == "G-77"
    b = seen["body"]
    assert b["trigger_type"] == "OCO" and b["action"] == "SELL"
    assert b["triggerprice_sl"] == 1004.15 and b["triggerprice_tg"] == 1183.84
    assert b["product"] == "CNC"


def test_broker_error_raises():
    def handler(request):
        return httpx.Response(200, json={"status": "error", "message": "RMS: insufficient funds"})

    ex = mock_executor(handler)
    with pytest.raises(OpenAlgoError, match="placeorder"):
        ex.place_limit_buy("LODHA", 9, 1057.0)


def test_http_failure_raises():
    def handler(request):
        return httpx.Response(500)

    ex = mock_executor(handler)
    with pytest.raises(httpx.HTTPStatusError):
        ex.place_limit_buy("LODHA", 9, 1057.0)


def test_default_config_is_off(tmp_path, monkeypatch):
    import sensei.execution.openalgo as oa
    monkeypatch.setattr(oa, "CONFIG_FILE", tmp_path / "missing.yaml")
    assert ExecConfig.load().mode == "off"
