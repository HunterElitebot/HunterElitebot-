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

from config import TOKEN, OWNER_ID
from scanner import scan_token
from analyzer import analyze_token
from report import build_report, build_scan_error


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("HunterElite")

SOLANA_ADDRESS_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
)


def is_owner(update: Update) -> bool:
    user = update.effective_user

    return bool(
        user
        and OWNER_ID is not None
        and user.id == OWNER_ID
    )


async def deny_access(
    update: Update,
) -> None:

    user = update.effective_user

    logger.warning(
        "Unauthorized access user_id=%s username=%s",
        getattr(user, "id", None),
        getattr(user, "username", None),
    )

    if update.effective_message:

        await update.effective_message.reply_text(
            "⛔ Yetkisiz kullanıcı."
        )


async def require_owner(
    update: Update,
) -> bool:

    if not is_owner(update):

        await deny_access(update)

        return False

    return True


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "🛡 HUNTERELITE V4.4 AKTİF\n\n"
        "Solana kontrat adresini gönder.\n\n"
        "• Rug Risk\n"
        "• Pump Potansiyeli\n"
        "• Momentum Score\n"
        "• Holder Score\n"
        "• Elite Score\n"
        "• Gem Score\n"
        "• Top 1 / Top 5 / Top 10\n"
        "• Likidite analizi\n"
        "• Buy/Sell momentum\n"
        "• Mint/Freeze kontrolü\n"
        "• Gelişmiş karar motoru\n\n"
        "🔒 Owner-only erişim aktif.\n"
        "⚠️ Skorlar yatırım garantisi değildir."
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "🛡 HunterElite V4.4\n\n"
        "Bir Solana kontrat adresini buraya yapıştır.\n\n"
        "/start - Başlangıç\n"
        "/help - Yardım\n"
        "/status - Durum\n"
        "/version - Sürüm"
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "🟢 HunterElite V4.4 çalışıyor.\n"
        "⚡ Momentum Score aktif.\n"
        "🐋 Holder Score aktif.\n"
        "👑 Elite Score aktif.\n"
        "💎 Gem Score aktif.\n"
        "🔒 Owner-only güvenlik aktif."
    )


async def version_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "HunterElite V4.4 FINAL"
    )


async def analyze_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await
