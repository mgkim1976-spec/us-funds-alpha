#!/usr/bin/env python3
"""13F(헤지펀드) 분석 — 네 갈래를 한 파일에 (→ notes/f13.md):
  refine  — 집중도 필터(노이즈 RIA/연기금 제거) crude vs concentrated
  breadth — 정제 풀에서 N별 앙상블 포화점 곡선
  vs      — 뮤추얼펀드(N-PORT) vs 헤지펀드(13F) 시그널 비교
  combine — MF+13F 결합(best-of-both) vs 각 소스 단독
사용: python3 scripts/f13_analysis.py [refine|breadth|vs|combine|all]"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = fa.rebalance_dates("2024-09-01", "2026-03-01")
SIGS = {"ens": "앙상블", "mhw": "Mean Holding Wt", "lnp": "Large New Pos", "bi": "Best-Ideas"}

def load_13f_raw():
    d = pd.read_parquet(fa.DATA/"f13_panel.parquet")
    d = d[d["cusip"].str.len() == 9].copy().rename(columns={"manager": "fund"})
    d["w"] = d["pctVal"]/100.0; d["filingDate"] = pd.to_datetime(d["filingDate"])
    return d

def conc_filter(d, nmin, nmax, top10min):
    g = d.groupby(["fund", "reportDate"])
    stat = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = stat[(stat.n >= nmin) & (stat.n <= nmax) & (stat.top10 >= top10min)][["fund", "reportDate"]]
    return d.merge(keep, on=["fund", "reportDate"]), keep["fund"].nunique()

def evaluate(h, figi, rets, fac):
    fw = fa.fund_timelines(h); PER = {R: fa.score_stocks(fw, R, figi) for R in REBS}
    res = {}
    for k in SIGS:
        s = fa.basket_daily(rets, {R: PER[R][PER[R].hold >= 3].nlargest(30, k)["ticker"].tolist() for R in REBS}, REBS, "rank")
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); res[k] = (a, t, sh, cg)
    nf = int(np.median([len([f for f in fw if any(d <= R for d in fw[f])]) for R in REBS]))
    return res, nf

def run_refine(figi, rets, fac):
    d = load_13f_raw()
    cfgs = {"crude (전체 액티브)": d, "집중 (15-80, 상위10≥40%)": conc_filter(d, 15, 80, 0.40)[0],
            "초집중 (10-50, 상위10≥55%)": conc_filter(d, 10, 50, 0.55)[0]}
    out = ["## 13F 정밀 선별 — 집중도 필터", "| 코호트 | 매니저수 | 앙상블 | MHW | LNP | Best-Ideas |", "|---|---|---|---|---|---|"]
    for lab, dd in cfgs.items():
        res, nf = evaluate(dd, figi, rets, fac)
        out.append(f"| {lab} | {nf} | " + " | ".join(f"{res[k][0]*100:+.1f}%(t{res[k][1]:.1f})" for k in SIGS) + " |")
    return "\n".join(out)

def run_breadth(figi, rets, fac):
    d, _ = conc_filter(load_13f_raw(), 15, 80, 0.40); allf = sorted(d["fund"].unique()); nall = len(allf)
    by = {f: gg for f, gg in d.groupby("fund")}
    def ens_alpha(funds):
        fw = {f: dict(sorted({pd.Timestamp(fd): gg.groupby("cusip")["w"].sum() for fd, gg in by[f].groupby("filingDate")}.items())) for f in funds}
        PER = {R: fa.score_stocks(fw, R, figi) for R in REBS}
        return fa.ff_alpha(fa.basket_daily(rets, {R: PER[R][PER[R].hold >= 3].nlargest(30, "ens")["ticker"].tolist() for R in REBS}, REBS, "rank"), fac)
    rng = np.random.default_rng(7)
    out = [f"## 13F breadth 곡선 — 앙상블 포화점 (정제 풀 {nall})", "| N | 앙상블 알파 | t |", "|---|---|---|"]
    for N in [50, 100, 200, 400, 800, 1600, nall]:
        draws = 1 if N >= nall else 5
        accs = [ens_alpha(allf if N >= nall else list(rng.choice(allf, size=N, replace=False))) for _ in range(draws)]
        a = np.array([x[0] for x in accs]); t = np.array([x[1] for x in accs])
        out.append(f"| {N} | {a.mean()*100:+.1f}% (±{a.std()*100:.1f}) | {t.mean():+.1f} |")
    return "\n".join(out)

def run_vs(figi, rets, fac):
    mf, nmf = evaluate(fa.load_panel("holdings_panel_541.parquet").pipe(lambda h: h[h["reportDate"] >= "2024-01-01"]), figi, rets, fac)
    hf, nhf = evaluate(load_13f_raw(), figi, rets, fac)
    out = [f"## 뮤추얼펀드 vs 13F 시그널 비교 (MF {nmf} vs 13F {nhf}매니저)",
           "| 신호 | MF 알파(t) | 13F 알파(t) | MF Sharpe | 13F Sharpe |", "|---|---|---|---|---|"]
    for k in SIGS:
        m, f = mf[k], hf[k]
        out.append(f"| {SIGS[k]} | {m[0]*100:+.1f}%(t{m[1]:.2f}) | {f[0]*100:+.1f}%(t{f[1]:.2f}) | {m[2]:.2f} | {f[2]:.2f} |")
    return "\n".join(out)

def run_combine(figi, rets, fac):
    mf = fa.load_panel("holdings_panel_541.parquet"); mf = mf[mf["reportDate"] >= "2024-01-01"]
    hf = fa.load_13f()
    MF = {R: fa.score_stocks(fa.fund_timelines(mf), R, figi) for R in REBS}
    HF = {R: fa.score_stocks(fa.fund_timelines(hf), R, figi) for R in REBS}
    def top_by(df, col): return df[df.hold >= 3].nlargest(30, col)["ticker"].tolist()
    def combo(R, cmf, chf):
        m = MF[R][["cusip", "ticker", "hold"] + cmf].copy(); h = HF[R][["cusip"] + chf].copy()
        d = m.merge(h, on="cusip", how="outer", suffixes=("", "_hf")); zc = cmf + chf
        for c in zc: d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
        d["combo"] = d[zc].mean(axis=1); return d[d["ticker"].notna()].nlargest(30, "combo")["ticker"].tolist()
    strat = {"MF 앙상블": {R: top_by(MF[R], "ens") for R in REBS}, "13F 앙상블": {R: top_by(HF[R], "ens") for R in REBS},
             "13F Best-Ideas": {R: top_by(HF[R], "bi") for R in REBS},
             "결합: MF(mhw·lnp)+HF(bi)": {R: combo(R, ["z_mhw", "z_lnp"], ["z_bi"]) for R in REBS},
             "결합: 전체": {R: combo(R, ["z_mhw", "z_lnp", "z_bi"], ["z_bi"]) for R in REBS}}
    out = ["## MF + 13F 결합 시그널", "| 전략 | CAGR | Sharpe | 알파 | t |", "|---|---|---|---|---|"]
    for lab, pk in strat.items():
        s = fa.basket_daily(rets, pk, REBS, "rank"); cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        out.append(f"| {lab} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} |")
    return "\n".join(out)

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    parts = ["# 13F(헤지펀드) 분석 — 공통 2024-09~2026-03, 랭크가중 top30, FF5+Mom\n"]
    if which in ("refine", "all"): parts.append(run_refine(figi, rets, fac))
    if which in ("breadth", "all"): parts.append(run_breadth(figi, rets, fac))
    if which in ("vs", "all"): parts.append(run_vs(figi, rets, fac))
    if which in ("combine", "all"): parts.append(run_combine(figi, rets, fac))
    txt = "\n\n".join(parts); (fa.ROOT/"notes"/"f13.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
