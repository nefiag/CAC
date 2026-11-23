"""Database URL selection shared by the desktop launcher and tests."""

import os


def database_url_for_launcher(app_dir: str, configured: str | None) -> str:
    if configured and configured.strip():
        return configured.strip()
    db_file = os.path.join(app_dir, "ge_accounting.db").replace("\\", "/")
    return f"sqlite+aiosqlite:///{db_file}"
