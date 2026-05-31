#!/usr/bin/env python3
"""유니버스 방법론 분석 — 세 갈래를 한 파일에 (→ notes/universe.md):
  cohort  — 소형틸트·섹터 코호트의 신호가 broad보다 강한가
  compare — 유니버스 300 vs 541 (breadth 확대 효과)
  breadth — N(펀드 수)별 시그널 알파 포화곡선
사용: python3 scripts/universe_research.py [cohort|compare|breadth|all]"""
import sys, json, re
from pathlib import Path
import numpy as np, pandas as pd
import statsmodels.api as sm
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

NAMES = {"ens": "앙상블", "mhw": "Mean Holding Wt", "lnp": "Large New Pos", "bi": "Best-Ideas"}

def run_cohort():
    h = fa.load_panel(); figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates(); funds = sorted(h["fund"].unique())
    nav = pd.read_parquet(fa.DATA/"fund_nav_full.parquet").sort_values(["fund", "ym"])
    nav["ret"] = nav.groupby("fund")["nav"].pct_change(); nrets = nav.pivot(index="ym", columns="fund", values="ret")
    win = [ym for ym in fac.index if "201912" <= ym <= "202603"]; FACS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
    smb = {}
    for tk in funds:
        if tk not in nrets.columns: continue
        d = pd.concat([nrets[tk].reindex(win).rename('r'), fac.loc[win]], axis=1).dropna()
        if len(d) >= 36: smb[tk] = sm.OLS(d['r']-d['RF'], sm.add_constant(d[FACS])).fit().params['SMB']
    uni = json.load(open(fa.DATA/"universe_300.json")); fname = {tk: v.get("name", "") for tk, v in uni.items()}
    tech_rx = r"technolog|\btech\b|software|semiconduct|internet|digital|innovation|disrupt|next gen"
    cohorts = {"broad (전체 300)": set(funds), "소형틸트 (SMB>0.2)": {t for t in funds if smb.get(t, 0) > 0.2},
               "대형 (SMB<0)": {t for t in funds if smb.get(t, 9) < 0},
               "기술 특화": {t for t in funds if re.search(tech_rx, fname.get(t, "").lower())}}
    def ens_daily(cohort, mh):
        fw = fa.fund_timelines(h, funds=cohort)
        picks = {R: fa.score_stocks(fw, R, figi).pipe(lambda d: d[d.hold >= mh].nlargest(30, "ens")["ticker"].tolist()) for R in rebs}
        return fa.basket_daily(rets, picks, rebs, "rank")
    out = ["## 유니버스 세분화 — 코호트별 앙상블 (FF5+Mom, SMB 보정=사이즈 너머 알파)",
           "| 코호트 | 펀드수 | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 |", "|---|---|---|---|---|---|---|---|"]
    for k, cohort in cohorts.items():
        if len(cohort) < 8: out.append(f"| {k} | {len(cohort)} | 표본부족 | | | | | |"); continue
        s = ens_daily(cohort, 2 if len(cohort) < 60 else 3)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        out.append(f"| {k} | {len(cohort)} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) |")
    return "\n".join(out)

def run_compare():
    CFG = {"ens": ("ens", 3), "mhw": ("mhw", 15), "lnp": ("lnp", 3), "bi": ("bi", 5)}
    def evaluate(panel):
        h = fa.load_panel(panel); figi = fa.figi_map(); fw = fa.fund_timelines(h)
        pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors(); rebs = fa.rebalance_dates()
        PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}; res = {}
        for k, (col, mh) in CFG.items():
            s = fa.basket_daily(rets, {R: PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"].tolist() for R in rebs}, rebs, "rank")
            cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
            ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
            res[k] = (cg, sh, a, t, ae, te, al, tl)
        return res, h["fund"].nunique()
    r300, n300 = evaluate("holdings_panel_300.parquet"); r541, n541 = evaluate("holdings_panel_541.parquet")
    out = [f"## 유니버스 300 vs 541 (breadth 확대, 펀드 {n300}→{n541})",
           "| 신호 | 300 알파(t) | 541 알파(t) | 300 Sh | 541 Sh | 541 22-24 | 541 24-26 |", "|---|---|---|---|---|---|---|"]
    for k in CFG:
        a3, a5 = r300[k], r541[k]
        out.append(f"| {NAMES[k]} | {a3[2]*100:+.1f}%(t{a3[3]:.2f}) | {a5[2]*100:+.1f}%(t{a5[3]:.2f}) | {a3[1]:.2f} | {a5[1]:.2f} | {a5[4]*100:+.1f}%(t{a5[5]:.1f}) | {a5[6]*100:+.1f}%(t{a5[7]:.1f}) |")
    return "\n".join(out)

def run_breadth():
    SIGS = ["ens", "mhw", "lnp", "bi"]
    h = fa.load_panel("holdings_panel_541.parquet"); figi = fa.figi_map()
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors(); rebs = fa.rebalance_dates()
    allf = sorted(h["fund"].unique()); nall = len(allf); by = {f: g for f, g in h.groupby("fund")}
    def alpha_of(funds):
        fw = {f: dict(sorted({pd.Timestamp(fd): gg.groupby("cusip")["w"].sum() for fd, gg in by[f].groupby("filingDate")}.items())) for f in funds}
        PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}; res = {}
        for k in SIGS:
            s = fa.basket_daily(rets, {R: PER[R][PER[R].hold >= 2].nlargest(30, k)["ticker"].tolist() for R in rebs}, rebs, "equal")
            res[k] = fa.ff_alpha(s, fac)
        return res
    rng = np.random.default_rng(7); curve = {k: {} for k in SIGS}
    for N in [50, 100, 200, 300, 400, nall]:
        draws = 1 if N >= nall else 6; acc = {k: [] for k in SIGS}
        for _ in range(draws):
            r = alpha_of(allf if N >= nall else list(rng.choice(allf, size=N, replace=False)))
            for k in SIGS: acc[k].append(r[k])
        for k in SIGS:
            aa = np.array([x[0] for x in acc[k]]); tt = np.array([x[1] for x in acc[k]]); curve[k][N] = (aa.mean(), aa.std(), tt.mean())
    out = ["## Breadth 스케일링 — N별 알파 포화곡선 (동일가중 top30·minhold2)",
           "| N | " + " | ".join(NAMES[k] for k in SIGS) + " |", "|---|" + "---|"*len(SIGS)]
    for N in [50, 100, 200, 300, 400, nall]:
        out.append(f"| {N} | " + " | ".join(f"{curve[k][N][0]*100:+.1f}% (t{curve[k][N][2]:+.1f})" for k in SIGS) + " |")
    return "\n".join(out)

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    parts = ["# 유니버스 방법론 분석\n"]
    if which in ("cohort", "all"): parts.append(run_cohort())
    if which in ("compare", "all"): parts.append(run_compare())
    if which in ("breadth", "all"): parts.append(run_breadth())
    txt = "\n\n".join(parts); (fa.ROOT/"notes"/"universe.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
