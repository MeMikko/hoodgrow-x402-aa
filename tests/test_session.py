import requests
from x402.http.clients import x402HTTPAdapter

from hoodgrow_x402_aa import create_spend_wallet, x402_session


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
