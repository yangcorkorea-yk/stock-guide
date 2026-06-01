"""
거시 이벤트 캘린더 — 자동 계산 룰 + 큐레이션 JSON 결합.

자동 계산 (코드로 즉시 산출):
  · 네마녀의 날 (3·6·9·12월 셋째 금요일)
  · 월간 옵션 만기 (나머지 달의 셋째 금요일)
  · NFP (매월 첫째 금요일)

큐레이션 JSON (data/macro_events.json):
  · FOMC (Fed 정례회의 발표일)
  · CPI / PCE / GDP (BLS·BEA 발표일)
  · 기타 사용자 추가 이벤트

upcoming_events(days=30) → 오늘 이후 N일 내 이벤트 날짜순 리스트.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

CURATED_PATH = Path(__file__).resolve().parent / "data" / "macro_events.json"


def _third_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != 4:  # 금요일 = 4
        d += timedelta(days=1)
    return d + timedelta(days=14)


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def _auto_events(start: date, end: date) -> list[dict]:
    """규칙 기반 이벤트. start ~ end 범위 (inclusive)."""
    events: list[dict] = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        tf = _third_friday(y, m)
        if start <= tf <= end:
            if m in (3, 6, 9, 12):
                events.append({
                    "date": str(tf),
                    "name": "네마녀의 날 (쿼드러플 위칭)",
                    "tag": "🦇 네마녀",
                    "desc": "주가지수·개별주 선물·옵션이 동시에 만기. 장 마감 부근 변동성 큰 날."
                })
            else:
                events.append({
                    "date": str(tf),
                    "name": "월간 옵션 만기",
                    "tag": "📋 옵션만기",
                    "desc": "월간 주식·지수 옵션 만기."
                })
        ff = _first_friday(y, m)
        if start <= ff <= end:
            events.append({
                "date": str(ff),
                "name": "고용보고서 (NFP) 발표",
                "tag": "💼 NFP",
                "desc": "비농업 고용·실업률 (BLS). 시장 방향에 영향 큰 지표."
            })
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return events


def _load_curated() -> list[dict]:
    try:
        data = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
        return data.get("events", [])
    except Exception:
        return []


def upcoming_events(days: int = 30, today: Optional[date] = None) -> list[dict]:
    """
    오늘부터 N일 내 거시 이벤트를 날짜 순으로 반환.
    각 항목에 days_until (오늘 기준 D-N) 추가.
    """
    if today is None:
        today = date.today()
    end = today + timedelta(days=days)

    auto = _auto_events(today, end)
    curated = _load_curated()
    curated_filt = []
    for e in curated:
        try:
            d = date.fromisoformat(e["date"])
            if today <= d <= end:
                curated_filt.append(e)
        except Exception:
            continue

    # 같은 (date, tag) 중복 제거 — 큐레이션 우선
    seen = {(e["date"], e.get("tag", "")) for e in curated_filt}
    merged = list(curated_filt) + [e for e in auto if (e["date"], e.get("tag", "")) not in seen]
    merged.sort(key=lambda x: x["date"])

    for e in merged:
        try:
            d = date.fromisoformat(e["date"])
            e["days_until"] = (d - today).days
        except Exception:
            e["days_until"] = None
    return merged
