"""
오늘의 시장 브리핑 자동 생성.

수집: 지수·빅테크 변동률(Alpaca) + 거시 이벤트(macro_events.json)
     + 최근 시장 뉴스 헤드라인(Alpaca)
LLM:  Anthropic Claude (기본 Sonnet) — 한국어 헤드라인 + 본문 3~5줄
저장: data/market_briefing.json

GH Actions cron으로 매일 실행 (미국 마감 직후 = KST 새벽).

환경변수:
  ANTHROPIC_API_KEY (필수)
  ALPACA_API_KEY, ALPACA_SECRET_KEY (시장 데이터)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# secrets_loader 가 import 시 키를 요구하므로 더미라도 채워둠
os.environ.setdefault("ALPACA_API_KEY", os.getenv("ALPACA_API_KEY") or "dummy")
os.environ.setdefault("ALPACA_SECRET_KEY", os.getenv("ALPACA_SECRET_KEY") or "dummy")

from analysis import get_bars
from news_client import fetch_news
from macro_calendar import upcoming_events
from llm_client import _key, _model_analysis

OUT = ROOT / "data" / "market_briefing.json"

# 지수 ETF + 메가캡 빅테크 — 시장 분위기 파악용
WATCH = ["SPY", "QQQ", "DIA", "NVDA", "MSFT", "GOOGL", "META", "AAPL",
         "AMZN", "TSLA", "AVGO"]


def _move(sym: str):
    """심볼의 어제 종가 + 전일 대비 변동률(%) 반환. 실패 시 None."""
    try:
        df = get_bars(sym, days=10)
        if df is None or len(df) < 2:
            return None
        cur = float(df['close'].iloc[-1])
        prev = float(df['close'].iloc[-2])
        return cur, (cur / prev - 1) * 100, str(df.index[-1].date())
    except Exception:
        return None


def collect_payload():
    today = date.today()
    lines = []
    market_date = None

    # 1) 지수·빅테크 변동률
    lines.append("[어제 미국 시장 변동률]")
    for s in WATCH:
        m = _move(s)
        if m is None:
            continue
        price, pct, mdate = m
        if market_date is None:
            market_date = mdate
        lines.append(f"- {s}: ${price:.2f} ({pct:+.2f}%)")

    # 1-b) 시장 심리 — Fear & Greed Index
    try:
        from fear_greed import fetch_fear_greed, context_text
        fg = fetch_fear_greed()
        if fg:
            lines.append("\n[시장 심리]")
            lines.append("- " + context_text(fg))
    except Exception:
        pass

    # 2) 향후 14일 거시 이벤트
    upcoming = upcoming_events(days=14, today=today)
    if upcoming:
        lines.append("\n[향후 14일 시장 이벤트]")
        for e in upcoming[:8]:
            lines.append(f"- {e['date']} ({e.get('tag','')}): {e['name']}")

    # 3) 최근 36h 시장 뉴스 헤드라인 (Alpaca)
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=36)
        news = fetch_news(start=start, end=end, limit=30, max_pages=1)
    except Exception:
        news = []
    if news:
        lines.append("\n[최근 시장 뉴스 헤드라인]")
        for n in news[:12]:
            h = (n.get("headline") or "").strip()
            if h:
                lines.append(f"- {h}")

    return "\n".join(lines), today, market_date


def synthesize(payload: str, today: date) -> dict:
    key = _key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수 필요")
    from anthropic import Anthropic
    client = Anthropic(api_key=key)

    system = (
        "당신은 20년 경력의 미국 주식 시장 분석가입니다. "
        "한국 초보 투자자에게 오늘의 시장 상황을 쉽고 균형 있게 설명합니다.\n"
        "규칙(엄수):\n"
        "1) 가격 예측·목표가·매수/매도 권유 절대 금지.\n"
        "2) 긍정 신호와 위험 요인을 균형 있게 짚을 것.\n"
        "3) 주어진 데이터에 없는 사실을 만들지 말 것.\n"
        "4) 응답은 JSON만 출력 — 다른 설명·마크다운·코드펜스 금지."
    )
    user = (
        f"기준일: {today}\n\n"
        f"[현재 데이터]\n{payload}\n\n"
        "위 데이터로 다음 JSON 형식으로만 응답하세요:\n"
        '{"headline": "한국어 짧은 헤드라인 (20자 내외)", '
        '"briefing": "한국어 본문 3~5줄. 어제 시장 분위기 + 이번 주 주목할 것 + '
        '다가올 이벤트. 자연스러운 단락. 예측·매매 권유 금지."}'
    )
    resp = client.messages.create(
        model=_model_analysis(),
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text if hasattr(b, "text") else "" for b in resp.content).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError(f"JSON 파싱 실패. raw 200자: {raw[:200]!r}")
    return json.loads(m.group(0))


def main():
    print(f"실행 시점 (UTC): {datetime.now(timezone.utc).isoformat()}")

    print("[1/3] 시장 데이터 수집...")
    payload, today, market_date = collect_payload()
    print(f"  payload {len(payload)} 자, market_date={market_date}")
    if len(payload) < 50:
        print("⚠️ 데이터 너무 적음 — 저장 건너뜀.")
        sys.exit(0)

    print("[2/3] LLM 브리핑 생성...")
    result = synthesize(payload, today)
    headline = (result.get("headline") or "").strip()
    briefing = (result.get("briefing") or "").strip()
    if not headline or not briefing:
        raise RuntimeError(f"LLM 응답 비어있음: {result}")
    print(f"  headline: {headline}")

    print("[3/3] JSON 저장...")
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market_date": market_date or str(today - timedelta(days=1)),
        "headline": headline,
        "briefing": briefing,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 저장: {OUT}")


if __name__ == "__main__":
    main()
