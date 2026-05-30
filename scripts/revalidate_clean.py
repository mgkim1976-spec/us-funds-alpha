#!/usr/bin/env python3
"""정제 신호 검증: 3전략(MHW≥15·LNP≥3·BI≥5) 풀기간 알파 + 하위기간 + 플라시보(랜덤 대비).
출력 notes/revalidate_clean.md. 비주식 제외는 falib.load_panel이 처리.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

CFG = {"mhw": 15, "lnp": 3, "bi": 5}
NAMES = {"mhw": "Mean Holding Weight", "lnp": "Large New Positions", "bi": "Best-Ideas"}

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates(); Rns = rebs[1:]+[pivot.index.max()]
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}

    def poa(d):
        w = pivot.loc[d:d+pd.Timedelta(days=8)]; return w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
    spy_qf = np.array([(poa(Rn).get("SPY", np.nan)/poa(R).get("SPY", np.nan)-1) for R, Rn in zip(rebs, Rns)])
    qfwd = {}; univ = {}
    for R, Rn in zip(rebs, Rns):
        p0, p1 = poa(R), poa(Rn)
        u = [t for t in PER[R][PER[R].hold >= 3]["ticker"]
             if t in p0.index and t in p1.index and not np.isnan(p0[t]) and not np.isnan(p1[t])]
        univ[R] = u; qfwd[R] = {t: p1[t]/p0[t]-1 for t in u}

    def placebo(col, mh):
        bi_t = {R: [t for t in PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"] if t in qfwd[R]] for R in rebs}
        cg = lambda a: (np.prod(1+a[~np.isnan(a)]))**(4/len(a[~np.isnan(a)]))-1
        qa = lambda pb: np.array([np.mean([qfwd[R][t] for t in pb[R]]) if pb[R] else np.nan for R in rebs])
        b = qa(bi_t); bcg = cg(b); bex = np.nanmean(b-spy_qf)
        umh = {R: [t for t in PER[R][PER[R].hold >= mh]["ticker"] if t in qfwd[R]] for R in rebs}
        rng = np.random.default_rng(11); rc = []; re_ = []
        for _ in range(300):
            pr = {R: (list(rng.choice(umh[R], size=min(30, len(umh[R])), replace=False)) if umh[R] else []) for R in rebs}
            a = qa(pr); rc.append(cg(a)); re_.append(np.nanmean(a-spy_qf))
        return bcg, (np.array(rc) < bcg).mean()*100, bex, (np.array(re_) < bex).mean()*100

    out = ["# 25. 정제 신호 검증 (비주식 제외 + 정제 minhold)\n",
           "| 신호 | minhold | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 | 플라시보(CAGR/초과 백분위) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for sig, mh in CFG.items():
        s = fa.basket_daily(rets, {R: PER[R][PER[R].hold >= mh].nlargest(30, sig)["ticker"].tolist() for R in rebs}, rebs)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        pc_cg, pc_p, ex, ex_p = placebo(sig, mh)
        out.append(f"| {NAMES[sig]} | ≥{mh} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | "
                   f"{ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) | {pc_p:.0f}/{ex_p:.0f} |")
    out.append("\n비교(오염 헤드라인): MHW hold≥3 +8.4%(t2.73). 정제후 t>2·플라시보 90+ 유지면 robust.")
    txt = "\n".join(out); (fa.ROOT/"notes"/"revalidate_clean.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
