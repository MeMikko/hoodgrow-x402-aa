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

#: Circle's own native USDC contract addresses, keyed by CAIP-2 network —
#: every one is 6 decimals (Circle mandates this across all its official
#: deployments, unlike third-party bridged/wrapped variants elsewhere).
#: A PaymentRequirements.asset is just an address; nothing about the x402
#: protocol guarantees it points at one of these. _max_amount_usd_policy
#: only applies the _USDC_DECIMALS-based cap to a requirement whose asset
#: matches an entry here — anything else is excluded rather than
#: evaluated with a guessed decimal count. Guessing UNDER the real decimal
#: count (e.g. treating an 18-decimal asset's raw amount as 6-decimal)
#: makes a genuinely large charge look small enough to pass the cap — a
#: fail-open worse than refusing to pay an asset this policy can't verify.
_KNOWN_USDC_ADDRESSES = {
    "eip155:8453": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # Base mainnet
    "eip155:84532": "0x036cbd53842c5426634e7929541ec2318f3dcf7e",  # Base Sepolia
}


def _max_amount_usd_policy(max_amount_usd: float):
    """Refuse (raise) rather than pay any requirement above the cap —
    a real x402Client policy (see register_policy), not a client-side
    amount check bolted on after signing. Mirrors the TypeScript
    implementation's behavior and error message exactly."""
    cap_atomic = round(max_amount_usd * 10**_USDC_DECIMALS)

    def _is_affordable(r: Any) -> bool:
        known_usdc = _KNOWN_USDC_ADDRESSES.get(r.network)
        if known_usdc is None or r.asset.lower() != known_usdc:
            return False
        return int(r.get_amount()) <= cap_atomic

    def policy(_version: int, requirements: list[Any]) -> list[Any]:
        affordable = [r for r in requirements if _is_affordable(r)]
        if not affordable and requirements:
            def _reason(r: Any) -> str:
                known_usdc = _KNOWN_USDC_ADDRESSES.get(r.network)
                if known_usdc is None or r.asset.lower() != known_usdc:
                    return "unrecognized asset, decimals not verified"
                return "over cap"

            asked = ", ".join(
                f"{r.get_amount()} atomic units of {r.asset} on {r.network} ({_reason(r)})"
                for r in requirements
            )
            raise ValueError(
                f"x402_session: every payment option ({asked}) exceeds the configured "
                f"max_amount_usd cap of ${max_amount_usd}, or is on an asset this policy "
                "can't verify — refusing to pay. Raise max_amount_usd if this charge is "
                "expected, or investigate why the server is asking for more than usual."
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
