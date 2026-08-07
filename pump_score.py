from typing import Any,Dict
def clamp(v,lo=0,hi=100): return int(max(lo,min(hi,round(v))))
def calculate_holder_metrics(top1,top5,top10):
    s=100.0
    if top10 is not None: s-=max(0,float(top10)-20)*1.6
    if top5 is not None: s-=max(0,float(top5)-15)*1.3
    if top1 is not None: s-=max(0,float(top1)-8)*2.2
    s=clamp(s); label="ÇOK İYİ" if s>=80 else "İYİ" if s>=65 else "ORTA" if s>=50 else "RİSKLİ"
    return {"score":s,"label":label}
def authority_status(rug):
    rug=rug or {}; return {"mint_open":bool(rug.get("mintAuthority")),"freeze_open":bool(rug.get("freezeAuthority"))}
def calculate_pump_score(token,rug):
    buys=int(token.get("buys_5m") or 0); sells=int(token.get("sells_5m") or 0); total=buys+sells
    br=buys/total if total else 0; liq=float(token.get("liquidity_usd") or 0); mc=float(token.get("market_cap_usd") or 0)
    v5=float(token.get("volume_5m") or 0); v1=float(token.get("volume_1h") or 0)
    m=min(35,total/8)+min(35,br*45)+(min(20,(v5/liq)*6) if liq else 0)+(min(10,(v5/v1)*60) if v1 else 0)
    ms=clamp(m); h=calculate_holder_metrics((rug or {}).get("top1"),(rug or {}).get("top5"),(rug or {}).get("top10"))
    p=.45*ms+.35*h["score"]+(12 if mc>0 and liq/mc>=.12 else 0)+(8 if br>=.6 else 0); ps=clamp(p)
    return {"score":ps,"label":"YÜKSEK" if ps>=80 else "ORTA" if ps>=55 else "DÜŞÜK","momentum_score":ms,"momentum":"GÜÇLÜ" if ms>=70 else "ORTA" if ms>=50 else "ZAYIF","holder_score":h["score"],"holder_label":h["label"]}
