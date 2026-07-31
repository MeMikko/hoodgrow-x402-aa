import pytest
import responses

from hoodgrow_x402_aa import DEFAULT_BASE_RPC_URL, get_usdc_balance

ADDRESS = "0x1234567890123456789012345678901234567890"


@responses.activate
def test_get_usdc_balance_decodes_6_decimal_result():
    # 12500000 raw units == 12.5 USDC (6 decimals) == 0xbebc20.
    responses.add(
        responses.POST,
        DEFAULT_BASE_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x" + "0" * 58 + "bebc20",
        },
        status=200,
    )

    balance = get_usdc_balance(ADDRESS)
    assert balance == 12.5


@responses.activate
def test_get_usdc_balance_calls_balanceOf_with_the_padded_address():
    responses.add(
        responses.POST,
        DEFAULT_BASE_RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 64},
        status=200,
    )

    get_usdc_balance(ADDRESS)

    body = responses.calls[0].request.body
    import json

    payload = json.loads(body)
    assert payload["method"] == "eth_call"
    data = payload["params"][0]["data"]
    assert data.startswith("0x70a08231")  # balanceOf(address) selector
    assert data.endswith(ADDRESS[2:].lower())


@responses.activate
def test_get_usdc_balance_raises_on_rpc_error():
    responses.add(
        responses.POST,
        DEFAULT_BASE_RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}},
        status=200,
    )

    with pytest.raises(RuntimeError, match="RPC error"):
        get_usdc_balance(ADDRESS)
