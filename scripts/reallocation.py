#!/usr/bin/env python3
"""Reallocation(R3) 분석 — 두 갈래를 한 파일에:
  redefine — '재배분' 정의 변형 6종 탐색(가격 drift 제거한 능동 매매), IR vs SPY
  validate — R3(능동/turnover) 검증(하위기간·플라시보) + 3 vs 4-신호 앙상블
사용: python3 scripts/reallocation.py [redefine|validate|all]  → notes/reallocation.md"""
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

def _setup():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates(); Rns = rebs[1:]+[pivot.index.max()]
    pc = {}
    def poa(d):
        k = d.strftime("%Y%m%d")
        if k not in pc:
            w = pivot.loc[d:d+pd.Timedelta(days=8)]; pc[k] = w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
        return pc[k]
    return h, figi, fw, pivot, rets, fac, rebs, Rns, poa

# ── redefine: 정의 변형 탐색 ───────────────────────────────────────────────
def run_redefine():
    h, figi, fw, pivot, rets, fac, rebs, Rns, poa = _setup()
    VARIANTS = ["orig", "active_net", "active_pos", "active_norm", "active_breadth", "net_simple"]
    def scores(R):
        acc = {v: defaultdict(float) for v in VARIANTS}; hold = defaultdict(int)
        for f, series in fw.items():
            fds = [d for d in series if d <= R]
            if len(fds) < 2:
                if fds:
                    for c in series[fds[-1]].index: hold[c] += 1
                continue
            cur, prev = series[fds[-1]], series[fds[-2]]
            for c in cur.index: hold[c] += 1
            p0, p1 = poa(pd.Timestamp(fds[-2])), poa(pd.Timestamp(fds[-1]))
            def rstk(c):
                t = figi.get(c)
                return (p1[t]/p0[t]-1) if (t and t in p0 and t in p1 and not np.isnan(p0[t]) and not np.isnan(p1[t]) and p0[t] > 0) else 0.0
            rfund = sum(prev[c]*rstk(c) for c in prev.index) / (sum(prev.values) or 1)
            idx = cur.index.union(prev.index)
            dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0); dlt = dcur - dprev
            turn = float(dlt.abs().sum()) or 1e-9
            for c in idx:
                act = dcur[c] - dprev[c]*(1+rstk(c))/(1+rfund)
                acc["orig"][c] += (dlt[c]/turn) if dlt[c] > 0 else 0
                acc["active_net"][c] += act; acc["active_pos"][c] += max(0.0, act); acc["active_norm"][c] += act/turn
                if act > 0.0005: acc["active_breadth"][c] += 1
                elif act < -0.0005: acc["active_breadth"][c] -= 1
                acc["net_simple"][c] += dlt[c]
        rows = [[c, figi[c], hold[c]] + [acc[v].get(c, 0.0) for v in VARIANTS] for c in hold if hold[c] >= 3 and figi.get(c)]
        d = pd.DataFrame(rows, columns=["cusip", "ticker", "hold"]+VARIANTS)
        for v in VARIANTS: d[v] = pd.to_numeric(d[v], errors="coerce")
        return d.dropna(subset=VARIANTS)
    PER = {R: scores(R) for R in rebs}
    def ir(s):
        q = ((1+s).resample("QE").prod()-1).dropna()
        spy_q = pd.Series([(poa(Rn).get("SPY", np.nan)/poa(R).get("SPY", np.nan)-1) for R, Rn in zip(rebs, Rns)],
                          index=[pd.Timestamp(r) for r in rebs]).reindex(q.index, method="nearest")
        act = (q.values - spy_q.values); act = act[~np.isnan(act)]
        return act.mean()*4/(act.std(ddof=1)*np.sqrt(4)) if len(act) > 2 else np.nan
    names = {"orig":"R0 원래(Δw/turnover,>0)","active_net":"R1 능동순재배분","active_pos":"R2 능동매수만",
             "active_norm":"R3 능동/turnover","active_breadth":"R4 능동 breadth","net_simple":"R5 단순Δw"}
    out = ["# Reallocation Intensity 재정의 (IR 재현 시도)\n",
           "가설: '재배분'=가격 drift 뺀 능동 매매. long-only top30, FF5+Mom.\n",
           "| 정의 | CAGR | Sharpe | 알파 | t | **IR vs SPY** |", "|---|---|---|---|---|---|"]
    res = []
    for v in VARIANTS:
        s = fa.basket_daily(rets, {R: PER[R].nlargest(30, v)["ticker"].tolist() for R in rebs}, rebs)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); i = ir(s); res.append((v, i, a, t))
        out.append(f"| {names[v]} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | **{i:+.2f}** |")
    best = max(res, key=lambda r: r[1])
    out.append(f"\n최고 재현: **{names[best[0]]}** IR {best[1]:+.2f} (알파 {best[2]*100:+.1f}%, t{best[3]:+.2f}).")
    return "\n".join(out)

# ── validate: R3 검증 + 앙상블 ────────────────────────────────────────────
def run_validate():
    h, figi, fw, pivot, rets, fac, rebs, Rns, poa = _setup()
    def realloc_scores(R):
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
            idx = cur.index.union(prev.index); dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0)
            turn = float((dcur-dprev).abs().sum()) or 1e-9
            for c in idx: acc[c] += (dcur[c] - dprev[c]*(1+rstk(c))/(1+rfund))/turn
        return acc
    PER = {}
    for R in rebs:
        d = fa.score_stocks(fw, R, figi)
        rc = realloc_scores(R); d["realloc"] = pd.to_numeric(d["cusip"].map(lambda c: rc.get(c, 0.0)), errors="coerce")
        sd = d["realloc"].std(); d["z_realloc"] = (d["realloc"]-d["realloc"].mean())/(sd if sd else 1)
        d["ens4"] = d[["z_mhw", "z_lnp", "z_bi", "z_realloc"]].mean(axis=1); PER[R] = d
    def basket(col, mh=3, scheme="equal"):
        return fa.basket_daily(rets, {R: PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"].tolist() for R in rebs}, rebs, scheme)
    def row(s):
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        return cg, sh, a, t, ae, te, al, tl
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
    out = ["# Reallocation(R3) 검증 + 4-신호 앙상블\n",
           "## R3 단독 (능동/turnover, top30 동일가중)", "| 알파 | t | 22-24 | 24-26 | 플라시보(CAGR/초과) |", "|---|---|---|---|---|"]
    cg, sh, a, t, ae, te, al, tl = row(basket("realloc")); pc, pe = placebo("realloc")
    out.append(f"| {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) | {pc:.0f}/{pe:.0f} |")
    out += ["\n## 3-신호 vs 4-신호 앙상블 (z-결합 top30 랭크가중)",
            "| 앙상블 | CAGR | Sharpe | 알파 | t | 22-24 | 24-26 |", "|---|---|---|---|---|---|---|"]
    for lab, col in [("3-신호 (mhw+lnp+bi)", "ens"), ("4-신호 (+reallocation)", "ens4")]:
        cg, sh, a, t, ae, te, al, tl = row(basket(col, 3, "rank"))
        out.append(f"| {lab} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | {ae*100:+.1f}%(t{te:+.1f}) | {al*100:+.1f}%(t{tl:+.1f}) |")
    return "\n".join(out)

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    parts = []
    if which in ("redefine", "all"): parts.append(run_redefine())
    if which in ("validate", "all"): parts.append(run_validate())
    txt = "\n\n---\n\n".join(parts)
    (fa.ROOT/"notes"/"reallocation.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
