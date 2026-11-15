from backend.app.auth import hash_password, token_hash, verify_password
from backend.app.services.statement_agent import expand_statement_archives
import io
import zipfile
import pytest


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("StrongPassword123")
    second = hash_password("StrongPassword123")
    assert first != second
    assert verify_password("StrongPassword123", first)
    assert not verify_password("wrong", first)


def test_session_token_hash_is_deterministic_without_storing_token():
    assert token_hash("secret") == token_hash("secret")
    assert token_hash("secret") != "secret"


def test_statement_zip_expands_supported_files_and_ignores_noise():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("statements/bank.csv", "交易日期,金额\n2026-01-01,1")
        archive.writestr("__MACOSX/readme.txt", "noise")
    result = expand_statement_archives([("batch.zip", payload.getvalue())])
    assert [name for name, _ in result["files"]] == ["bank.csv"]
    assert result["ignored"] == ["__MACOSX/readme.txt"]


def test_statement_archive_rejects_empty_supported_set():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("readme.txt", "noise")
    with pytest.raises(ValueError, match="未找到可解析"):
        expand_statement_archives([("batch.zip", payload.getvalue())])
