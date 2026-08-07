def build_trade_plan(market_cap,rug_score,elite_score,x100_score):
    mc=float(market_cap or 0); ok=mc>0 and rug_score<=35 and elite_score>=70 and x100_score>=72
    if not ok: return {"status":"GİRİŞ ÖNERİLMİYOR","entry_low":0.0,"entry_high":0.0,"stop":0.0,"tp1":0.0,"tp2":0.0,"tp3":0.0}
    return {"status":"GÜÇLÜ GİRİŞ ADAYI","entry_low":mc*.94,"entry_high":mc*1.03,"stop":mc*.82,"tp1":mc*1.8,"tp2":mc*3,"tp3":mc*5}
