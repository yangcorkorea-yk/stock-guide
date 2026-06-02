"""
섹터 로테이션 히트맵 데이터 사전 계산.

매일 GH Actions cron이 실행:
  1. SECTORS 카탈로그 22개 그룹의 상위 5종목 평균 수익률 계산
  2. data/sector_heatmap.json 저장
  3. 변경 시 commit → 사용자 접속 시 LLM/Alpaca 호출 0

환경변수: ALPACA_API_KEY, ALPACA_SECRET_KEY
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", os.getenv("ALPACA_API_KEY") or "dummy")
os.environ.setdefault("ALPACA_SECRET_KEY", os.getenv("ALPACA_SECRET_KEY") or "dummy")

from analysis import sector_heatmap_data

OUT = ROOT / "data" / "sector_heatmap.json"


def main():
    print(f"실행 시점: {datetime.now(timezone.utc).isoformat()}")
    print("섹터 히트맵 계산 중...")
    data = sector_heatmap_data()
    if not data:
        print("⚠️ 데이터 0건 (Alpaca 호출 실패 가능). 저장 건너뜀.")
        sys.exit(0)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sectors": data,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 저장: {OUT} ({len(data)}개 섹터)")
    # 상위 5 / 하위 5 미리보기
    ranked = sorted(data, key=lambda x: -(x.get("m3") if x.get("m3") is not None else -999))
    print("\n[상위 5 (3개월 기준)]")
    for r in ranked[:5]:
        print(f"  {r['name']:18s} 1주 {r.get('w1') or 0:+.2f}%  "
              f"1개월 {r.get('m1') or 0:+.2f}%  3개월 {r.get('m3') or 0:+.2f}%")
    print("\n[하위 5]")
    for r in ranked[-5:]:
        print(f"  {r['name']:18s} 1주 {r.get('w1') or 0:+.2f}%  "
              f"1개월 {r.get('m1') or 0:+.2f}%  3개월 {r.get('m3') or 0:+.2f}%")


if __name__ == "__main__":
    main()
