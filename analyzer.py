from pump_score import calculate_pump_score,authority_status
from elite_score import calculate_elite_score
from gem_score import calculate_gem_score
from x100_score import calculate_x100_score
from trade_plan import build_trade_plan
def _rug_analysis(token,rug):
    rug=rug or {}; score=int(rug.get("score") or 0); warnings=list(rug.get("warnings") or []); positives=[]; top1=rug.get("top1"); top5=rug.get("top5"); top10=rug.get("top10"); liq=float(token.get("liquidity_usd") or 0); mc=float(token.get("market_cap_usd") or 0); age=token.get("age_minutes"); buys=int(token.get("buys_5m") or 0); sells=int(token.get("sells_5m") or 0); auth=authority_status(rug)
    if liq<5000:score+=35; warnings.append("Likidite çok düşük")
    elif liq<12000:score+=12; warnings.append("Likidite düşük")
    else:positives.append("Likidite güçlü")
    if mc>0 and liq/mc>=.12:positives.append("Likidite/MC güçlü")
    if top10 is not None:
        if float(top10)>=60:score+=35; warnings.append(f"Top 10 tehlikeli: %{float(top10):.1f}")
        elif float(top10)>=35:score+=15; warnings.append(f"Top 10 dikkat: %{float(top10):.1f}")
        else:positives.append("Top 10 dağılımı sağlıklı")
    if top1 is not None:
        if float(top1)>=25:score+=30; warnings.append(f"Tek holder çok yüksek: %{float(top1):.1f}")
        elif float(top1)>=12:score+=12; warnings.append(f"En büyük holder yüksek: %{float(top1):.1f}")
        else:positives.append("En büyük holder payı düşük")
    if auth["mint_open"]:score+=20; warnings.append("Mint Authority açık")
    else:positives.append("Mint Authority kapalı")
    if auth["freeze_open"]:score+=20; warnings.append("Freeze Authority açık")
    else:positives.append("Freeze Authority kapalı")
    if age is not None and float(age)<5:score+=8; warnings.append("Token aşırı yeni")
    elif age is not None and float(age)<20:warnings.append("Token erken aşamada")
    if sells>buys and buys+sells>20:score+=8; warnings.append("Satış tarafı baskın")
    score=max(0,min(100,int(score))); label="DÜŞÜK RİSK" if score<=20 else "ORTA RİSK" if score<=40 else "YÜKSEK RİSK" if score<=65 else "ÇOK YÜKSEK RİSK"
    return {"score":score,"label":label,"warnings":warnings[:18],"positives":positives[:12],"top1":top1,"top5":top5,"top10":top10}
def analyze_token(token,rug):
    rr=_rug_analysis(token,rug); pump=calculate_pump_score(token,rr); elite=calculate_elite_score(rr["score"],pump["score"],pump["momentum_score"],pump["holder_score"],float(token.get("liquidity_usd") or 0)); gem=calculate_gem_score(elite["score"],pump["score"],rr["score"],float(token.get("market_cap_usd") or 0),token.get("age_minutes")); x=calculate_x100_score(gem["score"],elite["score"],rr["score"],float(token.get("market_cap_usd") or 0),float(token.get("liquidity_usd") or 0),pump["momentum_score"]); plan=build_trade_plan(float(token.get("market_cap_usd") or 0),rr["score"],elite["score"],x["score"]); conf=max(0,min(100,round((100-rr["score"])*.35+pump["score"]*.25+elite["score"]*.20+gem["score"]*.20)))
    d={"emoji":"🔴","decision":"UZAK DUR","reason":"Rug riski çok yüksek"} if rr["score"]>=65 else ({"emoji":"🟢","decision":"GÜÇLÜ ADAY","reason":"Risk/potansiyel dengesi güçlü"} if elite["score"]>=80 and gem["score"]>=80 and x["score"]>=80 else ({"emoji":"🟡","decision":"İZLE","reason":"Aday güçlü ancak teyit gerekli"} if elite["score"]>=65 else {"emoji":"🔴","decision":"UZAK DUR","reason":"Risk/potansiyel dengesi yetersiz"}))
    return {"rug":rr,"pump":pump,"elite":elite,"gem":gem,"x100":x,"trade_plan":plan,"decision":d,"confidence":conf,"positives":rr["positives"],"warnings":rr["warnings"]}
