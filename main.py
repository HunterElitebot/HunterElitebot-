from __future__ import annotations

import asyncio
import logging
import re

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    TOKEN,
    OWNER_ID,
    AUTO_HUNTER_ENABLED,
    AUTO_HUNTER_INTERVAL,
)

from scanner import scan_token
from analyzer import analyze_token
from report import (
    build_report,
    build_alert_report,
    build_scan_error,
)
from hunter import discover_candidates


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("HunterElite")

SOLANA_ADDRESS_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
)

_seen_alerts: set[str] = set()


def is_owner(
    update: Update,
) -> bool:

    user = update.effective_user

    return bool(
        user
        and OWNER_ID is not None
        and user.id == OWNER_ID
    )


async def require_owner(
    update: Update,
) -> bool:

    if not is_owner(update):

        if update.effective_message:

            await update.effective_message.reply_text(
                "⛔ Yetkisiz kullanıcı."
            )

        return False

    return True


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "🛡 HUNTERELITE V5 FINAL AKTİF\n\n"
        "Kontrat gönder → anlık analiz\n"
        "Auto Hunter → uygun adayları otomatik tarar\n\n"
        "🛡 Rug Risk\n"
        "🚀 Pump Score\n"
        "⚡ Momentum Score\n"
        "🐋 Holder Score\n"
        "👑 Elite Score\n"
        "💎 Gem Score\n"
        "🔥 100X Potansiyel\n"
        "🎯 Trade Plan\n"
        "🚨 Hunter Alert\n\n"
        "🔒 Owner-only erişim aktif."
    )


async def version_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "HunterElite V5 FINAL"
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    auto_status = (
        "AKTİF"
        if AUTO_HUNTER_ENABLED
        else "KAPALI"
    )

    await update.effective_message.reply_text(
        "🟢 HunterElite V5 çalışıyor.\n"
        f"🤖 Auto Hunter: {auto_status}\n"
        f"⏱ Tarama aralığı: {AUTO_HUNTER_INTERVAL} sn\n"
        "🔥 100X motoru aktif.\n"
        "🎯 Trade Plan aktif.\n"
        "🔒 Owner-only aktif."
    )


async def analyze_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    if (
        not update.effective_message
        or
        not update.effective_message.text
    ):
        return

    contract
