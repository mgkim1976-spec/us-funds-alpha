#!/usr/bin/env python3
"""비중 방식 테스트 (z-결합 앙상블 top30). 동일/z가중/랭크/역변동성/랭크×역변동성.
각 방식 CAGR·Sharpe·알파·하위기간 + 집중도(상위5 비중). 출력 notes/weighting.md
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
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}
    ztop = {R: PER[R][PER[R].hold >= 3].nlargest(30, "ens")[["ticker", "ens"]].reset_index(drop=True) for R in rebs}

    def vol_at(tk, R):
        s = rets[tk].loc[R-pd.Timedelta(days=95):R].dropna() if tk in rets.columns else pd.Series(dtype=float)
        return s.std() if len(s) > 20 else np.nan

    def wvec(R, scheme):
        d = ztop[R]; d = d[d["ticker"].isin(rets.columns)]; n = len(d)
        if n == 0: return {}
        if scheme == "equal": w = np.ones(n)
        elif scheme == "zscore": z = d["ens"].values; w = np.clip(z-z.min()+0.1, 0, None)
        elif scheme == "rank": w = np.arange(n, 0, -1).astype(float)
        else:  # invvol / rankvol
            v = np.array([vol_at(t, R) for t in d["ticker"]]); med = np.nanmedian(v)
            v = np.where(np.isnan(v) | (v <= 0), med, v)
            w = (1.0/v) if scheme == "invvol" else np.arange(n, 0, -1)*(1.0/v)
        w = w/w.sum(); return dict(zip(d["ticker"], w))

    def daily(scheme):
        seg = []; top5 = []
        for R, Rn in zip(rebs, Rns):
            wd = wvec(R, scheme)
            if not wd: continue
            top5.append(sum(sorted(wd.values(), reverse=True)[:5]))
            m = (rets.index >= R) & (rets.index < Rn)
            seg.append((rets.loc[m, list(wd)]*pd.Series(wd)).sum(axis=1))
        return pd.concat(seg).sort_index(), float(np.mean(top5))

    out = ["# 27. 비중 방식 테스트 (z-결합 앙상블 top30, 정제데이터)\n",
           "| 비중방식 | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 | 상위5비중 |", "|---|---|---|---|---|---|---|---|"]
    nm = {"equal": "동일가중", "zscore": "z(신호)가중", "rank": "랭크가중", "invvol": "역변동성", "rankvol": "랭크×역변동성"}
    for sc in ["equal", "zscore", "rank", "invvol", "rankvol"]:
        s, t5 = daily(sc); cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        out.append(f"| {nm[sc]} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | "
                   f"{ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) | {t5*100:.0f}% |")
    txt = "\n".join(out); (fa.ROOT/"notes"/"weighting.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
