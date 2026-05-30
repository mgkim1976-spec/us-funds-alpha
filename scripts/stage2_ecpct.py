#!/usr/bin/env python3
"""Stage 2: N-PORT 벌크로 947후보의 EC%(주식비중)·US%(미국주식비중) authoritative 산출.
851MB 보유테이블 스트리밍 → 후보 accession만 누적. CURRENCY_VALUE/NET_ASSETS 기준.
확정: EC%≥80% & 미국주식/주식≥70% = 진짜 액티브 US 주식형.
출력: data/universe_confirmed.parquet
"""
import zipfile, io, csv
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
ZIP=ROOT/"data"/"raw"/"nport_bulk"/"2024q4_nport.zip"
EQ={"EC","EP"}

def main():
    master=pd.read_parquet(ROOT/"data"/"universe_master.parquet")
    cand=set(master["SERIES_ID"])
    z=zipfile.ZipFile(ZIP)
    # 1) accession → series, net_assets (후보만)
    acc2ser={}; net={}
    with z.open("FUND_REPORTED_INFO.tsv") as f:
        rd=csv.DictReader(io.TextIOWrapper(f,'utf-8'),delimiter='\t')
        for r in rd:
            sid=r.get("SERIES_ID","")
            if sid in cand:
                acc=r["ACCESSION_NUMBER"]; acc2ser[acc]=sid
                try: net[acc]=float(r.get("NET_ASSETS") or "nan")
                except: net[acc]=float("nan")
    print(f"후보 {len(cand)} 중 2024q4 N-PORT 제출: {len(acc2ser)}")
    # 2) 보유테이블 스트리밍 누적
    ec=dict.fromkeys(acc2ser,0.0); usec=dict.fromkeys(acc2ser,0.0); tot=dict.fromkeys(acc2ser,0.0)
    with z.open("FUND_REPORTED_HOLDING.tsv") as f:
        tw=io.TextIOWrapper(f,'utf-8'); hdr=tw.readline().rstrip("\n").split("\t")
        iA=hdr.index("ACCESSION_NUMBER"); iV=hdr.index("CURRENCY_VALUE")
        iC=hdr.index("ASSET_CAT"); iK=hdr.index("INVESTMENT_COUNTRY")
        n=0
        for line in tw:
            n+=1
            p=line.rstrip("\n").split("\t")
            acc=p[iA]
            if acc not in ec: continue
            try: v=float(p[iV])
            except: continue
            tot[acc]+=v
            if p[iC] in EQ:
                ec[acc]+=v
                if p[iK]=="US": usec[acc]+=v
            if n%2000000==0: print(f"  ...{n//1000000}M행",flush=True)
    print(f"보유행 총 {n}")
    # 3) 펀드별 비율
    rows=[]
    for acc,sid in acc2ser.items():
        na=net.get(acc,float("nan"))
        denom=na if (na and na==na and na>0) else tot[acc]
        if not denom: continue
        ecp=ec[acc]/denom; usq=(usec[acc]/ec[acc]) if ec[acc]>0 else 0.0
        rows.append(dict(SERIES_ID=sid, ec_pct=ecp, us_share_of_eq=usq,
                         us_eq_pct=usec[acc]/denom))
    cls=pd.DataFrame(rows)
    out=master.merge(cls,on="SERIES_ID",how="left")
    out["in_2024q4"]=out["SERIES_ID"].isin(set(acc2ser.values()))
    out["confirmed_us_eq"]=(out["ec_pct"]>=0.80)&(out["us_share_of_eq"]>=0.70)
    out.to_parquet(ROOT/"data"/"universe_confirmed.parquet",index=False)

    sub=out[out.in_2024q4]
    print(f"\n=== EC% 확정 결과 (2024q4 제출 {len(sub)}개 기준) ===")
    print(f"  EC%≥80% & US주식≥70% (확정 US주식형): {out.confirmed_us_eq.sum()}")
    print(f"  이름통과했으나 EC%<80% (채권/혼합 false positive): {(sub.ec_pct<0.80).sum()}")
    print(f"  이름통과했으나 US주식<70% (해외 false positive): {((sub.ec_pct>=0.80)&(sub.us_share_of_eq<0.70)).sum()}")
    print("\n  EC% 분포:", sub["ec_pct"].describe()[["min","25%","50%","75%","max"]].round(2).to_dict())
    print("\n  이름필터는 통과했으나 EC%<50%인 누수 샘플(채권):")
    leak=sub[sub.ec_pct<0.5].nlargest(8,"aum_avg")
    for _,r in leak.iterrows():
        print(f"    {str(r['ticker'] or '-'):7} EC%={r['ec_pct']*100:4.0f}% US={r['us_share_of_eq']*100:3.0f}%  {r['name'][:40]}")
    print("\n  확정 US주식형 AUM 상위 10:")
    for _,r in out[out.confirmed_us_eq].nlargest(10,"aum_avg").iterrows():
        print(f"    {str(r['ticker'] or '-'):7} ${r['aum_avg']:6.1f}B EC%={r['ec_pct']*100:3.0f}% US={r['us_share_of_eq']*100:3.0f}%  {r['name'][:36]}")
    # 확정셋 AUM 층화
    c=out[out.confirmed_us_eq]
    print(f"\n  확정셋 {len(c)}개 AUM 층화:")
    for lo,hi,lab in [(0,0.2,"<0.2"),(0.2,1,"0.2-1"),(1,5,"1-5"),(5,20,"5-20"),(20,1e9,">20")]:
        print(f"    {lab:>6}$B: {((c.aum_avg>=lo)&(c.aum_avg<hi)).sum()}")

if __name__=="__main__":
    main()
