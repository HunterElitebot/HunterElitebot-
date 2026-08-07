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
        "🛡 HUNTERELITE V4.2 AKTİF\n\n"
        "Solana kontrat adresini gönder.\n\n"
        "• Rug Risk\n"
        "• Pump Potansiyeli\n"
        "• Momentum Score\n"
        "• Holder Score\n"
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
        "🛡 HunterElite V4.2\n\n"
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
        "🟢 HunterElite V4.2 çalışıyor.\n"
        "⚡ Momentum Score aktif.\n"
        "🐋 Holder Score aktif.\n"
        "🔒 Owner-only güvenlik aktif."
    )


async def version_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await require_owner(update):
        return

    await update.effective_message.reply_text(
        "HunterElite V4.2"
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

    contract = (
        update.effective_message.text
        .strip()
        .replace(" ", "")
    )

    if not SOLANA_ADDRESS_RE.fullmatch(
        contract
    ):

        await update.effective_message.reply_text(
            "❌ Geçerli bir Solana kontrat adresine benzemiyor."
        )

        return

    status_message = (
        await update.effective_message.reply_text(
            "🔎 HunterElite V4.2 analiz ediyor...\n\n"
            "⚡ Momentum hesaplanıyor...\n"
            "🐋 Holder dağılımı inceleniyor...\n"
            "🛡 Rug riski kontrol ediliyor..."
        )
    )

    try:

        scan_result = await asyncio.to_thread(
            scan_token,
            contract,
        )

        if not scan_result.get(
            "success"
        ):

            await status_message.edit_text(
                build_scan_error(
                    scan_result.get(
                        "errors",
                        [],
                    )
                )
            )

            return

        token = scan_result.get(
            "token"
        )

        rug = scan_result.get(
            "rug"
        )

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

        report = build_report(
            token,
            analysis,
        )

        await status_message.edit_text(
            report
        )

        logger.info(
            "V4.2 analyzed contract=%s rug=%s pump=%s momentum=%s holder=%s decision=%s",
            contract,
            analysis["rug"]["score"],
            analysis["pump"]["score"],
            analysis["pump"].get(
                "momentum_score",
                0,
            ),
            analysis["pump"].get(
                "holder_score",
                0,
            ),
            analysis["decision"]["decision"],
        )

    except Exception as exc:

        logger.exception(
            "V4.2 analysis failed: %s",
            exc,
        )

        await status_message.edit_text(
            "❌ Analiz sırasında beklenmeyen bir hata oluştu. "
            "Biraz sonra tekrar dene."
        )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    logger.error(
        "Telegram error",
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
        "HunterElite V4.2 starting owner_id=%s",
        OWNER_ID,
    )

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "version",
            version_command,
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

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
