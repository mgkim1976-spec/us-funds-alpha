#!/usr/bin/env python3
"""액티비스트 13F 직접 수집 (집중도 필터 우회) → data/activist_panel.parquet.
검증된 액티비스트 매니저 CIK의 13F-HR(2024+)을 EDGAR에서 받아 보유 파싱.
update_filings 함수 재사용. 후보 CIK 중 실제 13F-HR 제출분만 채택."""
import sys, importlib.util, json, time
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("uf", str(Path(__file__).resolve().parent/"update_filings.py"))
uf = importlib.util.module_from_spec(spec); spec.loader.exec_module(uf)

# EDGAR 조회로 확보한 후보 CIK (애매한 건 복수 포함 — 실제 13F-HR 제출분만 남김)
ACTIVISTS = {
    "Elliott": ["1791786"], "Starboard": ["1517137"], "ThirdPoint": ["1040273"],
    "Trian": ["1345471", "1345472"], "ValueAct": ["1418814", "1351069", "1395267"],
    "PershingSquare": ["1336528"], "JANA": ["1159159"], "Icahn": ["1412093", "921669", "1413902"],
    "Corvex": ["1535472"], "SachemHead": ["1582090"], "Politan": ["1885245"],
    "EngineNo1": ["1835549"], "MantleRidge": ["1695459"], "Ancora": ["1657660", "1446114"],
    "LandBuildings": ["1536520"], "Engaged": ["1559771"], "Legion": ["1560207"], "Inclusive": ["1817187"],
}

def name_of(cik):
    d = uf.get(f"https://data.sec.gov/submissions/CIK{uf.cik10(cik)}.json")
    if not d: return None
    try: return json.loads(d).get("name")
    except Exception: return None

def main():
    rows = []; coverage = []
    for act, ciks in ACTIVISTS.items():
        for cik in ciks:
            new = uf.list_13f_new(cik, "2023-12-31")  # 2024+ 13F-HR
            if not new: continue
            nm = name_of(cik); nf = 0; nh = 0
            for acc, fd, rd in new:
                accn = acc.replace("-", ""); doc = uf.info_table_doc(cik, accn)
                if not doc: continue
                xml = uf.get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{doc}")
                if not xml: continue
                try: holds = uf.parse_13f(xml)
                except Exception: continue
                tot = sum(v for _, v, _ in holds)
                if tot <= 0: continue
                for cusip, val, sh in holds:
                    rows.append((act, cik, rd, fd, cusip, val, val/tot*100, sh))
                nf += 1; nh += len(holds); time.sleep(0.1)
            if nf:
                coverage.append((act, cik, nm, nf, nh//nf)); print(f"  ✓ {act:14} {cik:>10} {str(nm)[:34]:36} filings {nf}, ~{nh//nf}종목", flush=True)
            time.sleep(0.15)
    df = pd.DataFrame(rows, columns=["activist", "manager", "reportDate", "filingDate", "cusip", "valUSD", "pctVal", "shares"])
    df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce"); df["reportDate"] = pd.to_datetime(df["reportDate"], errors="coerce")
    df.to_parquet(ROOT/"data"/"activist_panel.parquet", index=False)
    print(f"\n저장 activist_panel.parquet {df.shape} | 액티비스트 {df.activist.nunique()} | 분기 {df.reportDate.nunique()}")
    print(f"커버리지: {len(coverage)} CIK 채택")

if __name__ == "__main__":
    main()
