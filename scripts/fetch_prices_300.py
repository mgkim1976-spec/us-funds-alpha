#!/usr/bin/env python3
"""300펀드 보유의 미가격 cusip(소형주 꼬리) 매핑+수집 → prices_full.parquet에 append."""
import json, time, urllib.request
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent; RAW=ROOT/"data"/"raw"; UA="us_funds_alpha research your-email@example.com"

def openfigi(cusips):
    cache=json.load(open(RAW/"figi_map.json"))
    todo=[c for c in cusips if c not in cache]
    print(f"figi 신규 {len(todo)}",flush=True)
    for i in range(0,len(todo),10):
        b=todo[i:i+10]
        body=json.dumps([{"idType":"ID_CUSIP","idValue":c} for c in b]).encode()
        try:
            res=json.load(urllib.request.urlopen(urllib.request.Request("https://api.openfigi.com/v3/mapping",
                data=body,headers={"Content-Type":"application/json","User-Agent":UA}),timeout=30))
            for c,r in zip(b,res):
                tk=None
                if "data" in r:
                    us=[d for d in r["data"] if d.get("exchCode")=="US" and d.get("securityType2")=="Common Stock"]
                    pool=us or [d for d in r["data"] if d.get("exchCode")=="US"]
                    if pool: tk=pool[0].get("ticker")
                cache[c]=tk
        except Exception as e: print(f"  !figi {i}: {e}",flush=True); time.sleep(5); continue
        if i%300==0: json.dump(cache,open(RAW/"figi_map.json","w")); print(f"  figi {i}/{len(todo)}",flush=True)
        time.sleep(2.6)
    json.dump(cache,open(RAW/"figi_map.json","w")); return cache

def yahoo(tickers):
    s=int(pd.Timestamp("2019-12-01").timestamp()); e=int(pd.Timestamp("2026-05-29").timestamp())
    rows=[]
    for i,tk in enumerate(sorted(set(tickers)),1):
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1={s}&period2={e}&interval=1d"
        try:
            j=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=25))
            r=j["chart"]["result"][0]; ts=r["timestamp"]
            adj=r["indicators"].get("adjclose",[{}])[0].get("adjclose") or r["indicators"]["quote"][0]["close"]
            for t,p in zip(ts,adj):
                if p is not None: rows.append((tk,pd.Timestamp(t,unit='s').normalize(),float(p)))
        except Exception: pass
        if i%200==0: print(f"  px {i}/{len(set(tickers))}",flush=True)
        time.sleep(0.22)
    return pd.DataFrame(rows,columns=["ticker","date","adjclose"])

def main():
    d=pd.read_parquet(ROOT/"data"/"holdings_panel_300.parquet")
    cus=sorted(d[d.cusip.str.len()==9]["cusip"].unique())
    figi=openfigi(cus)
    want=set(figi[c] for c in cus if figi.get(c))
    px=pd.read_parquet(ROOT/"data"/"prices_full.parquet"); px['date']=pd.to_datetime(px['date'])
    have=set(px['ticker'].unique())
    new=[t for t in want if t not in have]
    print(f"신규 가격 수집 티커: {len(new)}",flush=True)
    add=yahoo(new)
    out=pd.concat([px,add],ignore_index=True).drop_duplicates(['ticker','date'])
    out.to_parquet(ROOT/"data"/"prices_full.parquet",index=False)
    print(f"prices_full 갱신 {out.shape} 티커 {out['ticker'].nunique()}",flush=True)

if __name__=="__main__":
    main()
