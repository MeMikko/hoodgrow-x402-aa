"""A requests.Session that auto-pays x402 challenges via a plain EOA —
works against ANY x402 "exact"-scheme merchant on Base mainnet, not just
HoodGrow. Same underlying mechanism as the `hoodgrow` package's own
`signer` option, generalized to an arbitrary base_url-less session."""

from __future__ import annotations

from typing import Union

import requests
from eth_account.signers.local import LocalAccount

from .wallet import SpendWallet

#: Base mainnet, CAIP-2 form.
NETWORK = "eip155:8453"


def x402_session(wallet: Union[SpendWallet, LocalAccount, str]) -> requests.Session:
    """Build a `requests.Session` that transparently pays any HTTP 402
    x402 challenge it hits, signing with `wallet`.

    Args:
        wallet: a `SpendWallet` (from `create_spend_wallet`), a raw
            `eth_account` `LocalAccount`, or a private key hex string.
            Every payment this makes is real USDC on Base mainnet — only
            fund this wallet with what you're willing to spend, and never
            reuse an EOA that also holds other funds you care about.
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
    x402_client.register(NETWORK, ExactEvmScheme(account))
    wrapRequestsWithPayment(session, x402_client)
    return session
