#!/usr/bin/env python3
"""SC 13D 직접 수집 → data/sc13d_events.parquet. 검증된 액티비스트 CIK의 13D/13D-A 제출에서
제출헤더의 '대상회사(SUBJECT COMPANY) CIK'를 추출 → company_tickers로 티커 매핑.
재현: python3 scripts/sc13d_collect.py"""
import sys, importlib.util, json, re, time, urllib.request
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("uf", str(Path(__file__).resolve().parent/"update_filings.py"))
uf = importlib.util.module_from_spec(spec); spec.loader.exec_module(uf)
UA = uf.UA

# 액티비스트 13D 제출자 CIK (13F에서 검증한 엔티티)
ACT_CIK = {"Elliott": "1791786", "Starboard": "1517137", "ThirdPoint": "1040273", "Trian": "1345471",
           "ValueAct": "1418814", "PershingSquare": "1336528", "Icahn": "921669", "Corvex": "1535472",
           "SachemHead": "1582090", "Politan": "1885245", "EngineNo1": "1835549", "MantleRidge": "1695459",
           "Ancora": "1446114", "LandBuildings": "1536520", "Engaged": "1559771", "Legion": "1560207",
           "Inclusive": "1817187", "JANA": "1159159"}

def subject_cik(filer_cik, acc):
    """제출 .txt 헤더만 읽어 SUBJECT COMPANY 의 CIK 추출(엑시빗 전 ~수 KB).
    acc=대시포함 accession. 디렉터리는 대시제거, 파일명은 대시포함."""
    accn = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(filer_cik)}/{accn}/{acc}.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            buf = b""
            while b"<DOCUMENT>" not in buf and len(buf) < 30000:
                ch = r.read(4096)
                if not ch: break
                buf += ch
        txt = buf.decode("utf-8", "ignore")
        m = re.search(r"SUBJECT COMPANY:(.*?)(?:FILED BY:|$)", txt, re.S)
        if not m: return None
        c = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", m.group(1))
        return c.group(1).zfill(10) if c else None
    except Exception:
        return None

def main():
    # CIK → ticker 매핑 (SEC 공식)
    ct = json.loads(uf.get("https://www.sec.gov/files/company_tickers.json"))
    cik2tk = {str(v["cik_str"]).zfill(10): v["ticker"] for v in ct.values()}
    print(f"company_tickers: {len(cik2tk)} CIK→티커")

    rows = []
    for act, cik in ACT_CIK.items():
        data = uf.get(f"https://data.sec.gov/submissions/CIK{uf.cik10(cik)}.json")
        if not data: print(f"  ! {act} 조회 실패"); continue
        rec = json.loads(data).get("filings", {}).get("recent", {})
        forms = rec.get("form", []); fds = rec.get("filingDate", []); accs = rec.get("accessionNumber", [])
        n = 0
        for form, fd, acc in zip(forms, fds, accs):
            if form not in ("SC 13D", "SC 13D/A"): continue
            if fd < "2022-01-01": continue
            scik = subject_cik(cik, acc)
            tk = cik2tk.get(scik) if scik else None
            rows.append((act, cik, form, fd, scik, tk)); n += 1
            time.sleep(0.12)
        print(f"  {act:14} 13D/13DA {n}건", flush=True)
        time.sleep(0.1)
    df = pd.DataFrame(rows, columns=["activist", "filerCIK", "form", "filingDate", "subjectCIK", "ticker"])
    df["filingDate"] = pd.to_datetime(df["filingDate"])
    df.to_parquet(ROOT/"data"/"sc13d_events.parquet", index=False)
    init = df[df.form == "SC 13D"]
    print(f"\n저장 sc13d_events.parquet {df.shape} | 초기13D {len(init)} (티커매핑 {init.ticker.notna().sum()}) | 13D/A {len(df)-len(init)}")
    print(f"기간 {df.filingDate.min().date()}~{df.filingDate.max().date()} | 대상종목 {df.ticker.nunique()}")

if __name__ == "__main__":
    main()
