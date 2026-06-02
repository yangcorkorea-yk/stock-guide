"""
거시 이벤트(FOMC/CPI/PCE/GDP/NFP) 발표 다음날 5분 브리핑 자동 생성.

매일 GH Actions cron이 실행:
  1. 어제 발생한 거시 이벤트 검색 (macro_calendar)
  2. 이벤트 있으면 시장 반응 + 뉴스 헤드라인 수집
  3. LLM(Sonnet)으로 한국어 브리핑 생성
  4. data/event_briefings.json 에 prepend (최근 6개 보관)

환경변수: ANTHROPIC_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", os.getenv("ALPACA_API_KEY") or "dummy")
os.environ.setdefault("ALPACA_SECRET_KEY", os.getenv("ALPACA_SECRET_KEY") or "dummy")

from analysis import get_bars
from news_client import fetch_news
from macro_calendar import _auto_events, _load_curated
from llm_client import synthesize_event_briefing_ko

OUT = ROOT / "data" / "event_briefings.json"
KEEP = 6  # 최근 N개 브리핑 보관


def yesterday_events(yd: date) -> list[dict]:
    """yd 날짜에 해당하는 거시 이벤트 (자동 + 큐레이션 병합)."""
    auto = _auto_events(yd, yd)
    curated = _load_curated()
    matched = []
    yd_s = yd.isoformat()
    seen = set()
    for src in (curated, auto):
        for e in src:
            if e.get("date") != yd_s:
                continue
            k = (e.get("date"), e.get("tag", ""))
            if k in seen:
                continue
            seen.add(k)
            matched.append(e)
    return matched


def collect_market_reaction() -> str:
    """어제 종가 기준 지수 변동률."""
    lines = []
    for sym, label in (("SPY", "S&P500"), ("QQQ", "나스닥100"), ("DIA", "다우")):
        try:
            df = get_bars(sym, days=10)
            if df is None or len(df) < 2:
                continue
            cur = float(df['close'].iloc[-1])
            prev = float(df['close'].iloc[-2])
            pct = (cur / prev - 1) * 100
            lines.append(f"- {label} ({sym}): ${cur:.2f} ({pct:+.2f}%)")
        except Exception:
            continue
    return "\n".join(lines) if lines else "(시장 데이터 수집 실패)"


def collect_news(hours_back: int = 48) -> list[str]:
    """발표 전후 36~48h 시장 뉴스 헤드라인."""
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours_back)
        news = fetch_news(start=start, end=end, limit=50, max_pages=1)
    except Exception:
        return []
    out = []
    for n in news:
        h = (n.get("headline") or "").strip()
        if h:
            out.append(h)
    return out[:30]


def load_existing() -> list[dict]:
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return data.get("event_briefings") or []
    except Exception:
        return []


def main():
    today = date.today()
    yd = today - timedelta(days=1)
    print(f"실행 시점: {today} / 어제: {yd}")

    events = yesterday_events(yd)
    print(f"어제 이벤트 {len(events)}개")
    if not events:
        print("→ 어제 이벤트 없음. 종료 (기존 JSON 유지).")
        return

    market = collect_market_reaction()
    news = collect_news()
    print(f"  시장 데이터: {market.count(chr(10)) + 1}줄, 뉴스 {len(news)}건")

    new_briefings = []
    for ev in events:
        print(f"\n→ {ev['name']} ({ev.get('tag','')}) LLM 호출...")
        r = synthesize_event_briefing_ko(ev, market, news)
        if not r or not r.get("summary"):
            print(f"  ❌ 생성 실패: {r}")
            continue
        new_briefings.append({
            "date": ev["date"],
            "event_name": ev["name"],
            "tag": ev.get("tag", ""),
            "headline": (r.get("headline") or "").strip(),
            "summary": (r.get("summary") or "").strip(),
            "market_reaction": (r.get("market_reaction") or "").strip(),
            "sectors_affected": r.get("sectors_affected") or [],
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        print(f"  ✅ {r.get('headline')}")

    if not new_briefings:
        print("\n⚠️ 생성된 브리핑 없음. 종료.")
        return

    existing = load_existing()
    yd_s = yd.isoformat()
    kept = [e for e in existing if e.get("date") != yd_s]
    merged = sorted(new_briefings + kept, key=lambda x: x["date"], reverse=True)[:KEEP]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"event_briefings": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ 저장: {OUT} ({len(merged)}개 브리핑)")


if __name__ == "__main__":
    main()
