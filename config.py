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


BOT_TOKEN      = _get("BOT_TOKEN")
OWNER_ID       = _get("OWNER_ID")
GUILD_ID       = _get("GUILD_ID")
LOG_CHANNEL_ID = _get("LOG_CHANNEL_ID")
EMBED_COLOR    = _get("EMBED_COLOR", "FF8C00")
BOT_NAME       = _get("BOT_NAME", "Mango Bot")
BOT_FOOTER     = _get("BOT_FOOTER", "Mango Bot • Key Reseller")

# Aegis API credentials
AEGIS_API_KEY    = _get("AEGIS_API_KEY")
AEGIS_API_SECRET = _get("AEGIS_API_SECRET")
AEGIS_BASE_URL   = _get("AEGIS_BASE_URL", "https://clientarea.aegisonline.site")

# SMBPanel API key — set this in Railway env vars
SMB_API_KEY = _get("SMB_API_KEY")

# Database path
DATA_DIR = _get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH  = os.path.join(DATA_DIR, "bot.db")
os.makedirs(DATA_DIR, exist_ok=True)
