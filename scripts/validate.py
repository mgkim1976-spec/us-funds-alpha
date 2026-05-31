#!/usr/bin/env python3
"""검증 모음 — 다섯 갈래를 한 파일에 (→ notes/validate.md):
  signals  — 전 신호군 일괄(정제, long-only top30, FF5+Mom)
  revalid  — 정제 신호 3종 풀기간+하위기간+플라시보
  ensemble — 개별 vs 블렌드 vs z-결합 + 신호 상관
  weighting— 비중 방식 5종(동일/z/랭크/역변동성/랭크×역변동성)
  mhwcost  — Mean Holding Weight top10/20/30 × 거래비용
사용: python3 scripts/validate.py [signals|revalid|ensemble|weighting|mhwcost|all]"""
import sys, re, json
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
import statsmodels.api as sm
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

def _base():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates(); Rns = rebs[1:]+[pivot.index.max()]
    def poa(d):
        w = pivot.loc[d:d+pd.Timedelta(days=8)]; return w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
    return h, figi, fw, pivot, rets, fac, rebs, Rns, poa

def run_signals():
    h, figi, fw, pivot, rets, fac, rebs, Rns, poa = _base()
    SIGS = ["mhw", "net_weight_change", "herding", "lnp", "churn_weighted_flow", "concentration_weighted_flow", "reallocation_intensity", "bi"]
    def scored_full(R):
        base = fa.score_stocks(fw, R, figi).set_index("cusip")
        acc = {s: defaultdict(float) for s in ["net_weight_change", "herding", "churn_weighted_flow", "concentration_weighted_flow", "reallocation_intensity"]}
        for f, series in fw.items():
            fds = [d for d in series if d <= R]
            if not fds: continue
            cur = series[fds[-1]]; prev = series[fds[-2]] if len(fds) >= 2 else pd.Series(dtype=float)
            idx = cur.index.union(prev.index); dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0); dlt = dcur-dprev
            turn = float(dlt.abs().sum()) or 1e-9; conc = float((dcur**2).sum())
            for c in idx:
                d = dlt[c]; acc["net_weight_change"][c] += d; acc["churn_weighted_flow"][c] += d*turn; acc["concentration_weighted_flow"][c] += d*conc
                if d > 0: acc["reallocation_intensity"][c] += d/turn
                if d > 0.001: acc["herding"][c] += 1
                elif d < -0.001: acc["herding"][c] -= 1
        df = base.reset_index()
        for s in acc: df[s] = pd.to_numeric(df["cusip"].map(lambda c, ss=s: acc[ss].get(c, 0.0)), errors="coerce")
        return df[df.hold >= 3]
    PER = {R: scored_full(R) for R in rebs}
    labels = {"mhw": "Mean Holding Weight", "net_weight_change": "Net Weight Change", "herding": "Herding", "lnp": "Large New Positions",
              "churn_weighted_flow": "★Churn-Weighted Flow", "concentration_weighted_flow": "★Concentration-Wtd Flow",
              "reallocation_intensity": "★Reallocation Intensity", "bi": "Best-Ideas"}
    out = ["## 전 신호군 일괄 (정제, long-only top30, FF5+Mom). ★=정의 미공개·재구성",
           "| 신호 | CAGR | Sharpe | 알파 | t |", "|---|---|---|---|---|"]
    for s in SIGS:
        d = fa.basket_daily(rets, {R: PER[R].nlargest(30, s)["ticker"].tolist() for R in rebs}, rebs)
        cg, sh = fa.perf(d); a, t = fa.ff_alpha(d, fac)
        out.append(f"| {labels[s]} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} |")
    return "\n".join(out)

def run_revalid():
    h, figi, fw, pivot, rets, fac, rebs, Rns, poa = _base()
    CFG = {"mhw": 15, "lnp": 3, "bi": 5}; NAMES = {"mhw": "Mean Holding Weight", "lnp": "Large New Positions", "bi": "Best-Ideas"}
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}
    spy_qf = np.array([(poa(Rn).get("SPY", np.nan)/poa(R).get("SPY", np.nan)-1) for R, Rn in zip(rebs, Rns)])
    qfwd = {}; univ = {}
    for R, Rn in zip(rebs, Rns):
        p0, p1 = poa(R), poa(Rn)
        u = [t for t in PER[R][PER[R].hold >= 3]["ticker"] if t in p0.index and t in p1.index and not np.isnan(p0[t]) and not np.isnan(p1[t])]
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
        return (np.array(rc) < bcg).mean()*100, (np.array(re_) < bex).mean()*100
    out = ["## 정제 신호 검증 (비주식 제외 + 정제 minhold)",
           "| 신호 | minhold | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 | 플라시보(CAGR/초과 백분위) |", "|---|---|---|---|---|---|---|---|---|"]
    for sig, mh in CFG.items():
        s = fa.basket_daily(rets, {R: PER[R][PER[R].hold >= mh].nlargest(30, sig)["ticker"].tolist() for R in rebs}, rebs)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604")); pc, pe = placebo(sig, mh)
        out.append(f"| {NAMES[sig]} | ≥{mh} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) | {pc:.0f}/{pe:.0f} |")
    return "\n".join(out)

def run_ensemble():
    h, figi, fw, pivot, rets, fac, rebs, Rns, poa = _base()
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}
    def picks(col, mh): return {R: PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"].tolist() for R in rebs}
    def st(s):
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        return (cg, sh, a, t, ae, te, al, tl)
    dmhw = fa.basket_daily(rets, picks("mhw", 15), rebs); dlnp = fa.basket_daily(rets, picks("lnp", 3), rebs); dbi = fa.basket_daily(rets, picks("bi", 5), rebs)
    blend = pd.concat([dmhw, dlnp, dbi], axis=1).mean(axis=1); dz = fa.basket_daily(rets, picks("ens", 3), rebs)
    res = {"MHW(≥15)": st(dmhw), "LNP(≥3)": st(dlnp), "BI(≥5)": st(dbi), "앙상블A 블렌드": st(blend), "앙상블B z-결합": st(dz)}
    Q = (pd.concat([(1+dmhw).resample("QE").prod().rename("MHW"), (1+dlnp).resample("QE").prod().rename("LNP"), (1+dbi).resample("QE").prod().rename("BI")], axis=1).dropna() - 1)
    out = ["## 3-신호 앙상블 (max-diversification)", "| 전략 | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 |", "|---|---|---|---|---|---|---|"]
    for k, m in res.items():
        out.append(f"| {k} | {m[0]*100:.1f}% | {m[1]:.2f} | {m[2]*100:+.1f}% | {m[3]:+.2f} | {m[4]*100:+.1f}%(t{m[5]:+.1f}) | {m[6]*100:+.1f}%(t{m[7]:+.1f}) |")
    out.append(f"\n신호간 분기수익 평균 쌍상관: {Q.corr().values[np.triu_indices(3,1)].mean():.2f} (낮을수록 분산효과↑)")
    return "\n".join(out)

def run_weighting():
    h, figi, fw, pivot, rets, fac, rebs, Rns, poa = _base()
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
        else:
            v = np.array([vol_at(t, R) for t in d["ticker"]]); med = np.nanmedian(v); v = np.where(np.isnan(v) | (v <= 0), med, v)
            w = (1.0/v) if scheme == "invvol" else np.arange(n, 0, -1)*(1.0/v)
        w = w/w.sum(); return dict(zip(d["ticker"], w))
    def daily(scheme):
        seg = []; top5 = []
        for R, Rn in zip(rebs, Rns):
            wd = wvec(R, scheme)
            if not wd: continue
            top5.append(sum(sorted(wd.values(), reverse=True)[:5]))
            m = (rets.index >= R) & (rets.index < Rn); seg.append((rets.loc[m, list(wd)]*pd.Series(wd)).sum(axis=1))
        return pd.concat(seg).sort_index(), float(np.mean(top5))
    nm = {"equal": "동일가중", "zscore": "z(신호)가중", "rank": "랭크가중", "invvol": "역변동성", "rankvol": "랭크×역변동성"}
    out = ["## 비중 방식 (z-결합 앙상블 top30)", "| 비중방식 | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 | 상위5비중 |", "|---|---|---|---|---|---|---|---|"]
    for sc in ["equal", "zscore", "rank", "invvol", "rankvol"]:
        s, t5 = daily(sc); cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        out.append(f"| {nm[sc]} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) | {t5*100:.0f}% |")
    return "\n".join(out)

def run_mhwcost():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    h = pd.read_parquet(fa.DATA/"holdings_panel_300.parquet"); h = h[h['cusip'].str.len() == 9].copy()
    h['w'] = h['pctVal']/100.0; h['filingDate'] = pd.to_datetime(h['filingDate'])
    rebs = fa.rebalance_dates("2022-06-01", "2026-03-01"); Rns = rebs[1:]+[pivot.index.max()]
    fw = {f: dict(sorted({pd.Timestamp(fd): gg.groupby('cusip')['w'].sum() for fd, gg in g.groupby('filingDate')}.items())) for f, g in h.groupby('fund')}
    def picks(topn):
        out = {}
        for R in rebs:
            sumw = defaultdict(float); hold = defaultdict(int)
            for f, series in fw.items():
                fds = [d for d in series if d <= R]
                if not fds: continue
                for c, w in series[fds[-1]].items(): sumw[c] += w; hold[c] += 1
            rows = [(c, sumw[c]/hold[c]) for c in hold if hold[c] >= 3 and figi.get(c) in pivot.columns]
            rows.sort(key=lambda x: x[1], reverse=True); out[R] = [figi[c] for c, _ in rows[:topn]]
        return out
    def poa(d):
        w = pivot.loc[d:d+pd.Timedelta(days=8)]; return w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
    def qret(t, R, Rn):
        p0 = poa(R).get(t); p1 = poa(Rn).get(t)
        return (p1/p0-1) if (p0 and p1 and not np.isnan(p0) and not np.isnan(p1)) else np.nan
    def run(topn, c):
        pk = picks(topn); turns = []; seg = []; cbm = {}; prev = []; prevR = None
        for R, Rn in zip(rebs, Rns):
            new = [t for t in pk[R] if t in rets.columns]
            if prev:
                qr = {t: qret(t, prevR, R) for t in prev}
                dw = {t: (1.0/len(prev))*(1+qr[t]) for t in prev if not np.isnan(qr.get(t, np.nan))}
                tot = sum(dw.values()) or 1.0; dw = {t: v/tot for t, v in dw.items()}
            else: dw = {}
            tgt = {t: 1.0/len(new) for t in new} if new else {}; allt = set(dw) | set(tgt)
            to = sum(abs(tgt.get(t, 0)-dw.get(t, 0)) for t in allt); turns.append(to/2)
            cbm[pd.Timestamp(R).strftime('%Y%m')] = to*c
            m = (rets.index >= R) & (rets.index < Rn)
            if new: seg.append(rets.loc[m, new].mean(axis=1))
            prev = new; prevR = R
        gross = pd.concat(seg).sort_index(); mg = (1+gross).resample('ME').prod()-1; mg.index = mg.index.strftime('%Y%m')
        net = mg.copy()
        for ym, cost in cbm.items():
            if ym in net.index: net[ym] = (1+net[ym])*(1-cost)-1
        return mg, net, np.mean(turns)
    def metrics(mr):
        s = mr.copy(); s.index = pd.PeriodIndex(s.index, freq='M').to_timestamp(); qs = ((1+s).resample('QE').prod()-1).dropna()
        cg = (np.prod(1+qs.values))**(4/len(qs))-1; sh = qs.mean()*4/(qs.std(ddof=1)*np.sqrt(4))
        d = mr.to_frame('ret').join(fac, how='inner').dropna()
        r = sm.OLS(d['ret']-d['RF'], sm.add_constant(d[fa.FACS])).fit(cov_type='HAC', cov_kwds={'maxlags': 3})
        return cg, sh, (1+r.params['const'])**12-1, r.tvalues['const']
    out = ["## Mean Holding Weight — top10/20/30 × 거래비용 (턴오버 편도, 분기리밸)",
           "| top-N | 편도턴오버 | gross α | net@10bp(t) | net@25bp(t) | net@25 CAGR | Sharpe |", "|---|---|---|---|---|---|---|"]
    for tn in (10, 20, 30):
        mg, _, turn = run(tn, 0.0); _, n10, _ = run(tn, 0.0010); _, n25, _ = run(tn, 0.0025)
        cg, _, ag, _ = metrics(mg); _, _, a10, t10 = metrics(n10); c25, s25, a25, t25 = metrics(n25)
        out.append(f"| top{tn} | {turn*100:.0f}% | {ag*100:+.1f}% | {a10*100:+.1f}%({t10:+.2f}) | {a25*100:+.1f}%({t25:+.2f}) | {c25*100:.1f}% | {s25:.2f} |")
    return "\n".join(out)

RUNS = {"signals": run_signals, "revalid": run_revalid, "ensemble": run_ensemble, "weighting": run_weighting, "mhwcost": run_mhwcost}

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    keys = list(RUNS) if which == "all" else [which]
    parts = ["# 검증 모음 (정제 유니버스, FF5+Mom Newey-West)\n"] + [RUNS[k]() for k in keys if k in RUNS]
    txt = "\n\n".join(parts); (fa.ROOT/"notes"/"validate.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
