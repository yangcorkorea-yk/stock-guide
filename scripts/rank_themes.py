"""
최근 N일 Alpaca 뉴스에서 각 테마 키워드 언급량을 집계 → data/hot_themes.json 저장.

GitHub Actions에서 매일 실행. 결과 JSON이 변경되면 커밋 → Streamlit Cloud 자동 재배포.

실행:
    python scripts/rank_themes.py [--days 3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 프로젝트 루트 import 경로
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# analysis.py 의 Alpaca 키 import 부수 효과 회피 (이 스크립트는 별도 호출)
os.environ.setdefault("ALPACA_API_KEY", os.getenv("ALPACA_API_KEY") or "dummy")
os.environ.setdefault("ALPACA_SECRET_KEY", os.getenv("ALPACA_SECRET_KEY") or "dummy")

from analysis import THEMES
from news_client import fetch_news, count_theme_mentions

OUT = Path(__file__).resolve().parents[1] / "data" / "hot_themes.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="집계 윈도우(일)")
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    # 전체 시장 뉴스를 받아서 키워드 매칭 (테마별 심볼 필터 X)
    # 페이지 여러 장 모아야 표본 충분.
    news = fetch_news(start=start, end=end, limit=50, max_pages=args.max_pages)
    print(f"수집 헤드라인: {len(news)}건 (윈도우 {args.days}일)")

    if not news:
        print("⚠️ 뉴스 0건 — API 키/네트워크 확인. JSON 저장 안 함.")
        sys.exit(0)

    counts = count_theme_mentions(news, THEMES)
    ranked = sorted(
        ({"name": k, "count": v, "desc": THEMES[k]["desc"]} for k, v in counts.items()),
        key=lambda x: x["count"], reverse=True,
    )

    payload = {
        "updated_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": args.days,
        "sample_size": len(news),
        "themes": ranked,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 저장: {OUT}")
    for i, t in enumerate(ranked[:10], 1):
        print(f"  {i:2d}. {t['name']:18s}  {t['count']}건")


if __name__ == "__main__":
    main()
