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


def _first_weekday(year: int, month: int, weekday: int) -> date:
    """그 달 첫 weekday(월=0, 화=1, 수=2, ..., 일=6)."""
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def _nth_business_day(year: int, month: int, n: int) -> date:
    """그 달 N번째 영업일 (월~금)."""
    d = date(year, month, 1)
    bdays = 0
    while True:
        if d.weekday() < 5:
            bdays += 1
            if bdays == n:
                return d
        d += timedelta(days=1)


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

        # ADP 민간고용: 매월 첫째 수요일 (NFP 미니 프리뷰)
        fw = _first_weekday(y, m, 2)
        if start <= fw <= end:
            events.append({
                "date": str(fw),
                "name": "ADP 민간고용 발표",
                "tag": "👥 ADP",
                "desc": "민간기업 신규 고용. NFP 이틀 전 발표돼 시장이 '맛보기'로 본다."
            })

        # ISM 제조업 PMI: 매월 첫째 영업일
        ism_m = _nth_business_day(y, m, 1)
        if start <= ism_m <= end:
            events.append({
                "date": str(ism_m),
                "name": "ISM 제조업 PMI",
                "tag": "🏭 ISM",
                "desc": "제조업 경기지수 (50↑ 확장 / 50↓ 위축). 경기 선행 지표."
            })

        # ISM 서비스업 PMI: 매월 셋째 영업일
        ism_s = _nth_business_day(y, m, 3)
        if start <= ism_s <= end:
            events.append({
                "date": str(ism_s),
                "name": "ISM 서비스업 PMI",
                "tag": "🛎️ ISM",
                "desc": "서비스업 경기지수. 미국 경제의 70%를 차지."
            })

        # JOLTS 구인·이직: 매월 첫째 화요일 (BLS 일정 추정)
        ft = _first_weekday(y, m, 1)
        if start <= ft <= end:
            events.append({
                "date": str(ft),
                "name": "JOLTS 구인·이직 보고서",
                "tag": "📋 JOLTS",
                "desc": "구인 건수·이직률 (BLS). 노동시장 강도 지표."
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


def get_meta() -> dict:
    """큐레이션 JSON의 메타데이터 (last_refresh, refresh_failures 등)."""
    try:
        data = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
        return {
            "last_refresh": data.get("last_refresh"),
            "refresh_failures": data.get("refresh_failures", []),
        }
    except Exception:
        return {}


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
