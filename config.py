import os


TOKEN = os.getenv("TOKEN")

_owner_raw = os.getenv(
    "OWNER_ID",
    "",
).strip()

try:
    OWNER_ID = (
        int(_owner_raw)
        if _owner_raw
        else None
    )
except ValueError:
    OWNER_ID = None


# =========================
# API URLS
# =========================

DEXSCREENER_URL = (
    "https://api.dexscreener.com/"
    "latest/dex/tokens/{}"
)

RUGCHECK_URL = (
    "https://api.rugcheck.xyz/"
    "v1/tokens/{}/report"
)

DEX_LATEST_PROFILES_URL = (
    "https://api.dexscreener.com/"
    "token-profiles/latest/v1"
)

DEX_LATEST_BOOSTS_URL = (
    "https://api.dexscreener.com/"
    "token-boosts/latest/v1"
)


# =========================
# HTTP SETTINGS
# =========================

REQUEST_TIMEOUT = 12

MAX_RETRY = 3

RETRY_DELAY = 2


# =========================
# BOT
# =========================

BOT_NAME = "HunterElite"

VERSION = "5.0"


# =========================
# AUTO HUNTER
# =========================

AUTO_HUNTER_ENABLED = (
    os.getenv(
        "AUTO_HUNTER_ENABLED",
        "true",
    ).lower()
    ==
    "true"
)

AUTO_HUNTER_INTERVAL = int(
    os.getenv(
        "AUTO_HUNTER_INTERVAL",
        "90",
    )
)


# =========================
# MARKET FILTERS
# =========================

MIN_LIQUIDITY_USD = float(
    os.getenv(
        "MIN_LIQUIDITY_USD",
        "12000",
    )
)

MIN_MARKET_CAP_USD = float(
    os.getenv(
        "MIN_MARKET_CAP_USD",
        "15000",
    )
)

MAX_MARKET_CAP_USD = float(
    os.getenv(
        "MAX_MARKET_CAP_USD",
        "300000",
    )
)


# =========================
# SCORE FILTERS
# =========================

MAX_RUG_RISK = int(
    os.getenv(
        "MAX_RUG_RISK",
        "30",
    )
)

MIN_MOMENTUM_SCORE = int(
    os.getenv(
        "MIN_MOMENTUM_SCORE",
        "65",
    )
)

MIN_HOLDER_SCORE = int(
    os.getenv(
        "MIN_HOLDER_SCORE",
        "60",
    )
)

MIN_ELITE_SCORE = int(
    os.getenv(
        "MIN_ELITE_SCORE",
        "70",
    )
)

MIN_GEM_SCORE = int(
    os.getenv(
        "MIN_GEM_SCORE",
        "75",
    )
)

MIN_X100_SCORE = int(
    os.getenv(
        "MIN_X100_SCORE",
        "72",
    )
)
