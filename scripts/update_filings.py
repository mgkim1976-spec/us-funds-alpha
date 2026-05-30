#!/usr/bin/env python3
"""일일 증분 공시 수집: 300펀드의 EDGAR에서 *새 NPORT-P만* 받아 holdings_panel_300에 추가.
펀드마다 공시일이 달라 새 filing이 거의 매 영업일 올라옴 → 매일 돌려 보유를 최신 공개분으로.
패널의 펀드별 max filingDate보다 새 것만 다운로드(증분). bulk 스키마와 동일 컬럼.
"""
import json, time, sys, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
import datetime as dt
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
UA="us_funds_alpha research your-email@example.com"; EQ={"EC","EP"}

def get(url,retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=40) as r:
                return r.read()
        except Exception:
            time.sleep(1.0*(i+1))
    return None
def lt(el): return el.tag.split('}')[-1]

def list_new(series, since):
    """series-level NPORT-P 중 filingDate>since 인 (accession, filingDate)."""
    out=[]
    data=get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series}"
             f"&type=NPORT-P&dateb=&owner=include&count=10&output=atom")
    if not data: return out
    try: root=ET.fromstring(data)
    except ET.ParseError: return out
    for e in root.iter():
        if lt(e)!="entry": continue
        acc=fd=None
        for c in e.iter():
            if lt(c)=="accession-number": acc=c.text
            if lt(c)=="filing-date": fd=c.text
        if acc and fd and fd>since: out.append((acc,fd))
    return out

def parse(xml_bytes):
    root=ET.fromstring(xml_bytes); rep=net=None
    for el in root.iter():
        t=lt(el)
        if t=="repPdDate" and rep is None: rep=(el.text or "").strip()
        elif t=="netAssets" and net is None:
            try: net=float((el.text or "").strip())
            except: net=None
    rows=[]
    for s in root.iter():
        if lt(s)!="invstOrSec": continue
        d={}; cusip=""; ctry=""
        for c in s:
            t=lt(c)
            if t=="cusip": cusip=(c.text or "").strip()
            elif t=="invCountry": ctry=(c.text or "").strip()
            else: d[t]=(c.text or "").strip()
        if d.get("assetCat") not in EQ: continue
        try: pv=float(d.get("pctVal","") or "nan")
        except: pv=float("nan")
        try: vu=float(d.get("valUSD","") or "nan")
        except: vu=float("nan")
        rows.append(dict(cusip=cusip,name=d.get("name",""),pctVal=pv,valUSD=vu,country=ctry))
    return rep,net,rows

def main():
    uni=json.load(open(ROOT/"data"/"universe_300.json"))
    panel=ROOT/"data"/"holdings_panel_300.parquet"
    df=pd.read_parquet(panel); df['filingDate']=pd.to_datetime(df['filingDate'])
    maxfd=df.groupby('fund')['filingDate'].max().to_dict()
    new_rows=[]; nnew=0
    for i,(tk,info) in enumerate(uni.items(),1):
        cik=info['cik']; series=info['seriesId']
        since=maxfd.get(tk)
        since_s=since.strftime("%Y-%m-%d") if pd.notna(since) else "2020-01-01"
        for acc,fd in list_new(series, since_s):
            accn=acc.replace("-","")
            xml=get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/primary_doc.xml")
            if not xml: continue
            try: rep,net,holds=parse(xml)
            except ET.ParseError: continue
            if not rep: continue
            for hh in holds:
                new_rows.append(dict(fund=tk,seriesId=series,reportDate=rep,filingDate=fd,
                                     netAssets=net,**hh))
            nnew+=1; print(f"  + {tk} {fd} (report {rep}) {len(holds)}행",flush=True)
            time.sleep(0.12)
        if i%50==0: print(f"  ...{i}/{len(uni)} 확인",flush=True)
        time.sleep(0.08)
    if new_rows:
        add=pd.DataFrame(new_rows)
        add['filingDate']=pd.to_datetime(add['filingDate']); add['reportDate']=pd.to_datetime(add['reportDate'])
        out=pd.concat([df,add],ignore_index=True).drop_duplicates(['fund','filingDate','cusip','valUSD'])
        out.to_parquet(panel,index=False)
        print(f"\n신규 filing {nnew}건, {len(new_rows)}행 추가 → 패널 {len(df)}→{len(out)}")
    else:
        print(f"\n신규 공시 없음 (패널 {len(df)}행 유지)")

if __name__=="__main__":
    main()
