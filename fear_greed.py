"""
CNN Fear & Greed Index — 무료, API 키 불필요.

시장 심리 종합 지표 (0~100):
  - VIX, 모멘텀, 주가 강도, breadth, 풋콜 비율, 정크본드 수요, 안전자산 수요 7개 종합
  - 0~25: 극도의 공포 / 25~45: 공포 / 45~55: 중립 / 55~75: 탐욕 / 75~100: 극도의 탐욕

출처: CNN 공개 데이터 API (비공식이지만 안정적)
"""
from __future__ import annotations

from typing import Optional

import requests

URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
HEADERS = {"User-Agent": "Mozilla/5.0 (stock-guide-research)"}
TIMEOUT = 8


def fetch_fear_greed() -> Optional[dict]:
    """
    현재 Fear & Greed 점수 + 비교값.
    반환: {score, rating, prev_close, prev_week, prev_month, prev_year}
    실패 시 None.
    """
    try:
        r = requests.get(URL, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("fear_and_greed") or {}
        if "score" not in data:
            return None
        def _f(k, default=0):
            v = data.get(k)
            try:
                return round(float(v), 1)
            except Exception:
                return default
        return {
            "score": _f("score"),
            "rating": data.get("rating") or "neutral",
            "prev_close": _f("previous_close"),
            "prev_week": _f("previous_1_week"),
            "prev_month": _f("previous_1_month"),
            "prev_year": _f("previous_1_year"),
        }
    except Exception:
        return None


def regime_ko(score: float) -> str:
    """점수 → 한국어 분위 라벨 (이모지 포함)."""
    if score < 25:
        return "🔴 극도의 공포"
    if score < 45:
        return "🟠 공포"
    if score < 55:
        return "🟡 중립"
    if score < 75:
        return "🟢 탐욕"
    return "🔥 극도의 탐욕"


def regime_short(score: float) -> str:
    """점수 → 짧은 한국어 라벨 (이모지 없음, 텍스트 컨텍스트용)."""
    if score < 25:
        return "극도의 공포"
    if score < 45:
        return "공포"
    if score < 55:
        return "중립"
    if score < 75:
        return "탐욕"
    return "극도의 탐욕"


def context_text(data: dict) -> str:
    """데일리 브리핑 LLM 페이로드용 한 줄 텍스트."""
    if not data:
        return ""
    score = data["score"]
    return (
        f"Fear & Greed Index: {score:.0f} ({regime_short(score)}) · "
        f"전일 {data['prev_close']:.0f} · 1주전 {data['prev_week']:.0f} · "
        f"1개월전 {data['prev_month']:.0f} · 1년전 {data['prev_year']:.0f}"
    )
