from __future__ import annotations
import os, asyncio, requests
from typing import Any, Dict, Optional
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN=os.getenv("TOKEN","").strip()
DEX="https://api.dexscreener.com/latest/dex/tokens/{}"
RUG="https://api.rugcheck.xyz/v1/tokens/{}/report"
TIMEOUT=12
MC_MIN,MC_MAX=2000.0,10000.0

def num(v, default=None):
    try:
        if v is None:return default
        return float(v)
    except (TypeError,ValueError):return default

def money(v):
    return "⚠️ VERİ ALINAMADI" if v is None else f"${v:,.2f}"

def get_json(url):
    r=requests.get(url,timeout=TIMEOUT,headers={"User-Agent":"HunterEliteBot/9.2"})
    r.raise_for_status()
    return r.json()

def dex_pair(ca):
    raw=get_json(DEX.format(ca))
    pairs=[p for p in (raw.get("pairs") or []) if str(p.get("chainId","")).lower()=="solana"]
    if not pairs:return None
    def rank(p):
        return (num((p.get("liquidity") or {}).get("usd"),0) or 0,
                num((p.get("volume") or {}).get("h24"),0) or 0)
    return max(pairs,key=rank)

def rug_report(ca):
    try:return get_json(RUG.format(ca))
    except Exception:return None

def authority_state(raw, key):
    if not isinstance(raw,dict): return None
    val=raw.get(key)
    if val is None:
        token=raw.get("token") or raw.get("tokenMeta") or {}
        val=token.get(key) if isinstance(token,dict) else None
    if isinstance(val,bool): return val
    if isinstance(val,str):
        s=val.strip().lower()
        if s in ("","null","none","false","revoked","disabled"): return False
        return True
    return None if val is None else bool(val)

def holder_stats(raw):
    if not isinstance(raw,dict): return None,None,None
    holders=raw.get("topHolders") or raw.get("top_holders") or raw.get("holders")
    if not isinstance(holders,list) or not holders:return None,None,None
    vals=[]
    for h in holders:
        if not isinstance(h,dict):continue
        v=None
        for k in ("pct","percentage","percent","ownershipPct","ownershipPercentage"):
            if h.get(k) is not None:
                v=num(h.get(k)); break
        if v is not None:
            if 0 <= v <= 1: v*=100
            vals.append(v)
    if not vals:return None,None,None
    return vals[0],sum(vals[:5]),sum(vals[:10])

def rug_signals(raw):
    text=""
    risks=[]
    if isinstance(raw,dict):
        risks=raw.get("risks") or []
        text=str(raw).lower()
    keywords={
        "bundler":("bundl",),
        "insider":("insider",),
        "sniper":("sniper",),
        "honeypot":("honeypot","honey pot"),
        "rug":("rug pull","rugpull"),
    }
    found=set()
    for name,words in keywords.items():
        if any(w in text for w in words):found.add(name)
    # Prefer explicit risk records if present
    for r in risks if isinstance(risks,list) else []:
        if not isinstance(r,dict):continue
        s=(" ".join(str(r.get(k,"")) for k in ("name","description","message","level"))).lower()
        for name,words in keywords.items():
            if any(w in s for w in words):found.add(name)
    return found

def analyze(ca):
    try:p=dex_pair(ca)
    except Exception:p=None
    if not p:return "❌ DEX Screener üzerinde Solana pair bulunamadı."

    mc=num(p.get("marketCap"))
    if mc is None: mc=num(p.get("fdv"))
    liq=num((p.get("liquidity") or {}).get("usd"))
    tx5=(p.get("txns") or {}).get("m5") or {}
    tx1=(p.get("txns") or {}).get("h1") or {}
    buys5=int(num(tx5.get("buys"),0) or 0); sells5=int(num(tx5.get("sells"),0) or 0)
    buys1=int(num(tx1.get("buys"),0) or 0); sells1=int(num(tx1.get("sells"),0) or 0)
    vol5=num((p.get("volume") or {}).get("m5"),0) or 0
    ch5=num((p.get("priceChange") or {}).get("m5"),0) or 0

    rug=rug_report(ca)
    top1,top5,top10=holder_stats(rug)
    mint=authority_state(rug,"mintAuthority")
    freeze=authority_state(rug,"freezeAuthority")
    signals=rug_signals(rug)

    score=70
    risks=[]; data=[]

    if mc is None:data.append("Market cap verisi alınamadı"); score-=15
    elif not MC_MIN<=mc<=MC_MAX:risks.append("Market cap 2K–10K giriş bölgesi dışında"); score-=15

    if liq is None:data.append("Likidite verisi alınamadı")
    elif liq<5000:risks.append("Likidite < $5K"); score-=20
    else:score+=5

    if sells5>buys5:risks.append("5dk satış baskısı"); score-=10
    elif buys5>sells5*1.4 and buys5>=10:score+=8
    if vol5<500:risks.append("5dk hacim zayıf"); score-=8
    elif vol5>=5000:score+=5
    if ch5>=100:risks.append("5dk aşırı pump"); score-=18

    if rug is None:
        data.append("RugCheck verisi alınamadı"); score-=10
    else:
        if top10 is None:data.append("Top-10 holder yüzdesi API yanıtında yok")
        else:
            if top10>=50:risks.append(f"Top-10 holder çok yüksek: %{top10:.1f}"); score-=25
            elif top10>=35:risks.append(f"Top-10 holder yüksek: %{top10:.1f}"); score-=15
            else:score+=5
        if top1 is not None and top1>=20:risks.append(f"En büyük holder yüksek: %{top1:.1f}"); score-=15
        if mint is True:risks.append("Mint authority aktif"); score-=20
        elif mint is False:score+=5
        else:data.append("Mint authority durumu alınamadı")
        if freeze is True:risks.append("Freeze authority aktif"); score-=20
        elif freeze is False:score+=5
        else:data.append("Freeze authority durumu alınamadı")
        penalties={"bundler":15,"insider":15,"sniper":10,"honeypot":30,"rug":30}
        labels={"bundler":"Bundler riski","insider":"Insider riski","sniper":"Sniper riski",
                "honeypot":"Honeypot riski","rug":"Rug-pull sinyali"}
        for s in sorted(signals):
            risks.append(labels[s]); score-=penalties[s]

    score=max(0,min(100,score))
    critical=(liq is None or rug is None or top10 is None)
    if score>=75 and mc is not None and MC_MIN<=mc<=MC_MAX and not critical:
        verdict="🟢 UYGUN GİRİŞ ADAYI"
    elif score>=50:
        verdict="🟡 BEKLE / KRİTİK VERİ EKSİK" if critical else "🟡 BEKLE / DİKKATLİ İNCELE"
    else:verdict="🔴 GİRME / YÜKSEK RİSK"

    name=(p.get("baseToken") or {}).get("name") or "Token"
    symbol=(p.get("baseToken") or {}).get("symbol") or "?"
    holder_line="N/A" if top10 is None else f"%{top10:.1f}"
    auth=lambda v: "⚠️ N/A" if v is None else ("🔴 AKTİF" if v else "✅ KAPALI")
    risk_text="\n".join("• "+x for x in risks) or "• Belirgin kritik sinyal yok"
    data_text="\n".join("• "+x for x in data) or "• Kritik veri eksiği yok"

    return f"""🦅 HUNTERELITE V9.2

{name} ({symbol})
CA: {ca}

🎯 Market Giriş Bölgesi: $2K–$10K
Market Cap: {money(mc)}
Likidite: {money(liq)}

⚡ 5dk: {buys5} buy / {sells5} sell
📊 1s: {buys1} buy / {sells1} sell
💵 5dk hacim: {money(vol5)}
📈 5dk fiyat: {ch5:+.1f}%

🧪 RugCheck Derin Kontrol
RugCheck: {"✅ ALINDI" if rug is not None else "⚠️ ALINAMADI"}
Top-10 holder: {holder_line}
Mint authority: {auth(mint)}
Freeze authority: {auth(freeze)}
Bundler: {"🔴 SİNYAL" if "bundler" in signals else "✅ YOK"}
Insider: {"🔴 SİNYAL" if "insider" in signals else "✅ YOK"}
Sniper: {"🟠 SİNYAL" if "sniper" in signals else "✅ YOK"}

🛡 Hunter Elite Score: {score}/100
{verdict}

⚠️ Riskler:
{risk_text}

📡 Veri Durumu:
{data_text}

Not: Bu rapor risk filtresidir; kâr garantisi değildir."""

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🦅 HunterEliteBot V9.2 aktif!\nSolana kontrat adresini gönder.")
async def status(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ HunterElite V9.2 ONLINE\n🎯 Market giriş filtresi: $2K–$10K")
async def handle(update:Update,context:ContextTypes.DEFAULT_TYPE):
    ca=(update.message.text or "").strip()
    if len(ca)<30 or " " in ca:
        await update.message.reply_text("Solana kontrat adresini tek satır olarak gönder.");return
    msg=await update.message.reply_text("🔎 V9.2 derin tarıyor...")
    try:result=await asyncio.to_thread(analyze,ca)
    except Exception as e:result=f"❌ Analiz hatası: {type(e).__name__}"
    await msg.edit_text(result)

def main():
    if not TOKEN:raise RuntimeError("Railway Variables içinde TOKEN eksik.")
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("status",status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle))
    print("HUNTERELITE V9.2 ONLINE")
    app.run_polling(drop_pending_updates=True)
if __name__=="__main__":main()
