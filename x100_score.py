def calculate_x100_score(gem_score,elite_score,rug_score,market_cap,liquidity,momentum_score):
    s=gem_score*.35+elite_score*.25+momentum_score*.20+max(0,100-rug_score)*.20
    if 10000<=market_cap<=150000: s+=8
    if liquidity>=12000: s+=5
    s=max(0,min(100,round(s))); return {"score":s,"label":"ÇOK YÜKSEK" if s>=92 else "YÜKSEK" if s>=80 else "ORTA" if s>=60 else "ÇOK DÜŞÜK"}
