from pathlib import Path

import yaml

from database_url import database_url_for_launcher


ROOT = Path(__file__).resolve().parents[2]


def test_launcher_preserves_postgresql_url():
    configured = "postgresql+asyncpg://user:secret@db:5432/ledger"
    assert database_url_for_launcher("C:/app", configured) == configured


def test_launcher_defaults_to_sibling_sqlite_file():
    assert database_url_for_launcher("C:/app", None) == "sqlite+aiosqlite:///C:/app/ge_accounting.db"


def test_development_compose_binds_services_to_loopback_and_has_no_default_password():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(text.replace("${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}", "test-secret"))
    assert compose["services"]["db"]["ports"] == ["127.0.0.1:5432:5432"]
    assert compose["services"]["backend"]["ports"] == ["127.0.0.1:8000:8000"]
    assert "coxiaoac_password" not in text


def test_cloudflared_image_is_pinned():
    compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    image = compose["services"]["tunnel"]["image"]
    assert image.startswith("cloudflare/cloudflared:")
    assert not image.endswith(":latest")
