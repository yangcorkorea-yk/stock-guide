"""
Finnhub API 클라이언트 — 무료 60 req/min.
회사 프로필·펀더멘털·실적 일정을 가져온다.

환경변수: FINNHUB_KEY (없으면 모든 함수가 None 반환, graceful)
무료 가입: https://finnhub.io/register (신용카드 불필요)
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Optional

import requests

BASE = "https://finnhub.io/api/v1"
TIMEOUT = 8


def _key() -> Optional[str]:
    try:
        import streamlit as st
        k = st.secrets.get("FINNHUB_KEY")
        if k:
            return k
    except Exception:
        pass
    return os.getenv("FINNHUB_KEY") or None


def _get(path: str, params: dict) -> Optional[dict]:
    k = _key()
    if not k:
        return None
    params = {**params, "token": k}
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


def get_company_profile(symbol: str) -> Optional[dict]:
    """
    /stock/profile2 — 회사 기본 프로필.
    반환 키: name, finnhubIndustry, marketCapitalization(million USD), currency, exchange, ipo, weburl
    """
    data = _get("/stock/profile2", {"symbol": symbol})
    if not data or not data.get("name"):
        return None
    return data


def get_basic_financials(symbol: str) -> Optional[dict]:
    """
    /stock/metric — 펀더멘털 지표 (annual·TTM).
    반환은 metric dict (없으면 None).
    """
    data = _get("/stock/metric", {"symbol": symbol, "metric": "all"})
    if not data:
        return None
    return data.get("metric") or None


def get_economic_calendar(from_date: str, to_date: str,
                          country: str = "US") -> Optional[list]:
    """
    /calendar/economic — 경제 지표 캘린더 (actual/estimate/prev).
    from_date, to_date: 'YYYY-MM-DD'
    반환: [{event, actual, estimate, prev, unit, impact, time}, ...]
    실패 시 None.
    """
    data = _get("/calendar/economic", {"from": from_date, "to": to_date})
    if not data:
        return None
    items = data.get("economicCalendar") or []
    out = []
    for it in items:
        c = (it.get("country") or "").upper()
        if country and c != country:
            continue
        out.append({
            "event": it.get("event") or "",
            "actual": it.get("actual"),
            "estimate": it.get("estimate"),
            "prev": it.get("prev"),
            "unit": it.get("unit") or "",
            "impact": it.get("impact") or "",
            "time": it.get("time") or "",
        })
    return out


def get_next_earnings(symbol: str) -> Optional[dict]:
    """
    /calendar/earnings — 향후 ~120일 안의 실적 일정 첫 항목.
    반환: {date, epsEstimate, revenueEstimate, hour, quarter, year} 또는 None
    """
    today = date.today()
    end = today + timedelta(days=120)
    data = _get("/calendar/earnings", {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "symbol": symbol,
    })
    if not data:
        return None
    items = data.get("earningsCalendar") or []
    if not items:
        return None
    # 가장 가까운 항목
    items.sort(key=lambda x: x.get("date", ""))
    return items[0]
