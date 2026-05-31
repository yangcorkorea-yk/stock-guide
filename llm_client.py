"""
LLM 요약 클라이언트 — Anthropic Claude (기본: claude-haiku-4-5).

- ANTHROPIC_API_KEY 가 secrets/env에 있으면 호출, 없으면 None 반환 (graceful).
- 모델은 ANTHROPIC_MODEL 로 오버라이드 가능.
- 호출 실패 시 None.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_MODEL = "claude-haiku-4-5"


def _key() -> Optional[str]:
    # ① Streamlit secrets
    try:
        import streamlit as st
        k = st.secrets.get("ANTHROPIC_API_KEY")
        if k:
            return k
    except Exception:
        pass
    # ② env
    k = os.getenv("ANTHROPIC_API_KEY")
    return k or None


def _model() -> str:
    try:
        import streamlit as st
        m = st.secrets.get("ANTHROPIC_MODEL")
        if m:
            return m
    except Exception:
        pass
    return os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)


def summarize_news_ko(symbol: str, sector: Optional[str], headlines: list[str]) -> Optional[str]:
    """
    헤드라인 리스트를 받아 한국어 3~4줄 요약을 돌려준다.
    실패/키없음 시 None.
    """
    key = _key()
    if not key or not headlines:
        return None

    try:
        from anthropic import Anthropic
    except Exception:
        return None

    # 헤드라인이 너무 많으면 위에서 잘라 비용 절약
    hl = "\n".join(f"- {h}" for h in headlines[:15] if h)
    sect = f"(섹터: {sector})" if sector else ""

    system = (
        "당신은 미국 주식 뉴스를 한국 초보 투자자에게 쉽게 요약하는 도우미입니다. "
        "예측·추천·매수/매도 권유는 절대 하지 않습니다. "
        "정확하지 않은 정보는 만들지 않습니다."
    )
    user = (
        f"종목: {symbol} {sect}\n\n"
        f"최근 뉴스 헤드라인:\n{hl}\n\n"
        "위 헤드라인들을 종합해 한국어로 3~4줄 요약하세요.\n"
        "- 어려운 용어는 풀어서, 초보자가 이해할 수 있게.\n"
        "- 사실만 정리. 가격 예측·매매 권유 금지.\n"
        "- 글머리표 없이 자연스러운 문단으로."
    )

    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=_model(),
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            (block.text if hasattr(block, "text") else "") for block in resp.content
        ).strip()
        return text or None
    except Exception:
        return None
