import asyncio,logging,re
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
from config import TOKEN,OWNER_ID,AUTO_HUNTER_ENABLED,AUTO_HUNTER_INTERVAL
from scanner import scan_token
from analyzer import analyze_token
from report import build_report,build_alert_report,build_scan_error
from hunter import discover_candidates
logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"); logging.getLogger("httpx").setLevel(logging.WARNING); logger=logging.getLogger("HunterElite")
SOLANA_ADDRESS_RE=re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"); _seen_alerts=set()
def is_owner(u):
    user=u.effective_user; return bool(user and OWNER_ID is not None and user.id==OWNER_ID)
async def require_owner(u):
    if is_owner(u):return True
    if u.effective_message:await u.effective_message.reply_text("⛔ Yetkisiz kullanıcı.")
    return False
async def start_command(u,c):
    if not await require_owner(u):return
    await u.effective_message.reply_text("🛡 HUNTERELITE V5 FINAL AKTİF\n\n📩 Solana kontrat adresi gönder → analiz et\n🤖 Auto Hunter → güçlü adayları otomatik tara\n🔥 100X motoru aktif\n🎯 Trade Plan aktif\n🔒 Owner-only aktif")
async def version_command(u,c):
    if await require_owner(u):await u.effective_message.reply_text("HunterElite V5 FINAL")
async def status_command(u,c):
    if not await require_owner(u):return
    await u.effective_message.reply_text(f"🟢 HunterElite V5 çalışıyor.\n🤖 Auto Hunter: {'AKTİF' if AUTO_HUNTER_ENABLED else 'KAPALI'}\n⏱ Tarama aralığı: {AUTO_HUNTER_INTERVAL} sn\n🔥 100X motoru aktif.\n🎯 Trade Plan aktif.\n🔒 Owner-only aktif.")
async def analyze_message(u,c):
    if not await require_owner(u):return
    m=u.effective_message
    if m is None or not m.text:return
    contract=m.text.strip().replace(" ","")
    if not SOLANA_ADDRESS_RE.fullmatch(contract):await m.reply_text("❌ Geçerli bir Solana kontrat adresine benzemiyor."); return
    s=await m.reply_text("🔎 HunterElite V5 analiz ediyor...")
    try:
        r=await asyncio.to_thread(scan_token,contract)
        if not r.get("success"):await s.edit_text(build_scan_error(r.get("errors",[]))); return
        t=r.get("token")
        if not t:await s.edit_text("❌ Token piyasa verisi alınamadı."); return
        a=await asyncio.to_thread(analyze_token,t,r.get("rug")); await s.edit_text(build_report(t,a))
    except Exception as e:logger.exception("Manual analysis failed: %s",e); await s.edit_text("❌ Analiz sırasında hata oluştu.")
async def auto_hunter_job(c):
    if not AUTO_HUNTER_ENABLED or OWNER_ID is None:return
    try:
        for address,t,a in await asyncio.to_thread(discover_candidates,25):
            if address in _seen_alerts:continue
            _seen_alerts.add(address); await c.bot.send_message(chat_id=OWNER_ID,text=build_alert_report(t,a))
        if len(_seen_alerts)>2000:_seen_alerts.clear()
    except Exception as e:logger.exception("Auto Hunter failed: %s",e)
async def error_handler(u,c):logger.error("Telegram handler error",exc_info=c.error)
def main():
    if not TOKEN:raise RuntimeError("Railway Variables içinde TOKEN bulunamadı.")
    if OWNER_ID is None:raise RuntimeError("Railway Variables içinde geçerli OWNER_ID bulunamadı.")
    app=ApplicationBuilder().token(TOKEN).build(); app.add_handler(CommandHandler("start",start_command)); app.add_handler(CommandHandler("version",version_command)); app.add_handler(CommandHandler("status",status_command)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,analyze_message)); app.add_error_handler(error_handler)
    if AUTO_HUNTER_ENABLED:app.job_queue.run_repeating(auto_hunter_job,interval=AUTO_HUNTER_INTERVAL,first=20)
    logger.info("Telegram polling başlatılıyor."); app.run_polling(drop_pending_updates=True)
if __name__=="__main__":main()
