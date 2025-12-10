"""Configuration loader for the Telegram relay bot.

Environment variables:
- BOT_TOKEN: required bot token.
- ADMIN_USER_ID: Telegram ID of the admin (defaults to @askeditme ID constant).
- DB_PATH: path to SQLite database file (defaults to "projects.db").
"""
from dataclasses import dataclass
import os

ASKEDITME_TELEGRAM_ID = 205386594


@dataclass
class Config:
    bot_token: str
    admin_user_id: int
    db_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN is required")

    admin_raw = os.getenv("ADMIN_USER_ID")
    try:
        admin_id = int(admin_raw) if admin_raw else ASKEDITME_TELEGRAM_ID
    except ValueError as exc:
        raise ValueError("ADMIN_USER_ID must be an integer") from exc

    db_path = os.getenv("DB_PATH", "projects.db")

    return Config(bot_token=token, admin_user_id=admin_id, db_path=db_path)
