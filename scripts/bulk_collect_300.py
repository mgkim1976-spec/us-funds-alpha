#!/usr/bin/env python3
"""300펀드 보유를 N-PORT 벌크로 수집(개별 스크래핑 대체, 훨씬 빠름).
연속 분기 zip 다운→300펀드 accession만 스트리밍 추출(EC/EP)→삭제. point-in-time(FILING_DATE).
출력: data/holdings_panel_300.parquet
"""
import zipfile, io, csv, json, urllib.request, time, os
from pathlib import Path
import pandas as pd, datetime as dt
ROOT=Path(__file__).resolve().parent.parent; UA="us_funds_alpha research your-email@example.com"
EQ={"EC","EP"}
QUARTERS=[f"{y}q{q}" for (y,q) in
          [(2022,4),(2023,1),(2023,2),(2023,3),(2023,4),(2024,1),(2024,2),(2024,3),(2024,4),
           (2025,1),(2025,2),(2025,3),(2025,4),(2026,1)]]

def dl(q):
    url=f"https://www.sec.gov/files/dera/data/form-n-port-data-sets/{q}_nport.zip"
    tmp=ROOT/"data"/"raw"/"nport_bulk"/f"_tmp_{q}.zip"
    if (ROOT/"data"/"raw"/"nport_bulk"/f"{q}_nport.zip").exists():
        return ROOT/"data"/"raw"/"nport_bulk"/f"{q}_nport.zip", False
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=300) as r, open(tmp,'wb') as f:
        while True:
            b=r.read(1<<20)
            if not b: break
            f.write(b)
    return tmp, True

def main():
    import sys
    uni_name=sys.argv[1] if len(sys.argv)>1 else "universe_300.json"
    out_name=sys.argv[2] if len(sys.argv)>2 else "holdings_panel_300.parquet"
    uni=json.load(open(ROOT/"data"/uni_name))
    ser2tk={v["seriesId"]:k for k,v in uni.items()}
    want=set(ser2tk)
    print(f"대상 {len(want)} series, {len(QUARTERS)} 분기",flush=True)
    rows=[]
    for q in QUARTERS:
        try: zp,temp=dl(q)
        except Exception as e: print(f"  ! {q} dl 실패 {e}",flush=True); continue
        z=zipfile.ZipFile(zp)
        # SUBMISSION: acc→(filing,report)
        sub={}
        with z.open("SUBMISSION.tsv") as f:
            rd=csv.DictReader(io.TextIOWrapper(f,'utf-8'),delimiter='\t')
            for r in rd: sub[r["ACCESSION_NUMBER"]]=(r.get("FILING_DATE"),r.get("REPORT_DATE"))
        # INFO: acc→(series,net) for 대상
        acc2=dict()
        with z.open("FUND_REPORTED_INFO.tsv") as f:
            rd=csv.DictReader(io.TextIOWrapper(f,'utf-8'),delimiter='\t')
            for r in rd:
                sid=r.get("SERIES_ID","")
                if sid in want:
                    try: net=float(r.get("NET_ASSETS") or "nan")
                    except: net=float("nan")
                    acc2[r["ACCESSION_NUMBER"]]=(sid,net)
        # HOLDING stream
        n=0
        with z.open("FUND_REPORTED_HOLDING.tsv") as f:
            tw=io.TextIOWrapper(f,'utf-8'); hdr=tw.readline().rstrip("\n").split("\t")
            iA=hdr.index("ACCESSION_NUMBER");iV=hdr.index("CURRENCY_VALUE");iC=hdr.index("ASSET_CAT")
            iK=hdr.index("INVESTMENT_COUNTRY");iU=hdr.index("ISSUER_CUSIP");iN=hdr.index("ISSUER_NAME")
            for line in tw:
                p=line.rstrip("\n").split("\t"); acc=p[iA]
                if acc not in acc2 or p[iC] not in EQ: continue
                sid,net=acc2[acc]
                try: v=float(p[iV])
                except: continue
                fd,rd_=sub.get(acc,(None,None))
                rows.append((ser2tk[sid],sid,rd_,fd,net,p[iU],p[iN],
                             (v/net*100) if net and net==net and net>0 else float('nan'),v,p[iK]))
                n+=1
        print(f"  {q}: 대상filing {len(acc2)} 보유행 {n}",flush=True)
        z.close()
        if temp: os.remove(zp)
    df=pd.DataFrame(rows,columns=["fund","seriesId","reportDate","filingDate","netAssets",
                                  "cusip","name","pctVal","valUSD","country"])
    df["filingDate"]=pd.to_datetime(df["filingDate"],errors='coerce')
    df["reportDate"]=pd.to_datetime(df["reportDate"],errors='coerce')
    df.to_parquet(ROOT/"data"/out_name,index=False)
    print(f"\n저장 {df.shape} | 펀드 {df['fund'].nunique()} | 분기 {df['reportDate'].nunique()} "
          f"| {df['reportDate'].min()}~{df['reportDate'].max()}",flush=True)

if __name__=="__main__":
    main()
