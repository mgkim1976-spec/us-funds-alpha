#!/usr/bin/env python3
"""확대 Phase 1: 확정 US주식형 NAV 수집 → 스타일 분류 → §12 PCA 재검증 → 균형 300 선별.
§12 헤드라인: universe 확대로 잔차 독립차원이 늘었나(원래 PC1=54%, 그로쓰 편중).
출력: data/fund_nav_full.parquet, data/universe_300.json, notes/expand_pca.md
"""
import re, json, time, urllib.request
from pathlib import Path
import numpy as np, pandas as pd
import statsmodels.api as sm
ROOT=Path(__file__).resolve().parent.parent; RAW=ROOT/"data"/"raw"
FACS=["Mkt-RF","SMB","HML","RMW","CMA","Mom"]

def parse_ff(path,cols):
    rows=[]
    for ln in Path(path).read_text().splitlines():
        m=re.match(r'^\s*(\d{6})\s*,(.*)$',ln)
        if not m: continue
        v=[float(x) for x in m.group(2).split(',')]
        if len(v)==len(cols): rows.append([m.group(1)]+v)
    return pd.DataFrame(rows,columns=["ym"]+cols).set_index("ym")/100.0

def fetch_nav(tickers):
    cache=ROOT/"data"/"fund_nav_full.parquet"
    have=pd.read_parquet(cache) if cache.exists() else pd.DataFrame(columns=["fund","ym","nav"])
    done=set(have["fund"].unique()); todo=[t for t in tickers if t not in done]
    print(f"NAV: 캐시 {len(done)} / 신규 {len(todo)}",flush=True)
    s=int(pd.Timestamp("2014-12-01").timestamp()); e=int(pd.Timestamp("2026-04-01").timestamp())
    rows=[]
    for i,tk in enumerate(todo,1):
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1={s}&period2={e}&interval=1mo"
        try:
            j=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=20))
            r=j["chart"]["result"][0]; ts=r["timestamp"]
            adj=r["indicators"].get("adjclose",[{}])[0].get("adjclose") or r["indicators"]["quote"][0]["close"]
            for t,p in zip(ts,adj):
                if p: rows.append((tk,pd.Timestamp(t,unit='s').strftime('%Y%m'),float(p)))
        except Exception: pass
        if i%100==0: print(f"  nav {i}/{len(todo)}",flush=True)
        time.sleep(0.2)
    out=pd.concat([have,pd.DataFrame(rows,columns=["fund","ym","nav"])],ignore_index=True)
    out.to_parquet(cache,index=False); return out

def main():
    conf=pd.read_parquet(ROOT/"data"/"universe_confirmed.parquet")
    conf=conf[conf.confirmed_us_eq & conf.ticker.notna()].copy()
    print(f"확정 US주식형(티커보유): {len(conf)}")
    # series→cik
    mf=json.load(open(RAW/"mf_tickers.json")); idx={c:i for i,c in enumerate(mf["fields"])}
    s2cik={}
    for r in mf["data"]: s2cik.setdefault(r[idx["seriesId"]], r[idx["cik"]])
    conf["cik"]=conf["SERIES_ID"].map(s2cik)
    conf=conf[conf.cik.notna()]

    nav=fetch_nav(list(conf["ticker"].unique()))
    nav=nav.sort_values(["fund","ym"]); nav["ret"]=nav.groupby("fund")["nav"].pct_change()
    rets=nav.pivot(index="ym",columns="fund",values="ret")

    ff5=parse_ff(RAW/"F-F_Research_Data_5_Factors_2x3.CSV",["Mkt-RF","SMB","HML","RMW","CMA","RF"])
    mom=parse_ff(RAW/"F-F_Momentum_Factor.CSV",["Mom"]); fac=ff5.join(mom,how='inner').dropna()
    win=[ym for ym in fac.index if "201912"<=ym<="202603"]

    alpha={};smb={};hml={};resid={}
    for tk in rets.columns:
        r=rets[tk].reindex(win)
        d=pd.concat([r.rename('ret'),fac.loc[win]],axis=1).dropna()
        if len(d)<48: continue
        m=sm.OLS(d['ret']-d['RF'],sm.add_constant(d[FACS])).fit()
        alpha[tk]=(1+m.params['const'])**12-1; smb[tk]=m.params['SMB']; hml[tk]=m.params['HML']
        resid[tk]=pd.Series(m.resid,index=d.index)
    # PCA 고정창: 2020-06~2026-03, 완전커버리지 펀드만(신생펀드 탓 붕괴 방지)
    pwin=[ym for ym in fac.index if "202006"<=ym<="202603"]
    R=pd.DataFrame(resid).reindex(pwin)
    R=R.loc[:,R.notna().all()]
    print(f"\nNAV·팩터 분석된 펀드: {len(resid)}, PCA창 {len(pwin)}개월 완전커버리지 {R.shape[1]}펀드",flush=True)

    # §12 PCA
    Z=(R-R.mean())/R.std()
    S=np.linalg.svd(Z.values/np.sqrt(len(Z)-1),compute_uv=False)
    ev=S**2/np.sum(S**2); cum=np.cumsum(ev); n80=int(np.argmax(cum>=0.8)+1)
    C=R.corr().values; iu=np.triu_indices_from(C,1); avgc=C[iu].mean()

    # 스타일 분류
    conf["hml_b"]=conf["ticker"].map(hml); conf["smb_b"]=conf["ticker"].map(smb)
    conf["nav_alpha"]=conf["ticker"].map(alpha)
    def style(h):
        if pd.isna(h): return None
        return "Value" if h>0.15 else ("Growth" if h<-0.15 else "Blend")
    conf=conf.assign(style_box=conf["hml_b"].apply(style))
    def tier(a): return "small" if a<1 else ("mid" if a<5 else "large")
    conf["aum_tier"]=conf["aum_avg"].apply(tier)
    conf=conf[conf["style_box"].notna()]

    # 균형 300 선별: style×tier 9셀, 셀당 ~34, AUM desc
    PER=34; pick=[]
    for st in ["Value","Blend","Growth"]:
        for ti in ["small","mid","large"]:
            cell=conf[(conf["style_box"]==st)&(conf.aum_tier==ti)].sort_values("aum_avg",ascending=False)
            pick.append(cell.head(PER))
    sel=pd.concat(pick)
    # 300 못 채우면 잔여를 AUM desc로 보충
    if len(sel)<300:
        extra=conf[~conf.SERIES_ID.isin(sel.SERIES_ID)].sort_values("aum_avg",ascending=False).head(300-len(sel))
        sel=pd.concat([sel,extra])
    uni300={r.ticker:{"cik":int(r.cik),"seriesId":r.SERIES_ID,"name":r["name"],
                      "style":r.style_box,"aum":round(r.aum_avg,2)} for _,r in sel.iterrows()}
    json.dump(uni300,open(ROOT/"data"/"universe_300.json","w"),indent=1)

    out=["# 15. 확대 universe §12 PCA 재검증 + 균형300 선별\n",
         f"확정 US주식형 중 NAV·팩터 분석 {R.shape[1]}개 (원래 54 → {R.shape[1]}). 공통 {R.shape[0]}개월.\n",
         "## §12 잔차 PCA — 독립 알파차원 비교",
         f"| | 원래 54펀드(그로쓰편중) | 확대 {R.shape[1]}펀드 |",
         "|---|---|---|",
         f"| PC1 분산설명 | 54% | **{ev[0]*100:.0f}%** |",
         f"| 80% 도달 PC수 | 7 | **{n80}** |",
         f"| 평균 잔차상관 | 0.45 | **{avgc:.2f}** |",
         f"\n→ PC1↓·n80↑·평균상관↓ 이면 **독립 알파원천 확보**(그로쓰 편중 해소).",
         f"\n## 스타일×AUM 분포 (확정 {len(conf)}개)",
         "```",
         pd.crosstab(conf["style_box"],conf["aum_tier"]).to_string(),
         "```",
         f"\n## 균형 300 선별 (style×tier 균형, {len(sel)}개)",
         "```",
         pd.crosstab(sel["style_box"],sel["aum_tier"]).to_string(),
         "```",
         f"\n저장: data/universe_300.json ({len(uni300)}개) → 다음 N-PORT 보유 수집"]
    txt="\n".join(out); (ROOT/"notes"/"expand_pca.md").write_text(txt); print("\n"+txt)

if __name__=="__main__":
    main()
