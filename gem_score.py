def calculate_gem_score(elite_score,pump_score,rug_score,market_cap,age_minutes):
    s=elite_score*.45+pump_score*.30+max(0,100-rug_score)*.25
    if 15000<=market_cap<=250000: s+=7
    if age_minutes is not None and 2<=age_minutes<=180: s+=5
    s=max(0,min(100,round(s))); return {"score":s,"label":"GEM" if s>=85 else "GÜÇLÜ" if s>=70 else "İZLE" if s>=55 else "ELE"}
