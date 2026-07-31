import re

from hoodgrow_x402_aa import SpendWallet, create_spend_wallet, spend_wallet_from_private_key

HEX40 = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^0x[0-9a-fA-F]{64}$")


def test_create_spend_wallet_returns_a_fresh_address_and_matching_private_key():
    wallet = create_spend_wallet()
    assert isinstance(wallet, SpendWallet)
    assert HEX40.match(wallet.address)
    assert HEX64.match(wallet.private_key)
    # The account's own address must match the reported address.
    assert wallet.account.address == wallet.address


def test_create_spend_wallet_generates_a_different_wallet_each_call():
    a = create_spend_wallet()
    b = create_spend_wallet()
    assert a.address != b.address
    assert a.private_key != b.private_key


def test_spend_wallet_from_private_key_rehydrates_the_same_address():
    original = create_spend_wallet()
    rehydrated = spend_wallet_from_private_key(original.private_key)
    assert rehydrated.address == original.address
    assert rehydrated.private_key == original.private_key
