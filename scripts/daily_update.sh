#!/bin/bash
# 일일 갱신: ①두 소스 증분 수집(N-PORT 541 + 13F 헤지펀드) → ②최신 가격으로 대시보드 데이터 생성
cd "$(dirname "$0")/.." || exit 1
PY=${PY:-$(command -v python3)}
echo "=== $(date) daily_update 시작 ==="
"$PY" scripts/update_filings.py all   # MF(541) + HF(13F)
"$PY" scripts/sc13d_monitor.py        # 액티비스트 13D 알림 피드 → dashboard/sc13d.json
"$PY" scripts/dashboard_data.py
echo "=== $(date) 완료 ==="
