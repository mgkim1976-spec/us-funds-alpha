#!/usr/bin/env python3
"""유니버스 세분화: 소형틸트·섹터(기술) 코호트의 신호가 broad보다 강한가.
코호트 펀드만으로 앙상블 top30 → FF5+Mom 알파·하위기간·Sharpe. 출력 notes/cohort.md
"""
import sys, json, re
from pathlib import Path
import numpy as np, pandas as pd
import statsmodels.api as sm
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

def main():
    h = fa.load_panel(); figi = fa.figi_map()
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()
    funds = sorted(h["fund"].unique())   # 티커

    # SMB 틸트 (NAV) — 소형 코호트
    nav = pd.read_parquet(fa.DATA/"fund_nav_full.parquet").sort_values(["fund", "ym"])
    nav["ret"] = nav.groupby("fund")["nav"].pct_change()
    nrets = nav.pivot(index="ym", columns="fund", values="ret")
    win = [ym for ym in fac.index if "201912" <= ym <= "202603"]
    FACS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
    smb = {}
    for tk in funds:
        if tk not in nrets.columns: continue
        d = pd.concat([nrets[tk].reindex(win).rename('r'), fac.loc[win]], axis=1).dropna()
        if len(d) >= 36:
            smb[tk] = sm.OLS(d['r']-d['RF'], sm.add_constant(d[FACS])).fit().params['SMB']
    # 섹터(기술) — 펀드명
    names = h.drop_duplicates("fund").set_index("fund")["name"] if "name" in h else pd.Series(dtype=str)
    uni = json.load(open(fa.DATA/"universe_300.json"))
    fname = {tk: v.get("name", "") for tk, v in uni.items()}
    tech_rx = r"technolog|\btech\b|software|semiconduct|internet|digital|innovation|disrupt|next gen"

    cohorts = {
        "broad (전체 300)": set(funds),
        "소형틸트 (SMB>0.2)": {t for t in funds if smb.get(t, 0) > 0.2},
        "대형 (SMB<0)": {t for t in funds if smb.get(t, 9) < 0},
        "기술 특화": {t for t in funds if re.search(tech_rx, fname.get(t, "").lower())},
    }
    for k, v in cohorts.items(): print(f"  {k}: {len(v)}펀드", flush=True)

    def ens_daily(cohort, mh):
        fw = fa.fund_timelines(h, funds=cohort)
        picks = {R: fa.score_stocks(fw, R, figi).pipe(lambda d: d[d.hold >= mh].nlargest(30, "ens")["ticker"].tolist()) for R in rebs}
        return fa.basket_daily(rets, picks, rebs, "rank")

    out = ["# 30. 유니버스 세분화 — 코호트별 앙상블 신호\n",
           "코호트 펀드만으로 z-결합 앙상블 top30(랭크가중). FF5+Mom(SMB 포함=사이즈 보정).\n",
           "| 코호트 | 펀드수 | CAGR | Sharpe | 알파 | t | 2022-24 | 2024-26 |", "|---|---|---|---|---|---|---|---|"]
    for k, cohort in cohorts.items():
        if len(cohort) < 8:
            out.append(f"| {k} | {len(cohort)} | 표본부족 | | | | | |"); continue
        mh = 2 if len(cohort) < 60 else 3
        s = ens_daily(cohort, mh)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        out.append(f"| {k} | {len(cohort)} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) |")
        print(f"{k}: α{a*100:+.1f}% t{t:+.2f}", flush=True)
    out.append("\n※ FF5는 SMB(사이즈)를 보정하므로, 소형 코호트 알파>0이면 *사이즈 프리미엄 너머의 종목선택* 알파.")
    out.append("※ 코호트가 작을수록 breadth↓·노이즈↑ (MINHOLD 완화 적용).")
    txt = "\n".join(out); (fa.ROOT/"notes"/"cohort.md").write_text(txt); print("\n"+txt)

if __name__ == "__main__":
    main()
