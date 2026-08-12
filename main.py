import os, json, time, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSION='HUNTERELITE CREATOR HUNTER V2.2 LIVE-ONLY'
TOKEN=os.getenv('TOKEN','').strip()
SIGNAL_CHAT_ID=os.getenv('SIGNAL_CHAT_ID','').strip()
RPC=os.getenv('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com').strip()
SCAN=max(3,int(os.getenv('CREATOR_SCAN_SECONDS','5')))
DISCOVERY=max(20,int(os.getenv('DISCOVERY_SCAN_SECONDS','45')))
PROMOTE_MC=float(os.getenv('CREATOR_PROMOTE_MC','250000'))
STATE=Path(os.getenv('CREATOR_STATE_FILE','creator_hunter_state.json'))
PUMP_PROGRAM='6EF8rrecthR5DkR3dcoHj3hT9Yp5fYpJ2d7G7F6P'  # log/account hint only; create detection also uses mint suffix/logs
SEEDS={
 '5YRgrP3mjGzrzirYYN5HAQH19cTYREYwGxW6XRJQUzij':{'label':'TOAD creator','source':'A13oRB9FFaiUjfi6LdCg6p9ka1u8SfGkUFs4SKvPpump'},
 '7VPJHsm1bqMDd1ZCKRQyjv9bduPpEwpNmCmiikBBHs9F':{'label':'Creator #2','source':'CX2v7JSHJQDcNooubzzvZG8TPaDwbaPgfzcXRSWJpump'},
 'yHCxHBEaJW5tbndqC8JciSThr7U1cqLpdcsvHcx6PRe':{'label':'Creator #3','source':'9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump'},
}
extra=[x.strip() for x in os.getenv('CREATOR_WALLETS','').split(',') if x.strip()]
for w in extra: SEEDS.setdefault(w,{'label':'ENV creator','source':'manual'})
lock=threading.Lock(); state={'creators':{},'seen_sigs':{},'candidates':{},'alerts':[]}
STARTED_AT=int(time.time())

def load():
 global state
 try:
  if STATE.exists(): state.update(json.loads(STATE.read_text()))
 except Exception as e: print('STATE LOAD',repr(e),flush=True)
 for w,m in SEEDS.items(): state['creators'].setdefault(w,{**m,'added':int(time.time()),'wins':1})

def save():
 try:
  tmp=STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(state,ensure_ascii=False)); tmp.replace(STATE)
 except Exception as e: print('STATE SAVE',repr(e),flush=True)

def http_json(url,method='GET',payload=None,timeout=15):
 data=None; headers={'User-Agent':'HunterEliteCreator/1.0','Content-Type':'application/json'}
 if payload is not None: data=json.dumps(payload).encode()
 req=urllib.request.Request(url,data=data,headers=headers,method=method)
 with urllib.request.urlopen(req,timeout=timeout) as r: return json.loads(r.read().decode())

def rpc(method,params):
 x=http_json(RPC,'POST',{'jsonrpc':'2.0','id':1,'method':method,'params':params},20)
 if x.get('error'): raise RuntimeError(x['error'])
 return x.get('result')

def tg(text, reply_markup=None):
 if not TOKEN or not SIGNAL_CHAT_ID: print(text,flush=True); return
 url=f'https://api.telegram.org/bot{TOKEN}/sendMessage'
 body={'chat_id':SIGNAL_CHAT_ID,'text':text[:4000],'disable_web_page_preview':True}
 if reply_markup is not None: body['reply_markup']=reply_markup
 http_json(url,'POST',body,15)

def send_creator_alert(meta, wallet, mint):
 # 1) Short alert. Keep CA out of the crowded detail block.
 tg(f"🚨 CREATOR YENI TOKEN CIKARDI\n\nCreator: {meta.get('label','TRACKED')}\nWallet: {wallet}\nDetected: ON-CHAIN / NEW CREATE\nScan: {SCAN}s")
 # 2) CA-only message: long-press -> Copy works cleanly on mobile.
 tg(mint)
 # 3) One-tap actions. Telegram Bot API copy_text button copies the exact CA.
 axiom=f"https://axiom.trade/t/{mint}/@215162?chain=sol"
 markup={'inline_keyboard':[[
   {'text':'📋 CA KOPYALA','copy_text':{'text':mint}},
   {'text':"🚀 AXIOM'DA AC",'url':axiom}
 ]]}
 tg('⚡ ANLIK CREATOR ALARMI', markup)

def sigs(addr,limit=12): return rpc('getSignaturesForAddress',[addr,{'limit':limit,'commitment':'confirmed'}]) or []
def tx(sig): return rpc('getTransaction',[sig,{'encoding':'jsonParsed','maxSupportedTransactionVersion':0,'commitment':'confirmed'}])

def account_keys(t):
 try:
  ks=t['transaction']['message']['accountKeys']; out=[]
  for k in ks: out.append(k.get('pubkey') if isinstance(k,dict) else k)
  return [x for x in out if x]
 except: return []

def signer_keys(t):
 try:
  return [k.get('pubkey') for k in t['transaction']['message']['accountKeys'] if isinstance(k,dict) and k.get('signer')]
 except: return []

def pump_create_info(t, creator=None):
 if not t: return None
 logs=((t.get('meta') or {}).get('logMessages') or [])
 txt='\n'.join(logs).lower(); keys=account_keys(t)
 # Pump create txs normally expose Create/CreateV2 in logs and a mint ending in pump.
 create=('instruction: create' in txt or 'createv2' in txt or 'program log: create' in txt)
 mints=[]
 for b in ((t.get('meta') or {}).get('postTokenBalances') or []):
  m=b.get('mint');
  if m and m not in mints: mints.append(m)
 for k in keys:
  if isinstance(k,str) and k.endswith('pump') and k not in mints: mints.append(k)
 if not create and not mints: return None
 mint=next((m for m in mints if m.endswith('pump')), mints[0] if mints else None)
 if not mint: return None
 signers=signer_keys(t); owner=creator if creator in signers else (signers[0] if signers else creator)
 return {'mint':mint,'creator':owner,'logs':txt}

def bootstrap_creator(w):
 arr=sigs(w,5)
 if arr: state['seen_sigs'][w]=arr[0]['signature']

def watch_creators():
 # LIVE-ONLY baseline: ALWAYS reset each creator to its newest signature at process start.
 # This deliberately ignores every historical transaction, including stale state from V2/V2.1.
 for w in list(state['creators']):
  try:
   bootstrap_creator(w)
   print('BASELINE', w, state['seen_sigs'].get(w,'NONE'), flush=True)
  except Exception as e:
   print('BOOT',w,repr(e),flush=True)
 save()
 while True:
  for w,meta in list(state['creators'].items()):
   try:
    arr=sigs(w,15); last=state['seen_sigs'].get(w)
    # If RPC had no baseline, establish one silently. Never backfill.
    if not last:
     if arr: state['seen_sigs'][w]=arr[0]['signature']; save()
     continue
    fresh=[]
    found_baseline=False
    for s in arr:
     if s['signature']==last:
      found_baseline=True
      break
     fresh.append(s)
    # If baseline fell outside the window, do NOT treat the page as new history.
    # Re-baseline silently to newest and wait for the next truly new signature.
    if arr and not found_baseline:
     state['seen_sigs'][w]=arr[0]['signature']; save()
     print('REBASELINE',w,'history skipped',flush=True)
     continue
    if arr: state['seen_sigs'][w]=arr[0]['signature']
    for s in reversed(fresh):
     if s.get('err') is not None: continue
     # Signature must itself be newer than this process startup.
     bt=int(s.get('blockTime') or 0)
     if bt and bt < STARTED_AT-10: continue
     t=tx(s['signature'])
     tx_bt=int((t or {}).get('blockTime') or bt or 0)
     if tx_bt and tx_bt < STARTED_AT-10: continue
     info=pump_create_info(t,w)
     if info:
      mint=info['mint']
      # Never announce the known source/winner token as a new launch.
      if mint == meta.get('source'): continue
      key=w+':'+mint
      if key in state['alerts']: continue
      state['alerts'].append(key); state['alerts']=state['alerts'][-500:]
      send_creator_alert(meta, w, mint)
      print('LIVE ALERT',w,mint,flush=True)
    save()
   except Exception as e: print('WATCH ERROR',w,repr(e),flush=True)
   time.sleep(0.7)
  time.sleep(SCAN)

def dex_profiles():
 try:
  x=http_json('https://api.dexscreener.com/token-profiles/latest/v1',timeout=15)
  return x if isinstance(x,list) else []
 except Exception as e: print('DEX PROFILE',repr(e),flush=True); return []
def dex_pair(mint):
 try:
  x=http_json('https://api.dexscreener.com/latest/dex/tokens/'+mint,timeout=15)
  ps=[p for p in (x.get('pairs') or []) if p.get('chainId')=='solana']
  return max(ps,key=lambda p:float(((p.get('liquidity') or {}).get('usd') or 0))) if ps else None
 except: return None

def find_creator_from_mint(mint):
 try:
  arr=sigs(mint,100)
  # API is newest first; creation is usually among oldest available for young Pump tokens.
  for s in reversed(arr):
   if s.get('err') is not None: continue
   t=tx(s['signature']); info=pump_create_info(t)
   if info and info.get('creator'): return info['creator']
 except Exception as e: print('CREATOR FIND',mint,repr(e),flush=True)
 return None

def discovery():
 # Prospectively learn creators: observe fresh Pump tokens, remember creator, promote creator
 # automatically if an observed token later reaches PROMOTE_MC.
 while True:
  try:
   now=int(time.time())
   for p in dex_profiles()[:100]:
    if p.get('chainId')!='solana': continue
    mint=p.get('tokenAddress') or ''
    if not mint.endswith('pump'): continue
    c=state['candidates'].get(mint)
    pair=dex_pair(mint)
    if not pair: continue
    mc=float(pair.get('marketCap') or pair.get('fdv') or 0)
    if not c:
     creator=find_creator_from_mint(mint)
     if creator: state['candidates'][mint]={'creator':creator,'first_mc':mc,'peak_mc':mc,'first_seen':now}
    else:
     c['peak_mc']=max(float(c.get('peak_mc',0)),mc)
     creator=c.get('creator')
     if creator and c['peak_mc']>=PROMOTE_MC and creator not in state['creators']:
      state['creators'][creator]={'label':'AUTO WINNER','source':mint,'added':now,'wins':1,'peak_mc':c['peak_mc']}
      bootstrap_creator(creator)
      tg(f"🏆 CREATOR AUTO-ADDED\n\nWallet: {creator}\nWinning CA: {mint}\nObserved peak MC: ${c['peak_mc']:,.0f}\n\nNow watching this creator for the next launch.")
   # prune candidates after 7 days
   state['candidates']={m:c for m,c in state['candidates'].items() if now-int(c.get('first_seen',now))<604800}
   save()
  except Exception as e: print('DISCOVERY ERROR',repr(e),flush=True)
  time.sleep(DISCOVERY)

class H(BaseHTTPRequestHandler):
 def do_GET(self):
  b=json.dumps({'ok':True,'version':VERSION,'creators':len(state['creators']),'candidates':len(state['candidates'])}).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b)
 def log_message(self,*a): pass

def health():
 try: HTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),H).serve_forever()
 except Exception as e: print('HEALTH',repr(e),flush=True)

if __name__=='__main__':
 load(); threading.Thread(target=health,daemon=True).start()
 print(VERSION,'ONLINE',flush=True); print('TRACKED CREATORS:',len(state['creators']),'PROMOTE_MC:',PROMOTE_MC,flush=True)
 tg(f"🦅 {VERSION} ONLINE\nTracked creators: {len(state['creators'])}\nCreator launch alerts: ACTIVE\nRug/holder entry gate: OFF FOR CREATOR ALERTS\nAuto-discovery: ACTIVE\nCreator scan: {SCAN}s")
 threading.Thread(target=discovery,daemon=True).start(); watch_creators()
