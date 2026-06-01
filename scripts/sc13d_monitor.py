#!/usr/bin/env python3
"""일별 13D 모니터 → dashboard/sc13d.json. 검증 액티비스트 CIK의 최근 13D(신규·수정) 공시를
EDGAR submissions에서 받아, 대상 티커·공시일·공시이후 수익(시장조정)을 피드로. daily_update에서 호출.
폼: SC 13D / SCHEDULE 13D (+/A). 2024 SEC 현대화로 코드가 SCHEDULE 13D 로 바뀜."""
import sys, json, re, datetime as dt
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts"))
import falib as fa, sc13d_collect as sc, fetch_prices_300 as fp
uf = sc.uf
LOOKBACK_AMEND = 270   # 수정공시: 최근 270일 (캠페인 스레드에 후속 13D/A를 충분히 묶기 위함)
LOOKBACK_INIT = 365    # 신규 13D(캠페인 개시)는 드물어 더 길게
FORMS_INIT = {"SC 13D", "SCHEDULE 13D"}
FORMS_AMEND = {"SC 13D/A", "SCHEDULE 13D/A"}
# Item 4(Purpose of Transaction) 키워드 → 캠페인 목적 태그
PURP = [("이사회·이사", r"board of director|director nominee|nominat|proxy contest|board seat|to elect"),
        ("매각·합병", r"strategic alternativ|sale of the|\bmerger\b|acquisition|business combination|take[ -]private|sell the"),
        ("저평가·자본환원", r"undervalued|repurchase|buyback|return of capital|capital allocation|special dividend"),
        ("운영·분사", r"operational|cost reduction|margin|spin[ -]?off|divest|separat"),
        ("지배구조", r"governance|bylaw|charter|declassif")]

def enrich(filer_cik, acc):
    """공시 원문 링크 + Item4 목적 태그 + 레터 첨부 여부 (구조화 13D XML)."""
    accn = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(filer_cik)}/{accn}/"
    purpose = None; letter = False
    xml = uf.get(url + "primary_doc.xml")
    if xml:
        t = xml.decode("utf-8", "ignore")
        m4 = re.search(r"<item4\b[^>]*>(.*?)</item4>", t, re.S)
        if m4:
            txt = re.sub(r"<[^>]+>", " ", m4.group(1)).lower()
            purpose = next((tag for tag, pat in PURP if re.search(pat, txt)), "일반(13D)")
        ex = re.search(r"<(?:item7|filedExhibits)\b[^>]*>(.*?)</(?:item7|filedExhibits)>", t, re.S)
        if ex and "letter" in re.sub(r"<[^>]+>", " ", ex.group(1)).lower(): letter = True
    return url, purpose, letter

def main():
    since_a = (dt.date.today() - dt.timedelta(days=LOOKBACK_AMEND)).isoformat()
    since_i = (dt.date.today() - dt.timedelta(days=LOOKBACK_INIT)).isoformat()
    ct = json.loads(uf.get("https://www.sec.gov/files/company_tickers.json"))
    cik2tk = {str(v["cik_str"]).zfill(10): (v["ticker"], v["title"]) for v in ct.values()}
    evs = []; subs = {}                              # subs: act→(cik, recent) — 개시 역추적용
    for act, cik in sc.ACT_CIK.items():
        data = uf.get(f"https://data.sec.gov/submissions/CIK{uf.cik10(cik)}.json")
        if not data: continue
        rec = json.loads(data).get("filings", {}).get("recent", {})
        subs[act] = (cik, rec)
        for form, fd, acc in zip(rec.get("form", []), rec.get("filingDate", []), rec.get("accessionNumber", [])):
            isinit = form in FORMS_INIT
            if isinit:
                if fd < since_i: continue          # 신규: 365일
            elif form in FORMS_AMEND:
                if fd < since_a: continue          # 수정: 270일
            else:
                continue
            scik = sc.subject_cik(cik, acc)
            tk, nm = cik2tk.get(scik, (None, None))
            evs.append(dict(activist=act, date=fd, form=form, ticker=tk, name=nm,
                            new=isinit, subject=scik, filerCIK=cik, acc=acc))
    # 가격: 대상 티커 공시이후 수익(시장조정 vs SPY)
    px = fa.price_pivot()  # date×ticker adjclose
    tks = sorted({e["ticker"] for e in evs if e["ticker"]})
    miss = [t for t in tks if t not in px.columns]
    if miss:
        add = fp.yahoo(miss)
        if len(add):
            full = pd.read_parquet(fa.DATA/"prices_full.parquet")
            pd.concat([full, add]).drop_duplicates(["ticker", "date"]).to_parquet(fa.DATA/"prices_full.parquet", index=False)
            px = fa.price_pivot()
    spy = px["SPY"].dropna() if "SPY" in px.columns else None
    def ret_since(t, date):                          # 공시일 이후 시장조정(−SPY) 초과수익
        if not t or t not in px.columns or spy is None: return None
        s = px[t].dropna(); d0 = pd.Timestamp(date)
        on = s.index[s.index >= d0]; spon = spy.index[spy.index >= d0]
        if len(on) == 0 or len(spon) == 0: return None
        p0 = s.loc[on[0]]; p1 = s.iloc[-1]; sp0 = spy.loc[spon[0]]; sp1 = spy.iloc[-1]
        if p0 > 0 and sp0 > 0 and not pd.isna(p1) and not pd.isna(sp1):
            return round(((p1/p0-1) - (sp1/sp0-1))*100, 1)
        return None
    for e in evs:
        e["ret"] = ret_since(e["ticker"], e["date"])
    # ── 캠페인 스레드: (액티비스트·종목)별로 신규 13D + 후속 13D/A 묶기 ──
    withtk = [e for e in evs if e["ticker"]]
    inits = [e for e in withtk if e["new"]]
    amends = sorted([e for e in withtk if not e["new"]], key=lambda e: e["date"], reverse=True)
    keep = inits + amends[:max(20, 44 - len(inits))]   # 표시·목적/레터 보강 대상
    for e in keep:
        e["url"], e["purpose"], e["letter"] = enrich(e["filerCIK"], e["acc"])
    groups = {}
    for e in keep:
        groups.setdefault((e["activist"], e["ticker"]), []).append(e)
    # ── 표적 매칭: 개시(신규) 없는 캠페인에 한해, 같은 대상 회사의 과거 개시 13D를 역추적해 머리로 ──
    SCAN_CAP = 40                                      # 캠페인당 subject_cik 추가호출 상한
    sc_cache = {}; backfilled = 0
    for (act, tk), fl in groups.items():
        if any(e["new"] for e in fl) or act not in subs: continue
        subject = next((e["subject"] for e in fl if e.get("subject")), None)
        if not subject: continue
        cik, rec = subs[act]
        cand = sorted([(acc, fd) for form, fd, acc in
                       zip(rec.get("form", []), rec.get("filingDate", []), rec.get("accessionNumber", []))
                       if form in FORMS_INIT], key=lambda x: x[1], reverse=True)
        earliest = min(e["date"] for e in fl); opener = None; calls = 0
        for acc, fd in cand:
            if fd > earliest: continue                 # 개시는 후속(수정)보다 앞서야
            s = sc_cache.get((act, acc))
            if s is None:
                if calls >= SCAN_CAP: break
                s = sc.subject_cik(cik, acc); sc_cache[(act, acc)] = s; calls += 1
            if s == subject: opener = (acc, fd); break # 후속 직전의 가장 최근 개시 = 현 캠페인 개시
        if opener:
            acc, fd = opener; url, purpose, letter = enrich(cik, acc)
            # 역추적 개시의 ret는 비움 — 수년 누적 시장조정값이라 최근 공시(수개월)와 한 열에 섞으면 오해
            fl.append(dict(activist=act, date=fd, form="SCHEDULE 13D", ticker=tk,
                           name=fl[0].get("name"), new=True, subject=subject, ret=None,
                           url=url, purpose=purpose, letter=letter, backfilled=True))
            backfilled += 1
    def rep_purpose(fl):                               # 캠페인 대표 목적: 최신·구체 우선
        for e in fl:
            if e.get("purpose") and e["purpose"] != "일반(13D)": return e["purpose"]
        return next((e["purpose"] for e in fl if e.get("purpose")), None)
    campaigns = []
    for (act, tk), fl in groups.items():
        fl = sorted(fl, key=lambda e: e["date"], reverse=True)   # 최신순
        head = fl[0]
        campaigns.append(dict(
            activist=act, ticker=tk, name=next((e["name"] for e in fl if e["name"]), None),
            purpose=rep_purpose(fl), latest=head["date"], latest_ret=head["ret"],
            n=len(fl), has_initial=any(e["new"] for e in fl),
            letter=any(e.get("letter") for e in fl),
            filings=[dict(date=e["date"], form=e["form"], new=e["new"], ret=e["ret"],
                          purpose=e.get("purpose"), letter=e.get("letter"), url=e["url"],
                          backfilled=e.get("backfilled", False)) for e in fl]))
    campaigns.sort(key=lambda c: c["latest"], reverse=True)
    n_init_camp = sum(c["has_initial"] for c in campaigns)
    out = dict(generated=dt.date.today().strftime("%Y-%m-%d"), lookback_amend=LOOKBACK_AMEND, lookback_init=LOOKBACK_INIT,
               announce_note="발표 [0,+1] 평균 +5.5% (t4.34) · +1일 진입·21일 보유 +5.8% (t3.76) — sc13d.md",
               n_total=len(withtk), n_new=len(inits),
               n_campaigns=len(campaigns), n_initial_campaigns=n_init_camp,
               campaigns=campaigns)
    json.dump(out, open(ROOT/"dashboard"/"sc13d.json", "w"), ensure_ascii=False, indent=1)
    print(f"sc13d.json: 필링 {out['n_total']}건(신규 {out['n_new']}) → 캠페인 {len(campaigns)}개(개시포착 {n_init_camp}, 그중 역추적 {backfilled})")
    for c in campaigns[:8]:
        print(f"  {c['latest']} {c['activist']:12} {str(c['ticker']):6} {'개시' if c['has_initial'] else '후속'} "
              f"{c['n']}건 이후{c['latest_ret']}% | 목적 {c.get('purpose')} | 레터 {c['letter']}")

if __name__ == "__main__":
    main()
