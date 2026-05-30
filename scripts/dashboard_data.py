#!/usr/bin/env python3
"""대시보드 데이터 (매일). 3구역: ①앙상블 소스비교(결합·MF·HF) ②뮤추얼펀드 개별시그널 ③헤지펀드 개별시그널.
검증통계·곡선은 card_stats.json(2024-2026). 라이브는 최신가격으로 리밸런싱 이후 추적. → dashboard/data.json"""
import sys, json, time, urllib.request, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa
ROOT, RAW = fa.ROOT, fa.RAW
TODAY = pd.Timestamp(dt.date.today())
def _qstart(t):
    qs = [pd.Timestamp(t.year, m, 1) for m in (3, 6, 9, 12)] + [pd.Timestamp(t.year-1, 12, 1)]
    return max([d for d in qs if d <= t])
REBAL = _qstart(TODAY)
NEXT_REBAL = min([d for d in [pd.Timestamp(REBAL.year, m, 1) for m in (3, 6, 9, 12)]+[pd.Timestamp(REBAL.year+1, 3, 1)] if d > REBAL])

# 카드 메타 (name·desc·note). 통계·곡선은 card_stats에서.
CARDS = {
 "comb": ("결합 앙상블 (MF + HF)", "뮤추얼펀드의 보유·신규매수 + 헤지펀드의 집중 확신", "프로젝트 최고 — 각 소스 승자 신호만 결합 (전부넣기보다 우월)"),
 "mf_ens": ("뮤추얼펀드 앙상블", "MF 세 신호(mhw·lnp·bi) z-결합", "폭넓은 보유·신규매수에 강함"),
 "hf_ens": ("헤지펀드 앙상블", "집중 헤지펀드 세 신호 z-결합", "집중 확신에 강함"),
 "mf_mhw": ("Mean Holding Weight", "많은 펀드가 크게 보유 (널리·두텁게)", "뮤추얼펀드가 우월(안정)"),
 "mf_lnp": ("Large New Positions", "여러 펀드의 신규 고확신 진입(≥0.5%)", "뮤추얼펀드 최강 신호"),
 "mf_bi":  ("Best-Ideas", "컨센서스 대비 초과보유 (active overweight)", "뮤추얼펀드는 분산적이라 약함"),
 "mf_rlc": ("Reallocation", "가격변동 빼고 실제로 사들인 종목", "최근(2024-26)엔 약화 — 레짐"),
 "hf_mhw": ("Mean Holding Weight", "많은 헤지펀드가 크게 보유", "집중 매니저라 보유자 적어 약함"),
 "hf_lnp": ("Large New Positions", "여러 헤지펀드 신규 고확신 진입", "안정적"),
 "hf_bi":  ("Best-Ideas", "컨센서스 대비 초과보유 (active overweight)", "헤지펀드 최강 — 집중 확신 압도"),
}
SECTIONS = [
 ("앙상블 — 소스별 비교", "결합이 최고 (+13.8%, t3.92)", ["comb", "mf_ens", "hf_ens"]),
 ("뮤추얼펀드 유니버스 · 개별 시그널", "~540 액티브 US 주식형 · 기존 방식", ["mf_mhw", "mf_lnp", "mf_bi", "mf_rlc"]),
 ("헤지펀드 유니버스 · 개별 시그널", "~3,100 집중 13F 매니저 · 기존 방식", ["hf_mhw", "hf_lnp", "hf_bi"]),
]

def hf_concentrated():
    d = pd.read_parquet(fa.DATA/"f13_panel.parquet")
    d = d[d["cusip"].str.len() == 9].copy().rename(columns={"manager": "fund"})
    d["w"] = d["pctVal"]/100.0; d["filingDate"] = pd.to_datetime(d["filingDate"])
    g = d.groupby(["fund", "reportDate"])
    st = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = st[(st.n >= 15) & (st.n <= 80) & (st.top10 >= 0.40)][["fund", "reportDate"]]
    return d.merge(keep, on=["fund", "reportDate"])

def fetch_prices(tickers):
    s = int(pd.Timestamp("2026-01-15").timestamp()); e = int((TODAY+pd.Timedelta(days=1)).timestamp())
    out = {}
    for tk in sorted(set(tickers)):
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1={s}&period2={e}&interval=1d",
                headers={"User-Agent": "Mozilla/5.0"}), timeout=20))
            r = j["chart"]["result"][0]; ts = r["timestamp"]
            adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or r["indicators"]["quote"][0]["close"]
            out[tk] = {pd.Timestamp(t, unit='s').strftime('%Y-%m-%d'): p for t, p in zip(ts, adj) if p}
        except Exception: pass
        time.sleep(0.12)
    return out

def main():
    figi = fa.figi_map()
    mf = fa.load_panel("holdings_panel_541.parquet")
    hf = hf_concentrated()
    names = mf.drop_duplicates('cusip').set_index('cusip')['name'].to_dict()
    pivot = fa.price_pivot()
    MFn = fa.score_stocks(fa.fund_timelines(mf), REBAL, figi)
    rc = fa.score_reallocation(fa.fund_timelines(mf), REBAL, figi, pivot)
    MFn["rlc"] = pd.to_numeric(MFn["cusip"].map(lambda c: rc.get(c, 0.0)), errors="coerce")
    HFn = fa.score_stocks(fa.fund_timelines(hf), REBAL, figi)

    def picks_df(key):
        if key == "comb":
            m = MFn[["cusip", "ticker", "hold", "z_mhw", "z_lnp"]].copy()
            h = HFn[["cusip", "z_bi"]].copy()
            d = m.merge(h, on="cusip", how="outer")
            for c in ["z_mhw", "z_lnp", "z_bi"]: d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
            d["sc"] = d[["z_mhw", "z_lnp", "z_bi"]].mean(axis=1); d = d[d.ticker.notna()]
            d["hold"] = d.get("hold", 1)
            return d.nlargest(30, "sc")
        src, sig = key.split("_"); df = MFn if src == "mf" else HFn
        col = "ens" if sig == "ens" else sig
        return df[df.hold >= 3].nlargest(30, col)

    picks = {k: picks_df(k) for k in CARDS}
    alltk = sorted(set(t for k in picks for t in picks[k]['ticker'].dropna()) | {"SPY"})
    px = fetch_prices(alltk)
    dates = sorted({d for t in px for d in px[t]}); dates = [d for d in dates if d >= REBAL.strftime('%Y-%m-%d')]
    cs = json.load(open(ROOT/"dashboard"/"card_stats.json")) if (ROOT/"dashboard"/"card_stats.json").exists() else {}

    def firstlast(p):
        av = [d for d in dates if d in p]; return (p[av[0]], p[av[-1]]) if len(av) >= 2 else (None, None)
    def port(tks, w):
        ser = []; base = {}
        for d in dates:
            num = ws = 0.0
            for t in tks:
                p = px.get(t, {})
                if t not in base: base[t] = p.get(dates[0]) or next((p[x] for x in dates if x in p), None)
                b = base.get(t)
                if b and d in p: num += w[t]*(p[d]/b-1); ws += w[t]
            ser.append(num/ws if ws > 0 else None)
        return (ser[-1]*100 if ser and ser[-1] is not None else 0.0)
    spy_ret = port(["SPY"], {"SPY": 1.0})

    def make(key):
        nm, desc, note = CARDS[key]; pdf = picks[key].copy()
        tks = pdf['ticker'].tolist(); n = len(tks)
        w = np.arange(n, 0, -1).astype(float); w = w/w.sum(); wm = dict(zip(tks, w))
        ret = port(tks, wm)
        holds = []
        for i, (_, r) in enumerate(pdf.iterrows()):
            b, last = firstlast(px.get(r['ticker'], {})); pr = (last/b-1)*100 if (b and last) else None
            holds.append(dict(ticker=r['ticker'], name=str(names.get(r['cusip'], r['ticker']))[:30],
                              funds=int(r.get('hold', 0)) if pd.notna(r.get('hold', 0)) else 0,
                              weight=round(w[i]*100, 1), ret=round(pr, 1) if pr is not None else None))
        st = cs.get(key, {})
        return dict(key=key, name=nm, desc=desc, note=note, weight="rank",
                    alpha=st.get('alpha', '–'), t=st.get('t', '–'), sharpe=st.get('sharpe', '–'),
                    cagr=st.get('cagr', '–'), sub="2024–2026 백테스트", bt_curve=st.get('curve', []),
                    since_rebal=round(ret, 2), vs_spy=round(ret-spy_ret, 2), holds=holds)

    sections = [{"title": t, "subtitle": sub, "cards": [make(k) for k in ks]} for t, sub, ks in SECTIONS]
    data = dict(generated=dt.date.today().strftime("%Y-%m-%d"), rebal=REBAL.strftime("%Y-%m-%d"),
                next_rebal=NEXT_REBAL.strftime("%Y-%m-%d"), bt_months=cs.get("_months", []), bt_spy=cs.get("_spy", []),
                spy_since_rebal=round(spy_ret, 2),
                note="MF=뮤추얼펀드(N-PORT) · HF=헤지펀드(13F 집중). 검증·곡선은 2024-2026(13F 가용기간). "
                     "결합=MF의 mhw·lnp + HF의 best-ideas. point-in-time·공시지연 반영. 투자 조언 아님.",
                sections=sections)
    json.dump(data, open(ROOT/"dashboard"/"data.json", "w"), ensure_ascii=False, indent=1)
    print(f"data.json: {sum(len(s['cards']) for s in sections)}카드 / SPY {spy_ret:+.1f}%")
    for s in sections:
        for c in s['cards']: print(f"  [{s['title'][:8]}] {c['name'][:24]}: {c['since_rebal']:+.1f}% α{c['alpha']}")

if __name__ == "__main__":
    main()
