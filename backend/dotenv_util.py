"""Read/write APP_SECRET_KEY in the project .env file (optional DOTENV_FILE override)."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolved_dotenv_path() -> Path:
    custom = os.getenv("DOTENV_FILE", "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    return repo_root() / ".env"


def upsert_app_secret_key_line(fernet_key: str) -> Path:
    """Replace or append APP_SECRET_KEY=...; preserves other lines and trailing newline."""
    path = resolved_dotenv_path()
    key_line = f"APP_SECRET_KEY={fernet_key.strip()}"
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        out: list[str] = []
        replaced = False
        for line in lines:
            if line.strip().startswith("APP_SECRET_KEY="):
                out.append(key_line)
                replaced = True
            else:
                out.append(line)
        if not replaced:
            if out and out[-1].strip() != "":
                out.append("")
            out.append(key_line)
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key_line + "\n", encoding="utf-8")
    return path
