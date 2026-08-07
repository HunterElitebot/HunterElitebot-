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

from hunter import (
    discover_candidates,
    discover_flash_candidates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("HunterElite")

SOLANA_ADDRESS_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
)

_seen_alerts: set[str] = set()
_seen_flash_alerts: set[str] = set()


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
    if is_owner(update):
        return True

    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Yetkisiz kullanıcı."
        )

    return False


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "🛡 HUNTERELITE V5 FINAL AKTİF\n\n"
        "📩 Solana kontrat adresi gönder → analiz et\n"
        "🤖 Auto Hunter → güçlü adayları otomatik tara\n\n"
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

    message = update.effective_message

    if (
        message is None
        or not message.text
    ):
        return

    contract = (
        message.text
        .strip()
        .replace(" ", "")
    )

    if not SOLANA_ADDRESS_RE.fullmatch(
        contract
    ):
        await message.reply_text(
            "❌ Geçerli bir Solana kontrat adresine benzemiyor."
        )
        return

    status_message = await message.reply_text(
        "🔎 HunterElite V5 analiz ediyor..."
    )

    try:
        result = await asyncio.to_thread(
            scan_token,
            contract,
        )

        if not result.get("success"):
            await status_message.edit_text(
                build_scan_error(
                    result.get(
                        "errors",
                        [],
                    )
                )
            )
            return

        token = result.get("token")
        rug = result.get("rug")

        if not token:
            await status_message.edit_text(
                "❌ Token piyasa verisi alınamadı."
            )
            return

        analysis = await asyncio.to_thread(
            analyze_token,
            token,
            rug,
        )

        report_text = build_report(
            token,
            analysis,
        )

        await status_message.edit_text(
            report_text
        )

    except Exception as exc:
        logger.exception(
            "Manual analysis failed: %s",
            exc,
        )

        await status_message.edit_text(
            "❌ Analiz sırasında hata oluştu."
        )


async def auto_hunter_job(
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not AUTO_HUNTER_ENABLED:
        return

    if OWNER_ID is None:
        return

    try:
        candidates = await asyncio.to_thread(
            discover_candidates,
            25,
        )

        for (
            address,
            token,
            analysis,
        ) in candidates:

            if address in _seen_alerts:
                continue

            _seen_alerts.add(
                address
            )

            alert_text = build_alert_report(
                token,
                analysis,
            )

            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=alert_text,
            )

        if len(_seen_alerts) > 2000:
            _seen_alerts.clear()

    except Exception as exc:
        logger.exception(
            "Auto Hunter failed: %s",
            exc,
        )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    logger.error(
        "Telegram handler error",
        exc_info=context.error,
    )


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "Railway Variables içinde TOKEN bulunamadı."
        )

    if OWNER_ID is None:
        raise RuntimeError(
            "Railway Variables içinde geçerli OWNER_ID bulunamadı."
        )

    logger.info(
        "HunterElite V5 FINAL başlatılıyor."
    )

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "version",
            version_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            &
            ~filters.COMMAND,
            analyze_message,
        )
    )

    app.add_error_handler(
        error_handler
    )

    if AUTO_HUNTER_ENABLED:
        app.job_queue.run_repeating(
            auto_hunter_job,
            interval=AUTO_HUNTER_INTERVAL,
            first=20,
        )

    logger.info(
        "Telegram polling başlatılıyor."
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()   
