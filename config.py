import os

TOKEN = os.getenv("TOKEN")

_owner_raw = os.getenv("OWNER_ID", "").strip()

try:
    OWNER_ID = int(_owner_raw) if _owner_raw else None
except ValueError:
    OWNER_ID = None

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{}/report"

REQUEST_TIMEOUT = 12
MAX_RETRY = 3
RETRY_DELAY = 2

BOT_NAME = "HunterElite"
VERSION = "4.1"
