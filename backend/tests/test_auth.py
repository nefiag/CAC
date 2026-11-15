from backend.app.auth import hash_password, token_hash, verify_password


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("StrongPassword123")
    second = hash_password("StrongPassword123")
    assert first != second
    assert verify_password("StrongPassword123", first)
    assert not verify_password("wrong", first)


def test_session_token_hash_is_deterministic_without_storing_token():
    assert token_hash("secret") == token_hash("secret")
    assert token_hash("secret") != "secret"
