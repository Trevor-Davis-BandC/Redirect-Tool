from auth_token import make_token, verify_token


def test_valid_token_round_trips():
    token, expiry = make_token("pw", 3600, now=1000)
    assert verify_token("pw", token, now=1500) == expiry == 4600


def test_expired_token_rejected():
    token, _ = make_token("pw", 3600, now=1000)
    assert verify_token("pw", token, now=4600) is None


def test_wrong_secret_rejected():
    token, _ = make_token("pw", 3600, now=1000)
    assert verify_token("other", token, now=1500) is None


def test_tampered_expiry_rejected():
    token, _ = make_token("pw", 3600, now=1000)
    _, sig = token.split(".", 1)
    assert verify_token("pw", f"999999999.{sig}", now=1500) is None


def test_garbage_rejected():
    for bad in (None, "", "abc", "12.", ".abc", "x.y"):
        assert verify_token("pw", bad, now=1) is None
