# config.py — Centralized config from environment variables.
# Railway: values come from env vars in the dashboard.
# Local: falls back to config.json if it exists.

import os
import json

_file_config = {}
_config_path = os.path.join(os.path.dirname(__file__), "config.json")
if os.path.exists(_config_path):
    with open(_config_path, "r") as f:
        _file_config = json.load(f)


def _get(key, default=""):
    return os.environ.get(key, _file_config.get(key, default))


BOT_TOKEN = _get("BOT_TOKEN")
OWNER_ID = _get("OWNER_ID")
GUILD_ID = _get("GUILD_ID")
LOG_CHANNEL_ID = _get("LOG_CHANNEL_ID")
EMBED_COLOR = _get("EMBED_COLOR", "FF8C00")
BOT_NAME = _get("BOT_NAME", "Mango Bot")
BOT_FOOTER = _get("BOT_FOOTER", "Mango Bot • Key Reseller")

# Database path — on Railway use a volume mount for persistence.
# Set DATA_DIR env var to your volume mount path (e.g. /data).
# Locally defaults to ./data next to the code.
DATA_DIR = _get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "bot.db")
os.makedirs(DATA_DIR, exist_ok=True)
