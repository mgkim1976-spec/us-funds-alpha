#!/bin/bash
# 일일 갱신: ①두 소스 증분 수집(N-PORT 541 + 13F 헤지펀드) → ②최신 가격으로 대시보드 데이터 생성
cd /Users/mg_mac/MGPrj/us_funds_alpha || exit 1
PY=/Users/mg_mac/.pyenv/versions/3.13.12/bin/python3
echo "=== $(date) daily_update 시작 ==="
"$PY" scripts/update_filings.py all   # MF(541) + HF(13F)
"$PY" scripts/dashboard_data.py
echo "=== $(date) 완료 ==="
