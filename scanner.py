from __future__ import annotations

import logging
import random
import time
import requests

from config import (
    DEXSCREENER_URL,
    DEX_LATEST_PROFILES_URL,
    DEX_LATEST_BOOSTS_URL,
    RUGCHECK_URL,
    REQUEST_TIMEOUT,
    MAX_RETRY,
    RETRY_DELAY,
)

logger = logging.getLogger("HunterElite.Scanner")


def safe_float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def safe_int(v, d=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


class RetrySession:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "HunterEliteBot/5.1",
                "Accept": "application/json",
            }
        )

    def get_json_any(self, url):
        last = None

        for attempt in range(1, MAX_RETRY + 1):
            try:
                r = self.session.get(url, timeout=REQUEST_TIMEOUT)

                # API rate limit
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")

                    try:
                        wait = float(retry_after) if retry_after else 0
                    except (TypeError, ValueError):
                        wait = 0

                    if wait <= 0:
                        # artan bekleme + küçük rastgele jitter
                        wait = min(
                            15.0,
                            max(2.0, RETRY_DELAY * (2 ** (attempt - 1)))
                            + random.uniform(0.2, 0.8),
                        )

                    logger.warning(
                        "API rate limit 429 attempt=%s/%s wait=%.1fs",
                        attempt,
                        MAX_RETRY,
                        wait,
                    )

                    if attempt < MAX_RETRY:
                        time.sleep(wait)
                        continue

                    r.raise_for_status()

                # Geçici sunucu hataları
                if r.status_code in (500, 502, 503, 504):
                    wait = min(
                        10.0,
                        max(1.0, RETRY_DELAY * (2 ** (attempt - 1)))
                        + random.uniform(0.1, 0.5),
                    )

                    logger.warning(
                        "API server error status=%s attempt=%s/%s wait=%.1fs",
                        r.status_code,
                        attempt,
                        MAX_RETRY,
                        wait,
                    )

                    if attempt < MAX_RETRY:
                        time.sleep(wait)
                        continue

                r.raise_for_status()
                return r.json()

            except (requests.RequestException, ValueError) as e:
                last = e

                logger.warning(
                    "API attempt failed attempt=%s/%s error=%s",
                    attempt,
                    MAX_RETRY,
                    e,
                )

                if attempt < MAX_RETRY:
                    wait = min(
                        10.0,
                        max(1.0, RETRY_DELAY * (2 ** (attempt - 1)))
                        + random.uniform(0.1, 0.5),
                    )
                    time.sleep(wait)

        raise RuntimeError(f"API isteği başarısız: {last}")


class DexScreenerClient:
    def __init__(self):
        self.http = RetrySession()

    def get_pairs(self, c):
        d = self.http.get_json_any(DEXSCREENER_URL.format(c))
        return (d.get("pairs") or []) if isinstance(d, dict) else []

    def get_best_pair(self, c):
        ps = [
            p
            for p in self.get_pairs(c)
            if isinstance(p, dict)
            and str(p.get("chainId", "")).lower() == "solana"
        ]

        return (
            max(
                ps,
                key=lambda p: safe_float(
                    (p.get("liquidity") or {}).get("usd")
                ),
            )
            if ps
            else None
        )

    def get_discovery_addresses(self):
        out = []

        for u in (
            DEX_LATEST_PROFILES_URL,
            DEX_LATEST_BOOSTS_URL,
        ):
            try:
                d = self.http.get_json_any(u)
            except Exception as e:
                logger.warning(
                    "Discovery feed failed url=%s error=%s",
                    u,
                    e,
                )
                continue

            if not isinstance(d, list):
                continue

            for i in d:
                if not isinstance(i, dict):
                    continue

                if str(i.get("chainId", "")).lower() != "solana":
                    continue

                a = str(
                    i.get("tokenAddress")
                    or i.get("address")
                    or ""
                ).strip()

                if a and a not in out:
                    out.append(a)

        return out


class RugCheckClient:
    def __init__(self):
        self.http = RetrySession()

    def get_report(self, c):
        d = self.http.get_json_any(RUGCHECK_URL.format(c))
        return d if isinstance(d, dict) else {}


def pair_age_minutes(p):
    c = safe_float(p.get("pairCreatedAt"), 0)

    if c <= 0:
        return None

    if c > 10_000_000_000:
        c /= 1000

    return max((time.time() - c) / 60, 0)


def pair_age_text(p):
    m = pair_age_minutes(p)

    if m is None:
        return "Bilinmiyor"

    if m < 60:
        return f"{m:.0f} dk"

    if m < 1440:
        return f"{m / 60:.1f} saat"

    return f"{m / 1440:.1f} gün"


def normalize_pair(p):
    b = p.get("baseToken") or {}
    liq = safe_float((p.get("liquidity") or {}).get("usd"))
    mc = safe_float(p.get("marketCap") or p.get("fdv"))
    vol = p.get("volume") or {}

    t = ((p.get("txns") or {}).get("m5") or {})

    buys = safe_int(t.get("buys"))
    sells = safe_int(t.get("sells"))
    total = buys + sells

    return {
        "name": str(b.get("name") or "Bilinmiyor"),
        "symbol": str(b.get("symbol") or "?"),
        "address": str(b.get("address") or ""),
        "price_usd": safe_float(p.get("priceUsd")),
        "liquidity_usd": liq,
        "market_cap_usd": mc,
        "fdv_usd": safe_float(p.get("fdv")),
        "volume_5m": safe_float(vol.get("m5")),
        "volume_1h": safe_float(vol.get("h1")),
        "buys_5m": buys,
        "sells_5m": sells,
        "total_trades_5m": total,
        "buy_ratio_5m": buys / total if total else None,
        "age_minutes": pair_age_minutes(p),
        "age_text": pair_age_text(p),
        "liquidity_mc_ratio": liq / mc if mc > 0 else None,
    }


def _rug_holder_stats(r):
    hs = r.get("topHolders") or r.get("top_holders") or []
    ps = []

    if isinstance(hs, list):
        for i in hs:
            if not isinstance(i, dict):
                continue

            v = i.get("pct", i.get("percentage"))

            try:
                v = float(v)
                v = v * 100 if v <= 1 else v
                ps.append(v)
            except (TypeError, ValueError):
                pass

    ps.sort(reverse=True)

    return (
        ps[0] if ps else None,
        sum(ps[:5]) if ps else None,
        sum(ps[:10]) if ps else None,
    )


def normalize_rug_report(raw):
        raw = raw or {}
    top1, top5, top10 = _rug_holder_stats(raw)

    score = safe_int(raw.get("score"), 0)
    if score > 100:
        score = min(100, round(score / 10))

    risks = raw.get("risks") or []
    ws = []

    if isinstance(risks, list):
        for x in risks[:10]:
            if isinstance(x, dict):
                t = x.get("name") or x.get("description") or x.get("value")
                if t:
                    ws.append(str(t))
            elif x:
                ws.append(str(x))

    return {
        "score": max(0, min(100, score)),
        "top1": top1,
        "top5": top5,
        "top10": top10,
        "mintAuthority": raw.get("mintAuthority"),
        "freezeAuthority": raw.get("freezeAuthority"),
        "warnings": ws,
        "raw": raw,
    }


def scan_token(c):
    res = {
        "success": False,
        "contract": c,
        "pair": None,
        "token": None,
        "rug": None,
        "errors": [],
    }

    try:
        p = DexScreenerClient().get_best_pair(c)
        if p is None:
            res["errors"].append("DexScreener üzerinde Solana pair bulunamadı.")
        else:
            res["pair"] = p
            res["token"] = normalize_pair(p)
            res["success"] = True
    except Exception as e:
        logger.exception("DexScreener tarama hatası")
        res["errors"].append(f"DexScreener hatası: {e}")

    try:
        res["rug"] = normalize_rug_report(RugCheckClient().get_report(c))
    except Exception as e:
        logger.warning("RugCheck verisi alınamadı: %s", e)
        res["errors"].append(f"RugCheck hatası: {e}")
        res["rug"] = normalize_rug_report({})

    return res


def scan_market_only(c):
    res = {
        "success": False,
        "contract": c,
        "token": None,
        "errors": [],
    }

    try:
        p = DexScreenerClient().get_best_pair(c)

        if p is None:
            res["errors"].append("Solana pair bulunamadı.")
            return res

        res["token"] = normalize_pair(p)
        res["success"] = True

    except Exception as e:
        logger.warning("Flash scan error: %s", e)
        res["errors"].append(str(e))

    return res
