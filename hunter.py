import logging
from config import MIN_LIQUIDITY_USD,MIN_MARKET_CAP_USD,MAX_MARKET_CAP_USD,MAX_RUG_RISK,MIN_MOMENTUM_SCORE,MIN_HOLDER_SCORE,MIN_ELITE_SCORE,MIN_GEM_SCORE,MIN_X100_SCORE
from scanner import DexScreenerClient,scan_token,scan_market_only
from analyzer import analyze_token
logger=logging.getLogger("HunterElite.Hunter")
def qualifies(token,analysis):
    mc=float(token.get("market_cap_usd") or 0); liq=float(token.get("liquidity_usd") or 0); rug=int((analysis.get("rug") or {}).get("score") or 0); p=analysis.get("pump") or {}; e=analysis.get("elite") or {}; g=analysis.get("gem") or {}; x=analysis.get("x100") or {}
    return liq>=MIN_LIQUIDITY_USD and MIN_MARKET_CAP_USD<=mc<=MAX_MARKET_CAP_USD and rug<=MAX_RUG_RISK and int(p.get("momentum_score") or 0)>=MIN_MOMENTUM_SCORE and int(p.get("holder_score") or 0)>=MIN_HOLDER_SCORE and int(e.get("score") or 0)>=MIN_ELITE_SCORE and int(g.get("score") or 0)>=MIN_GEM_SCORE and int(x.get("score") or 0)>=MIN_X100_SCORE
def discover_candidates(limit=25):
    found=[]
    for a in DexScreenerClient().get_discovery_addresses()[:limit]:
        try:
            s=scan_token(a)
            if not s.get("success"):continue
            t=s.get("token")
            if not t:continue
            an=analyze_token(t,s.get("rug"))
            if qualifies(t,an):found.append((a,t,an))
        except Exception as e:logger.warning("Candidate scan failed address=%s error=%s",a,e)
    found.sort(key=lambda i:int((i[2].get("x100") or {}).get("score") or 0),reverse=True); return found
def discover_flash_candidates(limit=25):
    out=[]
    for a in DexScreenerClient().get_discovery_addresses()[:limit]:
        try:
            s=scan_market_only(a)
            if not s.get("success"):continue
            t=s.get("token")
            if not t:continue
            liq=float(t.get("liquidity_usd") or 0); mc=float(t.get("market_cap_usd") or 0); buys=int(t.get("buys_5m") or 0); sells=int(t.get("sells_5m") or 0); v=float(t.get("volume_5m") or 0); total=buys+sells; br=buys/total if total else 0
            if liq<8000 or not 10000<=mc<=400000 or total<20 or br<.52 or v<3000:continue
            out.append((a,t))
        except Exception as e:logger.warning("Flash candidate error address=%s error=%s",a,e)
    return out
