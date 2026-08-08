import logging

from config import (
    MIN_LIQUIDITY_USD,
    MIN_MARKET_CAP_USD,
    MAX_MARKET_CAP_USD,
    MAX_RUG_RISK,
    MIN_MOMENTUM_SCORE,
    MIN_HOLDER_SCORE,
    MIN_ELITE_SCORE,
    MIN_GEM_SCORE,
    MIN_X100_SCORE,
)

from scanner import DexScreenerClient, scan_token, scan_market_only
from analyzer import analyze_token

logger = logging.getLogger("HunterElite.Hunter")


def scores(analysis):
    rug = int((analysis.get("rug") or {}).get("score") or 0)
    pump = analysis.get("pump") or {}
    elite = analysis.get("elite") or {}
    gem = analysis.get("gem") or {}
    x100 = analysis.get("x100") or {}

    momentum = int(pump.get("momentum_score") or 0)
    holder = int(pump.get("holder_score") or 0)
    elite_score = int(elite.get("score") or 0)
    gem_score = int(gem.get("score") or 0)
    x100_score = int(x100.get("score") or 0)

    return rug, momentum, holder, elite_score, gem_score, x100_score


def qualifies(token, analysis):
    mc = float(token.get("market_cap_usd") or 0)
    liq = float(token.get("liquidity_usd") or 0)

    rug, momentum, holder, elite, gem, x100 = scores(analysis)

    return (
        liq >= MIN_LIQUIDITY_USD
        and MIN_MARKET_CAP_USD <= mc <= MAX_MARKET_CAP_USD
        and rug <= MAX_RUG_RISK
        and momentum >= MIN_MOMENTUM_SCORE
        and holder >= MIN_HOLDER_SCORE
        and elite >= MIN_ELITE_SCORE
        and gem >= MIN_GEM_SCORE
        and x100 >= MIN_X100_SCORE
    )


def early_radar(token, analysis):
    mc = float(token.get("market_cap_usd") or 0)
    liq = float(token.get("liquidity_usd") or 0)

    buys = int(token.get("buys_5m") or 0)
    sells = int(token.get("sells_5m") or 0)
    volume = float(token.get("volume_5m") or 0)

    total = buys + sells
    buy_ratio = buys / total if total else 0

    rug, momentum, holder, elite, gem, x100 = scores(analysis)

    market_ok = (
        MIN_MARKET_CAP_USD <= mc <= MAX_MARKET_CAP_USD
        and liq >= 1000
    )

    activity_ok = (
        total >= 20
        and buy_ratio >= 0.52
        and volume >= 1500
    )

    potential_ok = (
        momentum >= 70
        and (
            gem >= 50
            or x100 >= 55
            or elite >= 40
        )
    )

    # Holder 0 yeni tokenlarda veri henüz oluşmamış olabilir.
    holder_ok = holder == 0 or holder >= 20

    # Radar "AL" sinyali değildir.
    # Yüksek rug riskini yine engelliyoruz.
    rug_ok = rug <= 45

    return (
        market_ok
        and activity_ok
        and potential_ok
        and holder_ok
        and rug_ok
    )


def discover_candidates(limit=25):
    confirmed = []
    radar = []

    addresses = DexScreenerClient().get_discovery_addresses()[:limit]

    for address in addresses:
        try:
            scan = scan_token(address)

            if not scan.get("success"):
                continue

            token = scan.get("token")

            if not token:
                continue

            analysis = analyze_token(token, scan.get("rug"))

            if qualifies(token, analysis):
                confirmed.append((address, token, analysis))

            elif early_radar(token, analysis):
                radar.append((address, token, analysis))

        except Exception as e:
            logger.warning(
                "Candidate scan failed address=%s error=%s",
                address,
                e,
            )

    confirmed.sort(
        key=lambda item: int(
            (item[2].get("x100") or {}).get("score") or 0
        ),
        reverse=True,
    )

    radar.sort(
        key=lambda item: int(
            (item[2].get("x100") or {}).get("score") or 0
        ),
        reverse=True,
    )

    # Güçlü adaylar önce.
    # Güçlü aday yoksa Early Radar adaylarını gönder.
    return confirmed if confirmed else radar[:3]


def discover_flash_candidates(limit=25):
    out = []

    addresses = DexScreenerClient().get_discovery_addresses()[:limit]

    for address in addresses:
        try:
            scan = scan_market_only(address)

            if not scan.get("success"):
                continue

            token = scan.get("token")

            if not token:
                continue

            liq = float(token.get("liquidity_usd") or 0)
            mc = float(token.get("market_cap_usd") or 0)
            buys = int(token.get("buys_5m") or 0)
            sells = int(token.get("sells_5m") or 0)
            volume = float(token.get("volume_5m") or 0)

            total = buys + sells
            buy_ratio = buys / total if total else 0

            if liq < 1000:
                continue

            if not MIN_MARKET_CAP_USD <= mc <= MAX_MARKET_CAP_USD:
                continue

            if total < 20:
                continue

            if buy_ratio < 0.52:
                continue

            if volume < 1500:
                continue

            out.append((address, token))

        except Exception as e:
            logger.warning(
                "Flash candidate error address=%s error=%s",
                address,
                e,
            )

    return out
