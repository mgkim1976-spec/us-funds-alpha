#!/usr/bin/env python3
"""R3 Reallocation(능동/turnover) 검증 + 4-신호 앙상블 vs 3-신호.
R3 단독: FF알파·하위기간·플라시보. 앙상블: z(mhw+lnp+bi) vs z(+realloc). 출력 notes/reallocation_validate.md
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates(); Rns = rebs[1:]+[pivot.index.max()]
    pcache = {}
    def poa(d):
        k = d.strftime("%Y%m%d")
        if k not in pcache:
            w = pivot.loc[d:d+pd.Timedelta(days=8)]; pcache[k] = w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
        return pcache[k]

    def realloc_scores(R):
        """R3: Σ_funds (active_Δw / fund_turnover). active = drift 제거."""
        from collections import defaultdict
        acc = defaultdict(float)
        for f, series in fw.items():
            fds = [d for d in series if d <= R]
            if len(fds) < 2: continue
            cur, prev = series[fds[-1]], series[fds[-2]]
            p0, p1 = poa(pd.Timestamp(fds[-2])), poa(pd.Timestamp(fds[-1]))
            def rstk(c):
                t = figi.get(c)
                return (p1[t]/p0[t]-1) if (t and t in p0 and t in p1 and not np.isnan(p0[t]) and not np.isnan(p1[t]) and p0[t] > 0) else 0.0
            rfund = sum(prev[c]*rstk(c) for c in prev.index)/(sum(prev.values) or 1)
            idx = cur.index.union(prev.index)
            dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0)
            turn = float((dcur-dprev).abs().sum()) or 1e-9
            for c in idx:
                act = dcur[c] - dprev[c]*(1+rstk(c))/(1+rfund)
                acc[c] += act/turn
        return acc

    PER = {}
    for R in rebs:
        d = fa.score_stocks(fw, R, figi)
        rc = realloc_scores(R); d["realloc"] = pd.to_numeric(d["cusip"].map(lambda c: rc.get(c, 0.0)), errors="coerce")
        sd = d["realloc"].std(); d["z_realloc"] = (d["realloc"]-d["realloc"].mean())/(sd if sd else 1)
        d["ens4"] = d[["z_mhw", "z_lnp", "z_bi", "z_realloc"]].mean(axis=1)
        PER[R] = d

    def basket(col, mh=3, scheme="equal"):
        return fa.basket_daily(rets, {R: PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"].tolist() for R in rebs}, rebs, scheme)
    def row(s):
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        return cg, sh, a, t, ae, te, al, tl

    # 플라시보 (R3)
    def poa2(d): return poa(d)
    spy_qf = np.array([(poa(Rn).get("SPY", np.nan)/poa(R).get("SPY", np.nan)-1) for R, Rn in zip(rebs, Rns)])
    qfwd = {}; univ = {}
    for R, Rn in zip(rebs, Rns):
        p0, p1 = poa(R), poa(Rn)
        u = [t for t in PER[R][PER[R].hold >= 3]["ticker"] if t in p0.index and t in p1.index and not np.isnan(p0[t]) and not np.isnan(p1[t])]
        univ[R] = u; qfwd[R] = {t: p1[t]/p0[t]-1 for t in u}
    def placebo(col):
        pick = {R: [t for t in PER[R][PER[R].hold >= 3].nlargest(30, col)["ticker"] if t in qfwd[R]] for R in rebs}
        cg = lambda a: (np.prod(1+a[~np.isnan(a)]))**(4/len(a[~np.isnan(a)]))-1
        qa = lambda pb: np.array([np.mean([qfwd[R][t] for t in pb[R]]) if pb[R] else np.nan for R in rebs])
        b = qa(pick); bcg = cg(b); bex = np.nanmean(b-spy_qf)
        rng = np.random.default_rng(11); rc = []; re_ = []
        for _ in range(300):
            pr = {R: (list(rng.choice(univ[R], size=min(30, len(univ[R])), replace=False)) if univ[R] else []) for R in rebs}
            a = qa(pr); rc.append(cg(a)); re_.append(np.nanmean(a-spy_qf))
        return (np.array(rc) < bcg).mean()*100, (np.array(re_) < bex).mean()*100

    out = ["# 29. Reallocation(R3) 검증 + 4-신호 앙상블\n",
           "## R3 단독 (능동/turnover, top30 동일가중)", "| 알파 | t | 22-24 | 24-26 | 플라시보(CAGR/초과) |", "|---|---|---|---|---|"]
    cg, sh, a, t, ae, te, al, tl = row(basket("realloc"))
    pc, pe = placebo("realloc")
    out.append(f"| {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) | {pc:.0f}/{pe:.0f} |")

    out += ["\n## 3-신호 vs 4-신호 앙상블 (z-결합 top30 랭크가중)",
            "| 앙상블 | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 |", "|---|---|---|---|---|---|---|"]
    for lab, col in [("3-신호 (mhw+lnp+bi)", "ens"), ("4-신호 (+reallocation)", "ens4")]:
        cg, sh, a, t, ae, te, al, tl = row(basket(col, 3, "rank"))
        out.append(f"| {lab} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) |")
    txt = "\n".join(out); (fa.ROOT/"notes"/"reallocation_validate.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
