#!/usr/bin/env python3
"""액티비스트 연구 — 세 갈래를 한 파일에:
  collect — 검증 액티비스트 CIK의 13F-HR 직접수집(집중도 필터 우회) → data/activist_panel.parquet
  signal  — 13F 프록시 신호(합의/확신/신규) 백테스트 (작동 안 함 기록)
  event   — SC 13D 이벤트 스터디(Brav-Jiang): 공시일 전후 시장조정 CAR
사용: python3 scripts/activist_research.py [collect|signal|event|all]  (기본 event)"""
import sys, json, time
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa, update_filings as uf

ACTIVISTS = {
    "Elliott": ["1791786"], "Starboard": ["1517137"], "ThirdPoint": ["1040273"],
    "Trian": ["1345471", "1345472"], "ValueAct": ["1418814", "1351069", "1395267"],
    "PershingSquare": ["1336528"], "JANA": ["1159159"], "Icahn": ["1412093", "921669", "1413902"],
    "Corvex": ["1535472"], "SachemHead": ["1582090"], "Politan": ["1885245"],
    "EngineNo1": ["1835549"], "MantleRidge": ["1695459"], "Ancora": ["1657660", "1446114"],
    "LandBuildings": ["1536520"], "Engaged": ["1559771"], "Legion": ["1560207"], "Inclusive": ["1817187"],
}

# ── collect: 액티비스트 13F-HR 직접 수집 ──────────────────────────────────
def run_collect():
    def name_of(cik):
        d = uf.get(f"https://data.sec.gov/submissions/CIK{uf.cik10(cik)}.json")
        try: return json.loads(d).get("name") if d else None
        except Exception: return None
    rows = []; cov = 0
    for act, ciks in ACTIVISTS.items():
        for cik in ciks:
            new = uf.list_13f_new(cik, "2023-12-31")
            if not new: continue
            nm = name_of(cik); nf = nh = 0
            for acc, fd, rd in new:
                accn = acc.replace("-", ""); doc = uf.info_table_doc(cik, accn)
                if not doc: continue
                xml = uf.get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{doc}")
                if not xml: continue
                try: holds = uf.parse_13f(xml)
                except Exception: continue
                tot = sum(v for _, v, _ in holds)
                if tot <= 0: continue
                for cusip, val, sh in holds: rows.append((act, cik, rd, fd, cusip, val, val/tot*100, sh))
                nf += 1; nh += len(holds); time.sleep(0.1)
            if nf: cov += 1; print(f"  ✓ {act:14} {cik:>10} {str(nm)[:34]:36} filings {nf}, ~{nh//nf}종목", flush=True)
            time.sleep(0.15)
    df = pd.DataFrame(rows, columns=["activist", "manager", "reportDate", "filingDate", "cusip", "valUSD", "pctVal", "shares"])
    df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce"); df["reportDate"] = pd.to_datetime(df["reportDate"], errors="coerce")
    df.to_parquet(ROOT/"data"/"activist_panel.parquet", index=False)
    print(f"\n저장 activist_panel.parquet {df.shape} | 액티비스트 {df.activist.nunique()} | {cov} CIK 채택")

# ── signal: 13F 프록시 신호 (작동 안 함 기록) ─────────────────────────────
def run_signal():
    REBS = fa.rebalance_dates("2024-09-01", "2026-03-01"); MAXH, MINPOS = 50, 1.0
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    df = pd.read_parquet(fa.DATA/"activist_panel.parquet")
    df = df[df["cusip"].str.len() == 9].copy(); df = df[~df["cusip"].isin(fa.noneq_cusips(figi))]
    df["filingDate"] = pd.to_datetime(df["filingDate"])
    fw = {}
    for m, g in df.groupby("manager"):
        snaps = {}
        for fd, gg in g.groupby("filingDate"):
            if gg["cusip"].nunique() > MAXH: continue
            sig = gg[gg["pctVal"] >= MINPOS].groupby("cusip")["pctVal"].sum()/100.0
            if len(sig): snaps[pd.Timestamp(fd)] = sig
        if snaps: fw[m] = dict(sorted(snaps.items()))
    print(f"집중 액티비스트 {len(fw)}")
    def score(R):
        held = defaultdict(int); conv = defaultdict(float); new = defaultdict(int)
        for m, series in fw.items():
            fds = [d for d in series if d <= R]
            if not fds: continue
            cur = series[fds[-1]]; prev = series[fds[-2]] if len(fds) >= 2 else pd.Series(dtype=float)
            for c, w in cur.items():
                if not figi.get(c): continue
                held[c] += 1; conv[c] += w
                if c not in prev.index: new[c] += 1
        return held, conv, new
    def picks(metric, n=20):
        out = {}
        for R in REBS:
            h, cv, nw = score(R); src = {"held": h, "conv": cv, "new": nw}[metric]
            items = sorted(((figi[c], v) for c, v in src.items() if figi.get(c) and v > 0), key=lambda x: x[1], reverse=True)
            seen = set(); tk = []
            for t, v in items:
                if t not in seen: seen.add(t); tk.append(t)
                if len(tk) >= n: break
            out[R] = tk
        return out
    print(f"\n{'신호':22} {'α':>8} {'t':>6} {'Sharpe':>7}")
    for metric, lbl in [("conv", "활동가-확신"), ("held", "활동가-합의"), ("new", "활동가-신규진입")]:
        for n in (10, 20):
            s = fa.basket_daily(rets, picks(metric, n), REBS, "rank")
            if len(s) < 40: print(f"{lbl+f' top{n}':22} 데이터부족"); continue
            _, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
            print(f"{lbl+f' top{n}':22} {a*100:+7.1f}% {t:6.2f} {sh:7.2f}")
    print("주: 13F 45일 지연이라 13D 발표 팝이 아닌 *이후 드리프트* — 소표본·미작동.")

# ── event: SC 13D 이벤트 스터디 ───────────────────────────────────────────
WINDOWS = [("사전매집 [-20,-1]", -20, -1), ("발표 [0,+1]", 0, 1), ("발표 [0,+5]", 0, 5),
           ("드리프트 [+2,+21]", 2, 21), ("드리프트 [+2,+63]", 2, 63),
           ("드리프트 [+2,+126]", 2, 126), ("드리프트 [+2,+252]", 2, 252)]

def run_event():
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); idx = rets.index
    if "SPY" not in rets.columns: raise SystemExit("SPY 가격 없음")
    ev = pd.read_parquet(fa.DATA/"sc13d_events.parquet"); ev = ev[ev["ticker"].notna()].copy()
    init = ev[ev.form == "SC 13D"]
    print(f"13D 이벤트: 초기 {len(init)} | 전체 {len(ev)} | {ev.filingDate.min().date()}~{ev.filingDate.max().date()}")
    def car(tk, t0i, a, b):
        lo, hi = t0i+a, t0i+b
        if lo < 0 or hi >= len(rets): return np.nan
        ar = rets[tk].iloc[lo:hi+1] - rets["SPY"].iloc[lo:hi+1]
        return float(ar.sum()) if not ar.isna().any() else np.nan
    def study(e, label):
        res = {w[0]: [] for w in WINDOWS}; used = 0
        for _, r in e.iterrows():
            tk = r["ticker"]
            if tk not in rets.columns: continue
            pos = idx.searchsorted(r["filingDate"])
            if pos >= len(idx): continue
            ok = False
            for name, a, b in WINDOWS:
                v = car(tk, pos, a, b)
                if not np.isnan(v): res[name].append(v); ok = True
            used += ok
        print(f"\n=== {label} (이벤트 {used}건) ===\n{'윈도우':22} {'평균 CAR':>9} {'t':>6} {'양(+)%':>7} {'N':>4}")
        for name, _, _ in WINDOWS:
            v = np.array(res[name])
            if len(v) < 3: print(f"{name:22} {'표본부족':>9}"); continue
            t = v.mean()/(v.std(ddof=1)/np.sqrt(len(v))) if v.std() else 0
            print(f"{name:22} {v.mean()*100:+8.1f}% {t:6.2f} {100*np.mean(v>0):6.0f}% {len(v):4}")
    study(init, "초기 SC 13D (Brav-Jiang 발표효과)"); study(ev, "전체 13D + 13D/A")
    print("\n=== 매매가능: 발표 +1일 진입, 보유기간별 평균 초과수익 (초기 13D) ===")
    for H in (21, 63, 126):
        rr = []
        for _, r in init.iterrows():
            tk = r["ticker"]
            if tk not in rets.columns: continue
            pos = idx.searchsorted(r["filingDate"]) + 1
            if pos+H >= len(idx) or pos < 0: continue
            ar = rets[tk].iloc[pos:pos+H] - rets["SPY"].iloc[pos:pos+H]
            if not ar.isna().any(): rr.append(ar.sum())
        if len(rr) >= 3:
            rr = np.array(rr); t = rr.mean()/(rr.std(ddof=1)/np.sqrt(len(rr)))
            print(f"  보유 {H:>3}일: {rr.mean()*100:+5.1f}% (t{t:4.2f}, 양 {100*np.mean(rr>0):.0f}%, N{len(rr)})")

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "event"
    if which in ("collect", "all"): run_collect()
    if which in ("signal", "all"): run_signal()
    if which in ("event", "all"): run_event()

if __name__ == "__main__":
    main()
