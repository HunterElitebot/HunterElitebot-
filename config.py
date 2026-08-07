from __future__ import annotations
import os
TOKEN=os.getenv("TOKEN","").strip()
_raw_owner=os.getenv("OWNER_ID","").strip()
try:
    OWNER_ID=int(_raw_owner) if _raw_owner else None
except ValueError:
    OWNER_ID=None
AUTO_HUNTER_ENABLED=os.getenv("AUTO_HUNTER_ENABLED","true").lower() in {"1","true","yes","on"}
AUTO_HUNTER_INTERVAL=int(os.getenv("AUTO_HUNTER_INTERVAL","90"))
REQUEST_TIMEOUT=int(os.getenv("REQUEST_TIMEOUT","12"))
MAX_RETRY=int(os.getenv("MAX_RETRY","2"))
RETRY_DELAY=float(os.getenv("RETRY_DELAY","1.0"))
DEXSCREENER_URL="https://api.dexscreener.com/latest/dex/tokens/{}"
DEX_LATEST_PROFILES_URL="https://api.dexscreener.com/token-profiles/latest/v1"
DEX_LATEST_BOOSTS_URL="https://api.dexscreener.com/token-boosts/latest/v1"
RUGCHECK_URL="https://api.rugcheck.xyz/v1/tokens/{}/report"
MIN_LIQUIDITY_USD=float(os.getenv("MIN_LIQUIDITY_USD","8000"))
MIN_MARKET_CAP_USD=float(os.getenv("MIN_MARKET_CAP_USD","10000"))
MAX_MARKET_CAP_USD=float(os.getenv("MAX_MARKET_CAP_USD","400000"))
MAX_RUG_RISK=int(os.getenv("MAX_RUG_RISK","35"))
MIN_MOMENTUM_SCORE=int(os.getenv("MIN_MOMENTUM_SCORE","60"))
MIN_HOLDER_SCORE=int(os.getenv("MIN_HOLDER_SCORE","55"))
MIN_ELITE_SCORE=int(os.getenv("MIN_ELITE_SCORE","70"))
MIN_GEM_SCORE=int(os.getenv("MIN_GEM_SCORE","75"))
MIN_X100_SCORE=int(os.getenv("MIN_X100_SCORE","72"))
