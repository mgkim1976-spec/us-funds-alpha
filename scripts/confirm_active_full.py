#!/usr/bin/env python3
"""1900 액티브 풀 → N-PORT 벌크 EC%/US% 확정 → 전체 확정 US 주식형.
출력: data/universe_confirmed_full.json (EC%≥80 & 미국주식≥70)"""
import zipfile, io, csv, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT/"data"/"raw"/"nport_bulk"/"2024q4_nport.zip"
EQ = {"EC", "EP"}

def main():
    uni = json.load(open(ROOT/"data"/"universe_active_full.json"))
    cand = set(uni); z = zipfile.ZipFile(ZIP)
    acc2ser, net = {}, {}
    with z.open("FUND_REPORTED_INFO.tsv") as f:
        for r in csv.DictReader(io.TextIOWrapper(f, 'utf-8'), delimiter='\t'):
            sid = r.get("SERIES_ID", "")
            if sid in cand:
                acc2ser[r["ACCESSION_NUMBER"]] = sid
                try: net[r["ACCESSION_NUMBER"]] = float(r.get("NET_ASSETS") or "nan")
                except: net[r["ACCESSION_NUMBER"]] = float("nan")
    print(f"1900 중 2024q4 제출: {len(acc2ser)}", flush=True)
    ec = dict.fromkeys(acc2ser, 0.0); usec = dict.fromkeys(acc2ser, 0.0); tot = dict.fromkeys(acc2ser, 0.0)
    with z.open("FUND_REPORTED_HOLDING.tsv") as f:
        tw = io.TextIOWrapper(f, 'utf-8'); hdr = tw.readline().rstrip("\n").split("\t")
        iA, iV, iC, iK = (hdr.index(x) for x in ["ACCESSION_NUMBER", "CURRENCY_VALUE", "ASSET_CAT", "INVESTMENT_COUNTRY"])
        n = 0
        for line in tw:
            n += 1; p = line.rstrip("\n").split("\t"); acc = p[iA]
            if acc not in ec: continue
            try: v = float(p[iV])
            except: continue
            tot[acc] += v
            if p[iC] in EQ:
                ec[acc] += v
                if p[iK] == "US": usec[acc] += v
    confirmed = {}; ratios = []
    for acc, sid in acc2ser.items():
        na = net.get(acc, float("nan"))
        denom = na if (na and na == na and na > 0) else tot[acc]
        if not denom: continue
        ecp = ec[acc]/denom; usq = (usec[acc]/ec[acc]) if ec[acc] > 0 else 0.0
        ratios.append((ecp, usq))
        if ecp >= 0.80 and usq >= 0.70:
            confirmed[sid] = {"seriesId": sid, "name": uni[sid]["name"], "aum": uni[sid].get("aum"),
                              "ec": round(ecp, 2), "us": round(usq, 2)}
    # 임계값 민감도 (공급 곡선)
    print("\n임계값별 통과 펀드 수 (공급 곡선):")
    for ecmin, usmin in [(0.80, 0.70), (0.70, 0.60), (0.60, 0.50), (0.80, 0.0), (0.50, 0.0)]:
        c = sum(1 for e, u in ratios if e >= ecmin and u >= usmin)
        print(f"  EC≥{ecmin:.0%} & US≥{usmin:.0%}: {c}")
    json.dump(confirmed, open(ROOT/"data"/"universe_confirmed_full.json", "w"), indent=1)
    print(f"\n전체 확정 US 주식형: {len(confirmed)} (1900 중, 제출분 {len(acc2ser)} 기준)")
    print(f"  → 기존 541 대비 +{len(confirmed)-541}")

if __name__ == "__main__":
    main()
