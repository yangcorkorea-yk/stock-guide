"""
FRED (St. Louis Fed) 경제 시리즈 클라이언트 — 무료.

키 발급: https://fred.stlouisfed.org/docs/api/api_key.html (무료, 즉시)
환경변수: FRED_API_KEY (없으면 모든 함수가 None 반환, graceful)

주요 시리즈:
  CPIAUCSL  소비자물가지수 (전체)
  CPILFESL  Core CPI (식품·에너지 제외)
  PAYEMS    비농업 신규 고용 (level → MoM 차이로 신규고용수)
  UNRATE    실업률 (%)
  DGS10     10년물 국채 금리 (%)
  DGS2      2년물 국채 금리 (%)
  T10Y2Y    10Y−2Y 스프레드 (역전 시 음수, 침체 신호로 자주 거론)
  DFF       Federal Funds 유효금리 (%)
  PCEPI     PCE 물가지수
  PCEPILFE  Core PCE
  PPIACO    PPI (전체 상품)
  GDPC1     실질 GDP (level)
  VIXCLS    VIX 일별 종가 (yfinance 폴백)
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

import requests

BASE = "https://api.stlouisfed.org/fred"
TIMEOUT = 10


# macro_calendar 태그 → FRED 시리즈 + 표시 라벨
TAG_TO_SERIES = {
    "📊 CPI":   {"series": "CPIAUCSL", "label": "CPI (전월)",
                 "transform": "yoy_pct", "unit": "% YoY"},
    "📈 PPI":   {"series": "PPIACO",  "label": "PPI (전월)",
                 "transform": "yoy_pct", "unit": "% YoY"},
    "💵 PCE":   {"series": "PCEPI",   "label": "PCE 물가",
                 "transform": "yoy_pct", "unit": "% YoY"},
    "📈 GDP":   {"series": "GDPC1",   "label": "실질 GDP",
                 "transform": "qoq_annualized", "unit": "% QoQ 연율"},
    "💼 NFP":   {"series": "PAYEMS",  "label": "신규 고용",
                 "transform": "mom_diff", "unit": "K"},
    "👥 ADP":   {"series": "PAYEMS",  "label": "신규 고용 (NFP 대용)",
                 "transform": "mom_diff", "unit": "K"},
    "🏦 FOMC":  {"series": "DFF",     "label": "Fed Funds",
                 "transform": "level", "unit": "%"},
    # ISM은 FRED 무료 시리즈 없음 — 생략
    # JOLTS: JTSJOL (job openings)
    "📋 JOLTS": {"series": "JTSJOL", "label": "구인 건수",
                 "transform": "level", "unit": "K"},
}


def _key() -> Optional[str]:
    try:
        import streamlit as st
        k = st.secrets.get("FRED_API_KEY")
        if k:
            return k
    except Exception:
        pass
    return os.getenv("FRED_API_KEY") or None


def get_observations(series_id: str, limit: int = 24) -> Optional[list[dict]]:
    """
    /series/observations — 최근 N개 관측치 (날짜 내림차순).
    반환: [{date: 'YYYY-MM-DD', value: float}, ...]  (실패·결측 None)
    """
    k = _key()
    if not k:
        return None
    try:
        r = requests.get(f"{BASE}/series/observations", params={
            "series_id": series_id,
            "api_key": k,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        obs = (r.json() or {}).get("observations") or []
        out = []
        for o in obs:
            try:
                v = float(o.get("value") or "")
            except Exception:
                continue
            out.append({"date": o.get("date") or "", "value": v})
        return out or None
    except Exception:
        return None


def _transform(obs: list[dict], kind: str) -> list[dict]:
    """관측치에 변환 적용. 결과 새 리스트 (날짜 내림차순 유지)."""
    if not obs or kind == "level":
        return obs
    obs_asc = list(reversed(obs))  # 시간순 정렬
    out_asc = []
    if kind == "yoy_pct":
        for i in range(len(obs_asc)):
            cur = obs_asc[i]
            # 12개월 전 값 찾기 (월별 시리즈 가정)
            if i >= 12:
                prev = obs_asc[i - 12]
                if prev["value"] != 0:
                    yoy = (cur["value"] / prev["value"] - 1) * 100
                    out_asc.append({"date": cur["date"], "value": yoy})
    elif kind == "mom_diff":
        for i in range(1, len(obs_asc)):
            cur = obs_asc[i]
            prev = obs_asc[i - 1]
            out_asc.append({"date": cur["date"],
                            "value": (cur["value"] - prev["value"])})  # level diff
    elif kind == "qoq_annualized":
        for i in range(1, len(obs_asc)):
            cur = obs_asc[i]
            prev = obs_asc[i - 1]
            if prev["value"] != 0:
                qoq = (cur["value"] / prev["value"]) ** 4 - 1
                out_asc.append({"date": cur["date"], "value": qoq * 100})
    return list(reversed(out_asc))


def get_indicator_trend(tag: str, lookback_points: int = 6) -> Optional[dict]:
    """
    매크로 태그 → 최근 lookback_points 개월 추이.
    반환:
      {
        "series": str, "label": str, "unit": str,
        "points": [{date, value}, ...],   # 최신 → 과거 순
        "latest": float, "prev": float, "trend": '↑'|'↓'|'→',
      }
    """
    cfg = TAG_TO_SERIES.get(tag)
    if not cfg:
        return None
    raw = get_observations(cfg["series"], limit=30)
    if not raw:
        return None
    transformed = _transform(raw, cfg["transform"])
    if not transformed:
        return None
    points = transformed[:lookback_points]
    latest = points[0]["value"]
    prev = points[1]["value"] if len(points) > 1 else latest
    diff = latest - prev
    trend = "↑" if diff > 0.05 else ("↓" if diff < -0.05 else "→")
    return {
        "series": cfg["series"],
        "label": cfg["label"],
        "unit": cfg["unit"],
        "points": points,
        "latest": latest,
        "prev": prev,
        "trend": trend,
    }


def get_yield_snapshot() -> Optional[dict]:
    """
    10Y·2Y 국채 금리 + 장단기 스프레드 한 번에.
    반환: {dgs10, dgs2, t10y2y, prev_dgs10, prev_dgs2, prev_spread}
    """
    k = _key()
    if not k:
        return None
    out = {}
    for sid, key in (("DGS10", "dgs10"), ("DGS2", "dgs2"), ("T10Y2Y", "t10y2y")):
        ob = get_observations(sid, limit=5)
        if not ob:
            continue
        out[key] = ob[0]["value"]
        out[f"prev_{key}"] = ob[1]["value"] if len(ob) > 1 else ob[0]["value"]
    if not out:
        return None
    return out


def yield_curve_label(spread: float) -> str:
    """T10Y2Y 스프레드 → 한국어 분위."""
    if spread < -0.5:
        return "🔴 강한 역전"
    if spread < 0:
        return "🟠 역전"
    if spread < 0.5:
        return "🟡 평탄"
    if spread < 1.5:
        return "🟢 정상"
    return "🟢 가파름"
