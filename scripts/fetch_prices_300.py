import os
#!/usr/bin/env python3
"""300펀드 보유의 미가격 cusip(소형주 꼬리) 매핑+수집 → prices_full.parquet에 append."""
import sys, json, time, urllib.request
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent; RAW=ROOT/"data"/"raw"; UA = os.environ.get("SEC_USER_AGENT", "us_funds_alpha research your-email@example.com")
sys.path.insert(0, str(Path(__file__).resolve().parent)); import falib as fa

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
    end=pd.Timestamp.today().normalize()+pd.Timedelta(days=1); rows=[]
    for i,tk in enumerate(sorted(set(tickers)),1):
        for d,p in fa.yahoo_chart(tk,"2019-12-01",end):   # '/'→'-' 변환은 fa 내부; 저장은 원본 tk
            rows.append((tk,d.normalize(),p))
        if i%200==0: print(f"  px {i}/{len(set(tickers))}",flush=True)
        time.sleep(0.22)
    return pd.DataFrame(rows,columns=["ticker","date","adjclose"])

def main():
    import sys
    panel=sys.argv[1] if len(sys.argv)>1 else "holdings_panel_300.parquet"
    d=pd.read_parquet(ROOT/"data"/panel)
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
