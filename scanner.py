from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests

from config import (
    DEXSCREENER_URL,
    RUGCHECK_URL,
    DEX_LATEST_PROFILES_URL,
    DEX_LATEST_BOOSTS_URL,
    REQUEST_TIMEOUT,
    MAX_RETRY,
    RETRY_DELAY,
)

logger = logging.getLogger("HunterElite.Scanner")


class APIError(Exception):
    pass


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class RetrySession:

    def __init__(self) -> None:
        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": "HunterEliteBot/5.0",
                "Accept": "application/json",
            }
        )

    def get_json_any(
        self,
        url: str,
    ) -> Any:

        last_error: Optional[Exception] = None

        for attempt in range(
            1,
            MAX_RETRY + 1,
        ):

            try:

                response = self.session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                )

                response.raise_for_status()

                return response.json()

            except (
                requests.RequestException,
                ValueError,
            ) as exc:

                last_error = exc

                logger.warning(
                    "API attempt failed "
                    "attempt=%s/%s error=%s",
                    attempt,
                    MAX_RETRY,
                    exc,
                )

                if attempt < MAX_RETRY:
                    time.sleep(
                        RETRY_DELAY
                    )

        raise APIError(
            f"API isteği başarısız: {last_error}"
        )

    def get_json_dict(
        self,
        url: str,
    ) -> Dict[str, Any]:

        data = self.get_json_any(
            url
        )

        if not isinstance(
            data,
            dict,
        ):

            raise APIError(
                "API geçerli JSON nesnesi döndürmedi."
            )

        return data


class DexScreenerClient:

    def __init__(self) -> None:
        self.http = RetrySession()

    def get_pairs(
        self,
        contract: str,
    ) -> list:

        data = self.http.get_json_dict(
            DEXSCREENER_URL.format(
                contract
            )
        )

        pairs = (
            data.get("pairs")
            or []
        )

        return (
            pairs
            if isinstance(
                pairs,
                list,
            )
            else []
        )

    def get_best_pair(
        self,
        contract: str,
    ) -> Optional[Dict[str, Any]]:

        pairs = self.get_pairs(
            contract
        )

        solana_pairs = [
            pair
            for pair in pairs
            if (
                isinstance(
                    pair,
                    dict,
                )
                and
                str(
                    pair.get(
                        "chainId",
                        "",
                    )
                ).lower()
                ==
                "solana"
            )
        ]

        if not solana_pairs:
            return None

        return max(
            solana_pairs,
            key=lambda pair: safe_float(
                (
                    pair.get(
                        "liquidity"
                    )
                    or {}
                ).get(
                    "usd"
                )
            ),
        )

    def get_discovery_addresses(
        self,
    ) -> list[str]:

        addresses: list[str] = []

        discovery_urls = (
            DEX_LATEST_PROFILES_URL,
            DEX_LATEST_BOOSTS_URL,
        )

        for url in discovery_urls:

            try:

                data = (
                    self.http.get_json_any(
                        url
                    )
                )

            except Exception as exc:

                logger.warning(
                    "Discovery feed failed "
                    "url=%s error=%s",
                    url,
                    exc,
                )

                continue

            if not isinstance(
                data,
                list,
            ):
                continue

            for item in data:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                chain_id = str(
                    item.get(
                        "chainId",
                        "",
                    )
                ).lower()

                if chain_id != "solana":
                    continue

                address = str(
                    item.get(
                        "tokenAddress"
                    )
                    or
                    item.get(
                        "address"
                    )
                    or
                    ""
                ).strip()

                if (
                    address
                    and
                    address not in addresses
                ):

                    addresses.append(
                        address
                    )

        return addresses


class RugCheckClient:

    def __init__(self) -> None:
        self.http = RetrySession()

    def get_report(
        self,
        contract: str,
    ) -> Dict[str, Any]:

        return self.http.get_json_dict(
            RUGCHECK_URL.format(
                contract
            )
        )


def pair_age_minutes(
    pair: Dict[str, Any],
) -> Optional[float]:

    created = pair.get(
        "pairCreatedAt"
    )

    if created is None:
        return None

    timestamp = safe_float(
        created,
        0.0,
    )

    if timestamp <= 0:
        return None

    if timestamp > 10_000_000_000:
        timestamp /= 1000.0

    return max(
        (
            time.time()
            -
            timestamp
        )
        /
        60.0,
        0.0,
    )


def pair_age_text(
    pair: Dict[str, Any],
) -> str:

    minutes = pair_age_minutes(
        pair
    )

    if minutes is None:
        return "Bilinmiyor"

    if minutes < 60:
        return f"{minutes:.0f} dk"

    if minutes < 1440:
        return f"{minutes / 60:.1f} saat"

    return (
        f"{minutes / 1440:.1f} gün"
    )


def normalize_pair(
    pair: Dict[str, Any],
) -> Dict[str, Any]:

    base = (
        pair.get(
            "baseToken"
        )
        or {}
    )

    liquidity = safe_float(
        (
            pair.get(
                "liquidity"
            )
            or {}
        ).get(
            "usd"
        )
    )

    market_cap = safe_float(
        pair.get(
            "marketCap"
        )
        or
        pair.get(
            "fdv"
        )
    )

    volume = (
        pair.get(
            "volume"
        )
        or {}
    )

    txns_5m = (
        (
            pair.get(
                "txns"
            )
            or {}
        ).get(
            "m5"
        )
        or {}
    )

    buys = safe_int(
        txns_5m.get(
            "buys"
        )
    )

    sells = safe_int(
        txns_5m.get(
            "sells"
        )
    )

    total =
