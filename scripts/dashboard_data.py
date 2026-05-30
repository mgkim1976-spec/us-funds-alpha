#!/usr/bin/env python3
"""대시보드 데이터 생성 (매일 실행). 3개 검증 알파전략의 현재 포트폴리오 + 실시간 vs SPY.
전략: Mean Holding Weight(top20), Large New Positions(top30), Best-Ideas active-OW(top30).
point-in-time(filingDate≤REBAL). 최신 일별가격 재수집 → 리밸런싱 이후 성과 추적.
출력: dashboard/data.json
"""
import sys, json, time, urllib.request, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa
ROOT, RAW = fa.ROOT, fa.RAW
TODAY=pd.Timestamp(dt.date.today()); MINHOLD=3; STALE_DAYS=180
# 리밸런싱일 = 검증과 동일한 분기 그리드(3/6/9/12월 1일) 중 오늘 이하 최신 (분기 자동진행)
def _qstart(t):
    qs=[pd.Timestamp(t.year,m,1) for m in (3,6,9,12)]+[pd.Timestamp(t.year-1,12,1)]
    return max([d for d in qs if d<=t])
REBAL=_qstart(TODAY)
def _next_q(t):
    qs=[pd.Timestamp(t.year,m,1) for m in (3,6,9,12)]+[pd.Timestamp(t.year+1,3,1)]
    return min([d for d in qs if d>t])
NEXT_REBAL=_next_q(REBAL)

# 검증된 백테스트 통계(notes 결과 — net@25bp 기준)
STATS={
 "mhw":{"name":"Mean Holding Weight","desc":"≥15개 펀드가 평균적으로 크게 보유한 종목 (널리·두텁게)",
        "topn":30,"minhold":15,"weight":"equal","alpha":"+4.0%","t":"2.11","sharpe":"2.00","cagr":"22.6%","turn":"19%/q",
        "note":"비주식 제외+breadth≥15 정제. 헤드라인 +8.4%의 절반은 에너지/MLP 오염. ⚠레짐의존: 2022-24 알파 0(t0.2), 2024-26만 +5.4%(t2.4). 메가캡AI 레짐 의존."},
 "lnp":{"name":"Large New Positions","desc":"여러 펀드가 신규로 고확신 진입(≥0.5%)한 종목",
        "topn":30,"minhold":3,"weight":"equal","alpha":"+6.1%","t":"2.54","sharpe":"1.56","cagr":"27.0%","turn":"~","note":"정제후 거의 불변(원래 깨끗). ⚠전반집중: 2022-24 +9.3%(t3.8), 2024-26 +2.3%(t0.7) 약화. 베타 1.19."},
 "bi":{"name":"Best-Ideas (active overweight)","desc":"컨센서스 대비 초과보유가 큰 고확신 종목 (Cohen-Polk-Silli)",
       "topn":30,"minhold":5,"weight":"equal","alpha":"+4.5%","t":"2.12","sharpe":"1.94","cagr":"22.0%","turn":"~","note":"정제후 불변(깨끗). ⚠전반강·후반약: 2022-24 +5.3%(t3.4), 2024-26 +2.2%(t1.1) decay. 베타 0.90(가장 깨끗)."},
 "ens":{"name":"★ 앙상블 (z-결합·랭크가중)","desc":"3신호 z-score 결합 top30, 순위 가중 (레짐 상호보완)",
        "topn":30,"minhold":3,"weight":"rank","alpha":"+7.1%","t":"4.49","sharpe":"1.77","cagr":"28.6%","turn":"~",
        "note":"세션 최강 robust: 양쪽 하위기간 강유의(22-24 t2.3, 24-26 t4.3). 랭크가중이 동일가중(알파+6.2%/t4.0)보다 알파↑. 단 신호상관 0.91로 분산 제한적, in-sample."},
}

def load_panel():
    return fa.load_panel("holdings_panel_300.parquet", exclude_noneq=True)

def fresh_funds(h):
    """REBAL 기준 보유 나이≤STALE_DAYS인 펀드 집합 (stale 제외용). + 제외수."""
    sub=h[h['filingDate']<=REBAL].copy(); sub['reportDate']=pd.to_datetime(sub['reportDate'])
    latest=sub.sort_values('filingDate').groupby('fund').tail(1)
    age=(REBAL-latest['reportDate']).dt.days
    fresh=set(latest.loc[age<=STALE_DAYS,'fund'])
    return fresh, int((age>STALE_DAYS).sum())

def current_scores(h, fresh):
    """REBAL 시점 시그널 점수 (stale 제외 fresh 펀드만, 검증과 동일한 falib.score_stocks)."""
    figi = fa.figi_map()
    fw = fa.fund_timelines(h, funds=fresh)
    df = fa.score_stocks(fw, REBAL, figi)
    names = h.drop_duplicates('cusip').set_index('cusip')['name'].to_dict()
    df['name'] = df['cusip'].map(lambda c: names.get(c, c))
    return df

def fetch_prices(tickers):
    s=int(pd.Timestamp("2026-01-15").timestamp()); e=int((TODAY+pd.Timedelta(days=1)).timestamp())
    out={}
    for tk in sorted(set(tickers)):
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1={s}&period2={e}&interval=1d"
        try:
            j=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=20))
            r=j["chart"]["result"][0]; ts=r["timestamp"]
            adj=r["indicators"].get("adjclose",[{}])[0].get("adjclose") or r["indicators"]["quote"][0]["close"]
            out[tk]={pd.Timestamp(t,unit='s').strftime('%Y-%m-%d'):p for t,p in zip(ts,adj) if p}
        except Exception: pass
        time.sleep(0.15)
    return out

def asof_dates(h, fresh):
    """사용된(fresh) 펀드들의 report/filing/lag *분포*."""
    sub=h[(h['filingDate']<=REBAL)&(h['fund'].isin(fresh))].copy()
    sub['reportDate']=pd.to_datetime(sub['reportDate'])
    latest=sub.sort_values('filingDate').groupby('fund').tail(1).copy()
    latest['lag']=(latest['filingDate']-latest['reportDate']).dt.days
    age=(REBAL-latest['reportDate']).dt.days
    d=lambda x:x.strftime('%Y-%m-%d')
    return dict(
        n=len(latest),
        report_med=d(latest['reportDate'].median()),
        report_min=d(latest['reportDate'].min()), report_max=d(latest['reportDate'].max()),
        public_min=d(latest['filingDate'].min()), public_max=d(latest['filingDate'].max()),
        lag_min=int(latest['lag'].min()), lag_med=int(latest['lag'].median()), lag_max=int(latest['lag'].max()),
        age_med=int(age.median()), age_q25=int(age.quantile(.25)), age_q75=int(age.quantile(.75)), age_max=int(age.max()),
        stale180=int((age>180).sum()))

def rebal_changes(picks):
    """리밸런싱일이 바뀌면 직전 픽과 비교해 교체종목 산출 + 이력 저장."""
    hist_p=ROOT/"dashboard"/"picks_history.json"
    hist=json.load(open(hist_p)) if hist_p.exists() else {}
    cur={k:picks[k]['ticker'].tolist() for k in picks}
    rb=REBAL.strftime("%Y-%m-%d")
    changes={"is_new_rebal":False,"rebal":rb,"prev_rebal":None,"per_strategy":{}}
    prior=[d for d in sorted(hist) if d<rb]
    if rb not in hist and prior:
        pr=prior[-1]; changes["is_new_rebal"]=True; changes["prev_rebal"]=pr
        for k in picks:
            old=set(hist[pr].get(k,[])); new=set(cur[k])
            changes["per_strategy"][k]={"added":sorted(new-old),"dropped":sorted(old-new)}
    hist[rb]=cur; json.dump(hist,open(hist_p,"w"),ensure_ascii=False,indent=1)
    # best-effort macOS 알림
    if changes["is_new_rebal"]:
        msg=" / ".join(f"{STATS[k]['name'].split()[0]} +{len(v['added'])}/-{len(v['dropped'])}"
                       for k,v in changes["per_strategy"].items())
        import subprocess
        try: subprocess.run(["osascript","-e",
            f'display notification "{msg}" with title "US Funds Alpha 리밸런싱 {rb}"'],timeout=5)
        except Exception: pass
    return changes

def main():
    h=load_panel()
    fresh, n_stale = fresh_funds(h)
    df=current_scores(h, fresh)
    ad=asof_dates(h, fresh); ad["excluded_stale"]=n_stale; ad["used_funds"]=len(fresh)
    picks={k:df[df.hold>=STATS[k]["minhold"]].nlargest(STATS[k]["topn"],k) for k in STATS}
    rebchg=rebal_changes(picks)
    alltk=sorted(set(t for k in picks for t in picks[k]['ticker'])|{"SPY"})
    px=fetch_prices(alltk)
    spy=px.get("SPY",{})
    dates=sorted(set().union(*[set(px[t]) for t in px if px[t]]))
    dates=[d for d in dates if d>=REBAL.strftime('%Y-%m-%d')]

    def port_series(tickers, wmap=None):
        # REBAL 기준 가중 누적수익 (wmap=None이면 동일가중). 결측종목은 재정규화.
        W=wmap or {t:1.0/len(tickers) for t in tickers}
        base={}; ser=[]
        for d in dates:
            num=0.0; wsum=0.0
            for t in tickers:
                p=px.get(t,{})
                if t not in base: base[t]=p.get(dates[0]) or next((p[x] for x in dates if x in p),None)
                b=base.get(t)
                if b and d in p: num+=W[t]*(p[d]/b-1); wsum+=W[t]
            ser.append((d, num/wsum if wsum>0 else None))
        return ser
    def cum(tickers, wmap=None):
        s=port_series(tickers, wmap); last=[v for _,v in s if v is not None]
        return s, (last[-1]*100 if last else 0.0)
    def weight_map(pdf, scheme):
        tks=pdf['ticker'].tolist(); n=len(tks)
        w=np.arange(n,0,-1).astype(float) if scheme=="rank" else np.ones(n)  # pdf는 점수 내림차순
        w=w/w.sum(); return dict(zip(tks,w))
    def firstlast(p):
        avail=[d for d in dates if d in p]    # 윈도 내 실제 보유 거래일
        return (p[avail[0]], p[avail[-1]]) if len(avail)>=2 else (None,None)

    spy_s,spy_ret=cum(["SPY"])
    cs=json.load(open(ROOT/"dashboard"/"card_stats.json")) if (ROOT/"dashboard"/"card_stats.json").exists() else {}
    def make_card(k, size):
        base=STATS[k]; pdf=picks[k].head(size)           # picks[k]=nlargest(30); head(size)
        wmap=weight_map(pdf, base.get("weight","equal"))
        ser,ret=cum(pdf['ticker'].tolist(), wmap)
        holds=[]
        for _,r in pdf.iterrows():
            p=px.get(r['ticker'],{}); b,last=firstlast(p)
            pr=(last/b-1)*100 if (b and last) else None
            holds.append(dict(ticker=r['ticker'],name=str(r['name'])[:34],funds=int(r['hold']),
                              weight=round(wmap[r['ticker']]*100,1),ret=round(pr,1) if pr is not None else None))
        st=cs.get(f"{k}_{size}",{})
        return dict(key=f"{k}_{size}", name=f"{base['name']} · Top{size}", desc=base['desc'],
            weight=base.get("weight","equal"),
            alpha=st.get('alpha','–'), t=st.get('t','–'), sharpe=st.get('sharpe','–'),
            cagr=st.get('cagr','–'), sub=st.get('sub',''), note=base['note'],
            since_rebal=round(ret,2), vs_spy=round(ret-spy_ret,2),
            bt_curve=st.get('curve',[]),
            series=[{"d":d,"v":round(v*100,2) if v is not None else None} for d,v in ser], holds=holds)
    sections=[
        {"title":"구역 1 · 앙상블 (z-결합 · 랭크가중)","cards":[make_card("ens",10),make_card("ens",30)]},
        {"title":"구역 2 · 3개 시그널 · Top 10 (집중)","cards":[make_card("mhw",10),make_card("lnp",10),make_card("bi",10)]},
        {"title":"구역 3 · 3개 시그널 · Top 30 (분산)","cards":[make_card("mhw",30),make_card("lnp",30),make_card("bi",30)]},
    ]
    data=dict(generated=dt.date.today().strftime("%Y-%m-%d"),
              rebal=REBAL.strftime("%Y-%m-%d"), next_rebal=NEXT_REBAL.strftime("%Y-%m-%d"),
              asof=ad,
              bt_months=cs.get("_months",[]), bt_spy=cs.get("_spy",[]),
              lag_note=f"펀드마다 회계연도가 달라 공시일 상이(point-in-time, 각 펀드 최신 공개분 사용). "
                       f"보유 기준일(report) 범위 {ad['report_min']}~{ad['report_max']}(중앙값 {ad['report_med']}), "
                       f"공시 {ad['public_min']}~{ad['public_max']}, 지연 {ad['lag_min']}~{ad['lag_max']}일(중앙값 {ad['lag_med']}). "
                       f"형성시점 보유 데이터 나이 중앙값 {ad['age_med']}일(최대 {ad['age_max']}). "
                       f"신호 사용 펀드 {ad['used_funds']}개 (180일+ stale {ad['excluded_stale']}개 제외).",
              rebal_changes=rebchg,
              spy_since_rebal=round(spy_ret,2),
              spy_series=[{"d":d,"v":round(v*100,2) if v is not None else None} for d,v in spy_s],
              caveat="검증은 in-sample·2022-26·15분기·long-only(베타≈1)·점추정. 실전 알파 보장 아님. Top10=집중(알파↑·robustness↓), Top30=분산. 공시지연·decay 모니터링 필수.",
              sections=sections)
    (ROOT/"dashboard").mkdir(exist_ok=True)
    json.dump(data, open(ROOT/"dashboard"/"data.json","w"), ensure_ascii=False, indent=1)
    nc=sum(len(s['cards']) for s in sections)
    print(f"data.json 생성: {len(sections)}구역 {nc}카드, {len(dates)}거래일, SPY since-rebal {spy_ret:.1f}%")
    for sec in sections:
        for c in sec['cards']: print(f"  [{sec['title'][:6]}] {c['name']}: {c['since_rebal']:+.1f}% (vsSPY {c['vs_spy']:+.1f}) α{c['alpha']}")

if __name__=="__main__":
    main()
