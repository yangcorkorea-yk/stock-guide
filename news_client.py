"""
Alpaca News API 클라이언트 (무료 플랜 포함, 기존 ALPACA 키 재사용).

엔드포인트: https://data.alpaca.markets/v1beta1/news
문서: https://docs.alpaca.markets/reference/news-3

- fetch_news(symbols=None, start=None, end=None, limit=50)
  · symbols 없으면 시장 전체 뉴스. 있으면 해당 심볼들 관련 뉴스.
  · start/end 는 ISO datetime (UTC). 미지정 시 최근 3일.
  · 페이지네이션 자동 처리 (max_pages 까지).

graceful: 키 없거나 호출 실패 시 빈 리스트 반환.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import requests

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


def _alpaca_keys():
    """secrets_loader 와 같은 우선순위. import 부수 효과 없이 직접 읽음."""
    # ① Streamlit secrets
    try:
        import streamlit as st
        k = st.secrets.get("ALPACA_API_KEY")
        s = st.secrets.get("ALPACA_SECRET_KEY")
        if k and s:
            return k, s
    except Exception:
        pass
    # ② env
    k = os.getenv("ALPACA_API_KEY")
    s = os.getenv("ALPACA_SECRET_KEY")
    if k and s and not k.startswith("dummy"):
        return k, s
    # ③ config.py
    try:
        from config import API_KEY, SECRET_KEY  # type: ignore
        return API_KEY, SECRET_KEY
    except Exception:
        return None, None


def fetch_news(symbols: Optional[Iterable[str]] = None,
               start: Optional[datetime] = None,
               end: Optional[datetime] = None,
               limit: int = 50,
               max_pages: int = 5) -> list[dict]:
    """
    Alpaca News API 호출. 실패하면 빈 리스트.

    반환 항목 키: id, headline, summary, author, url, symbols(list), created_at, updated_at, source
    """
    key, sec = _alpaca_keys()
    if not key or not sec:
        return []

    if end is None:
        end = datetime.now(timezone.utc)
    if start is None:
        start = end - timedelta(days=3)

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": sec,
        "Accept": "application/json",
    }
    params = {
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": min(max(limit, 1), 50),  # Alpaca 최대 50
        "sort": "desc",
        "include_content": "false",
        "exclude_contentless": "true",
    }
    if symbols:
        params["symbols"] = ",".join(symbols)

    out: list[dict] = []
    next_token = None
    for _ in range(max_pages):
        if next_token:
            params["page_token"] = next_token
        try:
            r = requests.get(NEWS_URL, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception:
            break
        out.extend(data.get("news") or [])
        next_token = data.get("next_page_token")
        if not next_token:
            break
    return out


def count_theme_mentions(news: list[dict], themes: dict) -> dict:
    """
    각 테마의 keywords 가 뉴스 headline+summary에서 몇 번 등장했는지 (대소문자 무시).
    한 헤드라인에 같은 테마의 다른 키워드가 여러 번 나오면 1번만 셈.

    반환: {테마명: int}
    """
    counts = {name: 0 for name in themes}
    for n in news:
        text = ((n.get("headline") or "") + " " + (n.get("summary") or "")).lower()
        if not text.strip():
            continue
        for name, info in themes.items():
            kws = [k.lower() for k in info.get("keywords") or []]
            if any(k in text for k in kws):
                counts[name] += 1
    return counts
