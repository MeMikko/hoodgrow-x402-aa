"""USDC balance check on Base — a plain JSON-RPC eth_call, not a full
web3.py dependency (this package only ever needs one read-only call)."""

from __future__ import annotations

import requests

DEFAULT_BASE_RPC_URL = "https://mainnet.base.org"
USDC_BASE_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
_BALANCE_OF_SELECTOR = "70a08231"  # balanceOf(address)
_RPC_TIMEOUT_SECONDS = 10


def get_usdc_balance(address: str, rpc_url: str = DEFAULT_BASE_RPC_URL) -> float:
    """USDC balance (human units, e.g. 12.5) held by `address` on Base
    mainnet — use this to decide when your agent's spend wallet needs
    topping up from its main smart wallet.
    """
    padded_address = address.lower().removeprefix("0x").rjust(64, "0")
    data = f"0x{_BALANCE_OF_SELECTOR}{padded_address}"

    res = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": USDC_BASE_ADDRESS, "data": data}, "latest"],
        },
        timeout=_RPC_TIMEOUT_SECONDS,
    )
    res.raise_for_status()
    body = res.json()
    if "error" in body:
        raise RuntimeError(f"RPC error reading USDC balance: {body['error']}")

    raw = int(body["result"], 16)
    return raw / 1_000_000  # USDC has 6 decimals
