def calculate_elite_score(rug_score,pump_score,momentum_score,holder_score,liquidity_usd):
    safety=max(0,100-int(rug_score)); s=round(safety*.30+int(pump_score)*.25+int(momentum_score)*.20+int(holder_score)*.20+min(100,float(liquidity_usd)/250)*.05); s=max(0,min(100,s))
    return {"score":s,"label":"ELITE" if s>=85 else "GÜÇLÜ" if s>=70 else "ORTA" if s>=55 else "RİSKLİ"}
