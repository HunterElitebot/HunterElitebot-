from __future__ import annotations

import logging
from typing import Any, Dict

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

from scanner import (
    DexScreenerClient,
    scan_token,
)

from analyzer import analyze_token


logger = logging.getLogger(
    "HunterElite.Hunter"
)


def qualifies(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> bool:

    market_cap = float(
        token.get(
            "market_cap_usd"
        )
        or 0
    )

    liquidity = float(
        token.get(
            "liquidity_usd"
        )
        or 0
    )

    rug_score = int(
        (
            analysis.get("rug")
            or {}
        ).get(
            "score"
        )
        or 100
    )

    momentum_score = int(
        (
            analysis.get("pump")
            or {}
        ).get(
            "momentum_score"
        )
        or 0
    )

    holder_score = int(
        (
            analysis.get("pump")
            or {}
        ).get(
            "holder_score"
        )
        or 0
    )

    elite_score = int(
        (
            analysis.get("elite")
            or {}
        ).get(
            "score"
        )
        or 0
    )

    gem_score = int(
        (
            analysis.get("gem")
            or {}
        ).get(
            "score"
        )
        or 0
    )

    x100_score = int(
        (
            analysis.get("x100")
            or {}
        ).get(
            "score"
        )
        or 0
    )

    return (
        liquidity
        >=
        MIN_LIQUIDITY_USD

        and
        MIN_MARKET_CAP_USD
        <=
        market_cap
        <=
        MAX_MARKET_CAP_USD

        and
        rug_score
        <=
        MAX_RUG_RISK

        and
        momentum_score
        >=
        MIN_MOMENTUM_SCORE

        and
        holder_score
        >=
        MIN_HOLDER_SCORE

        and
        elite_score
        >=
        MIN_ELITE_SCORE

        and
        gem_score
        >=
        MIN_GEM_SCORE

        and
        x100_score
        >=
        MIN_X100_SCORE
    )


def discover_candidates(
    limit: int = 25,
) -> list[
    tuple[
        str,
        Dict[str, Any],
        Dict[str, Any],
    ]
]:

    client = DexScreenerClient()

    addresses = (
        client.get_discovery_addresses()
        [:limit]
    )

    found = []

    for address in addresses:

        try:

            result = scan_token(
                address
            )

            if not result.get(
                "success"
            ):
                continue

            token = result.get(
                "token"
            )

            rug = result.get(
                "rug"
            )

            if not token:
                continue

            analysis = analyze_token(
                token,
                rug,
            )

            if qualifies(
                token,
                analysis,
            ):

                found.append(
                    (
                        address,
                        token,
                        analysis,
                    )
                )

        except Exception as exc:

            logger.warning(
                "Candidate scan failed "
                "address=%s error=%s",
                address,
                exc,
            )

    return found
    def discover_flash_candidates(
    limit: int = 25,
):
    from scanner import (
        DexScreenerClient,
        scan_market_only,
    )

    addresses = (
        DexScreenerClient()
        .get_discovery_addresses()
    )

    results = []

    for address in addresses[:limit]:

        try:
            scan = scan_market_only(
                address
            )

            if not scan.get("success"):
                continue

            token = scan.get("token")

            if not token:
                continue

            liquidity = float(
                token.get(
                    "liquidity_usd"
                )
                or 0
            )

            market_cap = float(
                token.get(
                    "market_cap_usd"
                )
                or 0
            )

            buys = int(
                token.get(
                    "buys_5m"
                )
                or 0
            )

            sells = int(
                token.get(
                    "sells_5m"
                )
                or 0
            )

            volume_5m = float(
                token.get(
                    "volume_5m"
                )
                or 0
            )

            total = buys + sells

            buy_ratio = (
                buys / total
                if total > 0
                else 0
            )

            if liquidity < 8000:
                continue

            if market_cap < 10000:
                continue

            if market_cap > 400000:
                continue

            if total < 20:
                continue

            if buy_ratio < 0.52:
                continue

            if volume_5m < 3000:
                continue

            results.append(
                (
                    address,
                    token,
                )
            )

        except Exception as exc:

            logger.warning(
                "Flash candidate error "
                "address=%s error=%s",
                address,
                exc,
            )

    return results
