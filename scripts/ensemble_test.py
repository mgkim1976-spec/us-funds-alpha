#!/usr/bin/env python3
"""3-신호 앙상블 (MS max-diversification 검증, 정제데이터).
개별(MHW≥15·LNP≥3·BI≥5) vs ①블렌드(수익1/3) ②z-결합(랭크 무관, 동일가중) top30.
각각 CAGR·Sharpe·알파·하위기간 + 신호 간 상관. 출력 notes/ensemble.md
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

CFG = {"mhw": 15, "lnp": 3, "bi": 5}

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}

    def picks(col, mh): return {R: PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"].tolist() for R in rebs}
    def st(s):
        cagr, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        return dict(cagr=cagr, sh=sh, a=a, t=t, ae=ae, te=te, al=al, tl=tl), s

    dmhw = fa.basket_daily(rets, picks("mhw", 15), rebs)
    dlnp = fa.basket_daily(rets, picks("lnp", 3), rebs)
    dbi  = fa.basket_daily(rets, picks("bi", 5), rebs)
    blend = pd.concat([dmhw, dlnp, dbi], axis=1).mean(axis=1)        # 앙상블A
    dz = fa.basket_daily(rets, picks("ens", 3), rebs)               # 앙상블B (z-결합)
    res = {"MHW(≥15)": st(dmhw), "LNP(≥3)": st(dlnp), "BI(≥5)": st(dbi),
           "앙상블A 블렌드": st(blend), "앙상블B z-결합": st(dz)}

    Q = pd.concat([(1+dmhw).resample("QE").prod().rename("MHW"),
                   (1+dlnp).resample("QE").prod().rename("LNP"),
                   (1+dbi).resample("QE").prod().rename("BI")], axis=1).dropna() - 1
    corr = Q.corr()

    out = ["# 26. 3-신호 앙상블 (max-diversification 검증, 정제데이터)\n",
           "| 전략 | CAGR | Sharpe | 알파 | t | 2022-24 | 2024-26 |", "|---|---|---|---|---|---|---|"]
    for k, (m, _) in res.items():
        out.append(f"| {k} | {m['cagr']*100:.1f}% | {m['sh']:.2f} | {m['a']*100:+.1f}% | {m['t']:+.2f} | "
                   f"{m['ae']*100:+.1f}%(t{m['te']:+.1f}) | {m['al']*100:+.1f}%(t{m['tl']:+.1f}) |")
    out += ["\n## 신호 간 분기수익 상관 (낮을수록 분산효과↑)", "```", corr.round(2).to_string(), "```",
            f"\n평균 쌍상관: {corr.values[np.triu_indices(3,1)].mean():.2f}"]
    txt = "\n".join(out); (fa.ROOT/"notes"/"ensemble.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
