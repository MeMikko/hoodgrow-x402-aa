"""A requests.Session that auto-pays x402 challenges via a plain EOA —
works against ANY x402 "exact"-scheme merchant. Same underlying mechanism
as the `hoodgrow` package's own `signer` option, generalized to an
arbitrary base_url-less session."""

from __future__ import annotations

from typing import Any, Union

import requests
from eth_account.signers.local import LocalAccount

from .wallet import SpendWallet

#: Base mainnet, CAIP-2 form — the default network, and the only one
#: registered unless `network` overrides it.
NETWORK = "eip155:8453"

#: USDC's own decimals on every chain x402 currently settles on (Base
#: included) — used to convert a human max_amount_usd into the atomic
#: units payment requirements are expressed in.
_USDC_DECIMALS = 6


def _max_amount_usd_policy(max_amount_usd: float):
    """Refuse (raise) rather than pay any requirement above the cap —
    a real x402Client policy (see register_policy), not a client-side
    amount check bolted on after signing. Mirrors the TypeScript
    implementation's behavior and error message exactly."""
    cap_atomic = round(max_amount_usd * 10**_USDC_DECIMALS)

    def policy(_version: int, requirements: list[Any]) -> list[Any]:
        affordable = [r for r in requirements if int(r.get_amount()) <= cap_atomic]
        if not affordable and requirements:
            asked = ", ".join(f"{r.get_amount()} atomic units on {r.network}" for r in requirements)
            raise ValueError(
                f"x402_session: every payment option ({asked}) exceeds the configured "
                f"max_amount_usd cap of ${max_amount_usd} — refusing to pay. Raise "
                "max_amount_usd if this charge is expected, or investigate why the "
                "server is asking for more than usual."
            )
        return affordable

    return policy


def x402_session(
    wallet: Union[SpendWallet, LocalAccount, str],
    *,
    max_amount_usd: float | None = None,
    network: str = NETWORK,
) -> requests.Session:
    """Build a `requests.Session` that transparently pays any HTTP 402
    x402 challenge it hits, signing with `wallet`.

    Args:
        wallet: a `SpendWallet` (from `create_spend_wallet`), a raw
            `eth_account` `LocalAccount`, or a private key hex string.
            Every payment this makes is real USDC on Base mainnet — only
            fund this wallet with what you're willing to spend, and never
            reuse an EOA that also holds other funds you care about.
        max_amount_usd: refuse to pay any single 402 challenge above this
            USD amount (assumes the asset is USDC — the only asset x402's
            "exact" scheme settles today). Without this, the session pays
            whatever the server's 402 response asks for — a misbehaving
            or compromised merchant returning far more than expected gets
            paid in full, silently. Recommended for any caller giving an
            agent autonomous spending.
        network: override the network this wallet pays on — CAIP-2 form.
            Defaults to `NETWORK` (Base mainnet). Only Base/EVM
            "exact"-scheme payments are supported by this library today
            regardless of the value passed here.
    """
    # Imported lazily so importing this package doesn't require x402's EVM
    # extras unless a session is actually built.
    from x402 import x402ClientSync
    from x402.http.clients import wrapRequestsWithPayment
    from x402.mechanisms.evm.exact import ExactEvmScheme

    if isinstance(wallet, SpendWallet):
        account = wallet.account
    elif isinstance(wallet, str):
        from .wallet import spend_wallet_from_private_key

        account = spend_wallet_from_private_key(wallet).account
    else:
        account = wallet

    session = requests.Session()
    x402_client = x402ClientSync()
    x402_client.register(network, ExactEvmScheme(account))
    if max_amount_usd is not None:
        x402_client.register_policy(_max_amount_usd_policy(max_amount_usd))
    wrapRequestsWithPayment(session, x402_client)
    return session
