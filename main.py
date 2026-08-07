
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = "BURAYA_YENI_BOT_TOKENINI_YAZ"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 HunterEliteBot aktif!\n\n"
        "Bir Solana kontrat adresi gönder, analiz etmeye başlayayım."
    )

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contract = update.message.text.strip()

    await update.message.reply_text(
        f"🔍 Kontrat alındı:\n\n{contract}\n\n"
        "⏳ Analiz ediliyor..."
    )

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))

app.run_polling()
