#!/usr/bin/env python3
"""Stage 1: survivorship 포함 액티브 US 주식형 마스터리스트.
N-CEN 6개 연도 스냅샷(2020-2025) union → SERIES_ID 중복제거(폐지펀드 포함).
N-CEN 플래그로 체계적 필터(인덱스·MMF·타깃데이트·FoF·inverse 제거).
주식/US는 N-CEN에 플래그 없어 이름기반 후보분류(Stage 2서 N-PORT EC%로 확정).
출력: data/universe_master.parquet
"""
import zipfile, io, csv, json, re
from pathlib import Path
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parent.parent; NCEN=ROOT/"data"/"raw"/"ncen"

COLS=["SERIES_ID","FUND_NAME","IS_INDEX","IS_MULTI_INVERSE_INDEX","IS_MONEY_MARKET",
      "IS_TARGET_DATE","IS_FUND_OF_FUND","IS_ETF","IS_INTERVAL","IS_NON_DIVERSIFIED",
      "MONTHLY_AVG_NET_ASSETS","RETURN_AFTR_FEES_AND_EXPENSES"]

def load_ncen():
    rows=[]
    for zf in sorted(NCEN.glob("*_ncen.zip")):
        yr=zf.name[:4]
        with zipfile.ZipFile(zf) as z:
            with z.open("FUND_REPORTED_INFO.tsv") as f:
                rd=csv.DictReader(io.TextIOWrapper(f,'utf-8'),delimiter='\t')
                for r in rd:
                    d={c:r.get(c,"") for c in COLS}; d["src_year"]=yr
                    rows.append(d)
    return pd.DataFrame(rows)

# 이름기반 주식/US 분류 (Stage1 후보 — N-PORT로 확정 예정)
BOND=(r"(bond|fixed.income|treasur|municipal|\bmuni\b|govt|government|credit|high.?yield|"
      r"floating.rate|duration|\btips\b|inflation.protected|mortgage|securitized|ginnie|gnma|"
      r"aggregate|interest.rate|senior.loan|bank.loan|investment.grade|short.?term|"
      r"intermediate.?term|long.?term|core.?plus|core.bond|strategic.income|income.opportunit|"
      r"total.return.bond|ultra.short|limited.term|agency|real.return|multi.?sector|preferred.securit|"
      r"tax.free|tax.exempt|tax.managed.bond)")
MMF=r"(money.market|cash.reserve|liquid(ity)?.fund|prime.fund)"
ALLOC=r"(balanced|allocation|target|retirement.\d|20[1-7]\d.fund|multi.?asset|lifestyle|lifecycle|conservative|moderate)"
INTL=(r"(international|\bintl\b|global|world|emerging|\bem\b|europ|asia|pacific|japan|china|india|"
      r"latin|overseas|foreign|ex.?us|developed.market|frontier|greater.|\beuro\b|brazil|korea|taiwan)")
SECTOR=r"(health.?care|biotech|technology|\btech\b|energy|financ|real.estate|\breit\b|utilit|gold|natural.resource|infrastructure|semiconductor|materials)"

def classify(name):
    n=(name or "").lower()
    return (bool(re.search(BOND,n)) or bool(re.search(MMF,n)),
            bool(re.search(ALLOC,n)),
            bool(re.search(INTL,n)),
            bool(re.search(SECTOR,n)))

def main():
    df=load_ncen()
    print(f"N-CEN 원행(펀드-연도): {len(df)}")
    df["MONTHLY_AVG_NET_ASSETS"]=pd.to_numeric(df["MONTHLY_AVG_NET_ASSETS"],errors='coerce')
    # SERIES_ID 단위 집계 (survivorship union)
    def yes(s): return (s=="Y").any()
    g=df[df.SERIES_ID.str.startswith("S",na=False)].groupby("SERIES_ID")
    m=pd.DataFrame({
        "name": g["FUND_NAME"].last(),
        "is_index": g["IS_INDEX"].apply(yes),
        "is_inverse": g["IS_MULTI_INVERSE_INDEX"].apply(yes),
        "is_mmf": g["IS_MONEY_MARKET"].apply(yes),
        "is_target": g["IS_TARGET_DATE"].apply(yes),
        "is_fof": g["IS_FUND_OF_FUND"].apply(yes),
        "is_etf": g["IS_ETF"].apply(yes),
        "aum_avg": g["MONTHLY_AVG_NET_ASSETS"].max()/1e9,   # peak AUM($B)
        "first_yr": g["src_year"].min(), "last_yr": g["src_year"].max(),
        "n_yrs": g["src_year"].nunique(),
    }).reset_index()
    n0=len(m); print(f"고유 SERIES_ID: {n0}")

    funnel=[("전체 series",n0)]
    m=m[~m.is_index];      funnel.append(("− 인덱스",len(m)))
    m=m[~m.is_inverse];    funnel.append(("− inverse/leveraged",len(m)))
    m=m[~m.is_mmf];        funnel.append(("− MMF",len(m)))
    m=m[~m.is_target];     funnel.append(("− 타깃데이트",len(m)))
    m=m[~m.is_fof];        funnel.append(("− fund-of-funds",len(m)))
    # 이름기반 주식/US
    cl=m["name"].apply(classify)
    m["nm_bond"]=[c[0] for c in cl]; m["nm_alloc"]=[c[1] for c in cl]
    m["nm_intl"]=[c[2] for c in cl]; m["nm_sector"]=[c[3] for c in cl]
    m=m[~m.nm_bond];       funnel.append(("− 이름상 채권/MMF",len(m)))
    m=m[~m.nm_alloc];      funnel.append(("− 이름상 밸런스/타깃",len(m)))
    us=m[~m.nm_intl];      funnel.append(("− 이름상 해외(=US후보)",len(us)))
    # 섹터펀드는 플래그만(다양성 위해 보존, 분산형과 구분)
    funnel.append(("  (그중 섹터펀드 플래그)", int(us.nm_sector.sum())))

    # 티커 조인 (company_tickers_mf)
    mf=json.load(open(ROOT/"data"/"raw"/"mf_tickers.json"))
    idx={c:i for i,c in enumerate(mf["fields"])}
    tk={}
    for r in mf["data"]:
        tk.setdefault(r[idx["seriesId"]], r[idx["symbol"]])
    us=us.copy(); us["ticker"]=us["SERIES_ID"].map(tk)
    us["alive_now"]=us["SERIES_ID"].isin(tk)     # 현 ticker파일에 없으면 폐지/기관 추정

    us.to_parquet(ROOT/"data"/"universe_master.parquet",index=False)

    print("\n=== 필터 퍼널 ===")
    for k,v in funnel: print(f"  {k:28} {v:>6}")
    print(f"\n=== US 액티브 주식형 후보: {len(us)} ===")
    print(f"  현 ticker 보유(생존추정): {us.alive_now.sum()} | 미보유(폐지/기관 추정): {(~us.alive_now).sum()}")
    print(f"  → survivorship 커버리지: 폐지/구펀드 {(~us.alive_now).sum()}개 포함")
    print(f"  ETF 포함: {us.is_etf.sum()}개")
    print("\n  AUM($B) 분포:", us["aum_avg"].describe()[["min","25%","50%","75%","max"]].round(2).to_dict())
    for lo,hi,lab in [(0,0.2,"<0.2"),(0.2,1,"0.2-1"),(1,5,"1-5"),(5,20,"5-20"),(20,1e9,">20")]:
        print(f"    AUM {lab:>6}$B: {((us.aum_avg>=lo)&(us.aum_avg<hi)).sum()}")
    print("\n  AUM 상위 12 후보:")
    for _,r in us.nlargest(12,"aum_avg").iterrows():
        print(f"    {r['SERIES_ID']} {str(r['ticker'] or '-'):7} ${r['aum_avg']:6.1f}B  {r['name'][:42]}")

if __name__=="__main__":
    main()
