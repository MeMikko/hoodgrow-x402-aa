import base64
import json

import pytest
import requests
import responses
# Imported from the requests submodule directly, not x402.http.clients'
# package __init__ — that package's __getattr__ lazily tries every
# transport backend (including httpx) to resolve an attribute, which
# fails with "httpx client requires the httpx package" in an environment
# that (correctly) only installs the requests extra.
from x402.http.clients.requests import PaymentError, x402HTTPAdapter

from x402_aa_wallet import create_spend_wallet, x402_session


def _assert_payment_adapter_mounted(session: requests.Session) -> None:
    assert isinstance(session, requests.Session)
    assert isinstance(session.get_adapter("https://example.com"), x402HTTPAdapter)
    assert isinstance(session.get_adapter("http://example.com"), x402HTTPAdapter)


def test_x402_session_accepts_a_spend_wallet():
    wallet = create_spend_wallet()
    _assert_payment_adapter_mounted(x402_session(wallet))


def test_x402_session_accepts_a_raw_private_key_string():
    wallet = create_spend_wallet()
    _assert_payment_adapter_mounted(x402_session(wallet.private_key))


def test_x402_session_accepts_a_local_account():
    wallet = create_spend_wallet()
    _assert_payment_adapter_mounted(x402_session(wallet.account))


def _payment_required_header(amount_atomic: str, asset: str | None = None) -> str:
    """A real, base64-encoded PAYMENT-REQUIRED header (v2 protocol) — the
    same wire format HoodGrow's own endpoints use, not a JSON-body v1
    shortcut. camelCase keys confirmed by dumping the real
    x402.schemas.payments.PaymentRequirements model with by_alias=True."""
    payment_required = {
        "x402Version": 2,
        "resource": {"url": "https://example.com/paid", "method": "GET"},
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": asset or "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "amount": amount_atomic,
                "payTo": "0x8520B3693a2Cf3c2bEa3a505Af3A9c1b093954c7",
                "maxTimeoutSeconds": 60,
                # EIP-712 domain params for USDC's EIP-3009
                # transferWithAuthorization signature — a real x402 server
                # includes these; the scheme can't sign without them.
                "extra": {"name": "USD Coin", "version": "2"},
            }
        ],
    }
    return base64.b64encode(json.dumps(payment_required).encode()).decode()


@responses.activate
def test_x402_session_pays_a_real_402_challenge_and_retries_with_a_payment_signature():
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={"PAYMENT-REQUIRED": _payment_required_header("50000")},  # $0.05
    )
    responses.add(
        responses.GET,
        "https://example.com/paid",
        json={"ok": True},
        status=200,
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet)
    res = session.get("https://example.com/paid")

    assert res.status_code == 200
    assert len(responses.calls) == 2, "expected an initial 402 call plus one paid retry"
    retry_headers = responses.calls[1].request.headers
    assert "PAYMENT-SIGNATURE" in retry_headers or "X-PAYMENT" in retry_headers


@responses.activate
def test_x402_session_with_max_amount_usd_pays_a_challenge_under_the_cap():
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={"PAYMENT-REQUIRED": _payment_required_header("50000")},  # $0.05
    )
    responses.add(
        responses.GET,
        "https://example.com/paid",
        json={"ok": True},
        status=200,
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet, max_amount_usd=0.1)
    res = session.get("https://example.com/paid")

    assert res.status_code == 200
    assert len(responses.calls) == 2


@responses.activate
def test_x402_session_with_max_amount_usd_refuses_to_pay_a_challenge_over_the_cap():
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={"PAYMENT-REQUIRED": _payment_required_header("50000000")},  # $50
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet, max_amount_usd=0.05)

    with pytest.raises(PaymentError, match="exceeds the configured max_amount_usd cap"):
        session.get("https://example.com/paid")


@responses.activate
def test_x402_session_with_max_amount_usd_refuses_an_unrecognized_asset_even_if_amount_looks_small():
    # A $50 charge expressed as if on a 2-decimal asset is "5000" atomic
    # units — numerically far below a $0.50 cap computed assuming
    # 6-decimal USDC (500000). Blindly comparing raw numbers would let
    # this through; verifying the asset itself must refuse it instead.
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={
            "PAYMENT-REQUIRED": _payment_required_header(
                "5000", asset="0x000000000000000000000000000000000000dd"
            )
        },
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet, max_amount_usd=0.5)

    with pytest.raises(PaymentError):
        session.get("https://example.com/paid")


@responses.activate
def test_x402_session_with_max_total_usd_stops_paying_once_the_budget_is_exhausted():
    # Budget fits exactly one $0.05 payment; the second must refuse even
    # though each individual charge is identical and "reasonable" — this
    # is the drain-by-repetition case max_amount_usd alone cannot stop.
    for _ in range(2):
        responses.add(
            responses.GET,
            "https://example.com/paid",
            status=402,
            headers={"PAYMENT-REQUIRED": _payment_required_header("50000")},  # $0.05
        )
        responses.add(
            responses.GET,
            "https://example.com/paid",
            json={"ok": True},
            status=200,
        )

    wallet = create_spend_wallet()
    session = x402_session(wallet, max_total_usd=0.08)

    first = session.get("https://example.com/paid")
    assert first.status_code == 200

    with pytest.raises(PaymentError, match="max_total_usd budget"):
        session.get("https://example.com/paid")


@responses.activate
def test_x402_session_refuses_an_unrecognized_asset_even_with_no_cap_configured():
    # The asset allowlist must not live inside the cap option: an EIP-3009
    # signature is valid for whatever token contract it names, so a capless
    # session was previously willing to sign for ANY asset a merchant put
    # in the challenge.
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={
            "PAYMENT-REQUIRED": _payment_required_header(
                "5000", asset="0x000000000000000000000000000000000000dd"
            )
        },
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet)

    with pytest.raises(PaymentError, match="unrecognized asset"):
        session.get("https://example.com/paid")


@responses.activate
def test_x402_session_pays_an_unrecognized_asset_only_with_the_explicit_opt_out():
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={
            "PAYMENT-REQUIRED": _payment_required_header(
                # 20 full bytes — this path actually signs, so the address
                # must be valid, unlike the refusal tests above.
                "5000", asset="0x00000000000000000000000000000000000000dd"
            )
        },
    )
    responses.add(
        responses.GET,
        "https://example.com/paid",
        json={"ok": True},
        status=200,
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet, allow_unknown_assets=True)
    res = session.get("https://example.com/paid")
    assert res.status_code == 200


@responses.activate
def test_x402_session_ignores_allow_unknown_assets_while_a_cap_is_set():
    # An asset with unverified decimals cannot be measured against a USD
    # cap — honoring the opt-out here would reopen the decimals bypass.
    responses.add(
        responses.GET,
        "https://example.com/paid",
        status=402,
        headers={
            "PAYMENT-REQUIRED": _payment_required_header(
                "5000", asset="0x000000000000000000000000000000000000dd"
            )
        },
    )

    wallet = create_spend_wallet()
    session = x402_session(wallet, max_amount_usd=0.5, allow_unknown_assets=True)

    with pytest.raises(PaymentError, match="unrecognized asset"):
        session.get("https://example.com/paid")
