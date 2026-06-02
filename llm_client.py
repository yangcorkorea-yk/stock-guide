"""
LLM 요약 클라이언트 — Anthropic Claude (기본: claude-haiku-4-5).

- ANTHROPIC_API_KEY 가 secrets/env에 있으면 호출, 없으면 None 반환 (graceful).
- 모델은 ANTHROPIC_MODEL 로 오버라이드 가능.
- 호출 실패 시 None.
"""
from __future__ import annotations

import os
import re
from typing import Optional

DEFAULT_MODEL = "claude-haiku-4-5"
# 종합 분석은 좀 더 큰 모델로 (속도보다 인사이트 우선)
DEFAULT_ANALYSIS_MODEL = "claude-sonnet-4-6"


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
    """기본 모델 — 뉴스 요약·헤드라인 번역 등 가벼운 작업용."""
    try:
        import streamlit as st
        m = st.secrets.get("ANTHROPIC_MODEL")
        if m:
            return m
    except Exception:
        pass
    return os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)


def _model_analysis() -> str:
    """종합 분석 전용 모델. ANTHROPIC_MODEL_ANALYSIS 우선, 없으면 Sonnet."""
    try:
        import streamlit as st
        m = st.secrets.get("ANTHROPIC_MODEL_ANALYSIS")
        if m:
            return m
    except Exception:
        pass
    return os.getenv("ANTHROPIC_MODEL_ANALYSIS", DEFAULT_ANALYSIS_MODEL)


def _strip_headers(text: str) -> str:
    """LLM 응답에서 마크다운 헤더/머릿말 제거 (안전망)."""
    if not text:
        return text
    # 줄 시작의 #/##/### 같은 헤더 라인 통째로 제거
    text = re.sub(r"^\s*#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
    # "XXX 관련 뉴스 요약" 같은 머릿말이 한 줄로 별도 있으면 제거 (보수적으로)
    text = re.sub(r"^\s*(.*?(요약|정리|분석)\s*)\n", "", text, count=1)
    return text.strip()


def _extract_json(text: str) -> Optional[dict]:
    """LLM 응답에서 JSON 안정적 추출.
    · 코드펜스(```json···```) 제거
    · prefix 텍스트 무시 (첫 { 부터 마지막 } 까지)
    · trailing comma 보정 (JSON 표준 위반이지만 LLM이 자주 만듦)
    """
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    cleaned = cleaned.replace("```", "")
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return None
    import json as _json
    candidate = m.group(0)
    # 1차: 원본 그대로
    for attempt in (candidate,
                    re.sub(r",\s*([}\]])", r"\1", candidate),  # trailing comma 제거
                    re.sub(r",\s*([}\]])", r"\1",
                           re.sub(r"^\s*//.*$", "", candidate, flags=re.MULTILINE))):  # 주석 제거
        try:
            return _json.loads(attempt)
        except Exception:
            continue
    return None


def summarize_news_ko(symbol: str, name: Optional[str], sector: Optional[str],
                      headlines: list[str]) -> Optional[str]:
    """
    헤드라인 리스트를 받아 한국어 3~4줄 요약을 돌려준다.
    name: 정확한 회사명 힌트 (예: '리게티컴퓨팅 Rigetti Computing'). LLM이
          회사명을 지어내지 않도록 넘김.
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
    sect = f" · 섹터: {sector}" if sector else ""
    company = name or symbol

    system = (
        "당신은 미국 주식 뉴스를 한국 초보 투자자에게 쉽게 요약하는 도우미입니다. "
        "예측·추천·매수/매도 권유는 절대 하지 않습니다. "
        "정확하지 않은 정보는 만들지 않습니다. "
        "회사명은 반드시 사용자가 알려준 이름만 쓰고, 임의로 지어내지 마세요. "
        "출력은 본문 단락만. 제목·헤더(#·##·**굵은 큰글씨**) 절대 금지."
    )
    user = (
        f"종목: {company} (티커 {symbol}){sect}\n\n"
        f"최근 뉴스 헤드라인:\n{hl}\n\n"
        f"위 헤드라인들을 종합해 한국어로 3~4줄 요약하세요.\n"
        f"- 회사명은 '{company}'의 한국어 표기를 그대로 쓰세요 (다른 이름 금지).\n"
        "- 어려운 용어는 풀어서, 초보자가 이해할 수 있게.\n"
        "- 사실만 정리. 가격 예측·매매 권유 금지.\n"
        "- 제목/헤더 없이 자연스러운 문단으로만 작성.\n"
        "- 'XXX 관련 뉴스 요약' 같은 머릿말 금지."
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
        text = _strip_headers(text)
        return text or None
    except Exception:
        return None


def synthesize_analysis_ko(symbol: str, name: Optional[str],
                           payload_text: str) -> Optional[str]:
    """
    종목의 종합 데이터(가격·기술지표·52주위치·참고가격대·뉴스)를 받아
    애널리스트 톤으로 한국어 5줄 종합. **예측·매매권유는 금지**.
    실패/키없음 시 None.
    """
    key = _key()
    if not key or not payload_text:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None

    company = name or symbol
    system = (
        "당신은 20년 경력의 미국 주식 애널리스트입니다. 초보 투자자에게 "
        "현재 상황을 쉽고 균형 있게 설명합니다. 반드시 주어진 데이터만 근거로 "
        "한국어로 정확히 5줄을 작성하세요.\n"
        "규칙(엄수):\n"
        "1) 가격 예측·목표가·매수/매도 권유 절대 금지.\n"
        "2) 긍정 신호와 위험 요인을 균형 있게 짚을 것.\n"
        "3) 불확실성·데이터 한계를 숨기지 말 것.\n"
        "4) 회사명은 사용자가 준 이름만 쓰고 지어내지 말 것.\n"
        "5) 각 줄은 '- '로 시작하는 한 문장. 군더더기 없이 간결하게."
    )
    user = (
        f"종목: {company} (티커 {symbol})\n\n"
        f"[현재 데이터]\n{payload_text}\n\n"
        "위 데이터를 종합해 한국어 5줄로 정리하세요. "
        "각 줄은 '- '로 시작. 예측·추천 없이 '지금 상태'만 균형 있게 설명."
    )
    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=_model_analysis(),  # 종합 분석은 별도 모델 (기본 Sonnet)
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            (b.text if hasattr(b, "text") else "") for b in resp.content).strip()
        text = _strip_headers(text)
        return text or None
    except Exception:
        return None


def compare_stocks_ko(items: list[dict]) -> Optional[dict]:
    """
    종목 비교 분석 — 시각화를 위해 JSON 반환.
    items: [{"symbol", "name", "data"}]
    반환: {"comparison": [{symbol, name, strengths[], weaknesses[], investor_type}], "insight": str}
    실패/키없음 시 None.
    """
    key = _key()
    if not key or len(items) < 2:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None

    blocks = []
    for it in items:
        blocks.append(f"## {it['name']} ({it['symbol']})\n{it['data']}")
    payload = "\n\n---\n\n".join(blocks)

    system = (
        "당신은 20년 경력의 미국 주식 애널리스트입니다. "
        "한국 초보 투자자에게 종목을 균형 있게 비교해 설명합니다.\n"
        "규칙(엄수):\n"
        "1) 가격 예측·목표가·매수/매도 권유 절대 금지.\n"
        "2) 강점·약점·리스크를 균형 있게.\n"
        "3) 주어진 데이터에 없는 사실 금지.\n"
        "4) 회사명은 입력 한국어만 사용.\n"
        "5) JSON만 출력. 다른 설명·마크다운·코드펜스 금지."
    )
    user = (
        f"다음 {len(items)}개 종목을 비교 분석해 JSON으로만 응답하세요.\n\n"
        f"{payload}\n\n"
        "스키마:\n"
        '{"comparison":[{"symbol":"티커","name":"한국어 회사명",'
        '"strengths":["짧은 강점 구문 1","강점 2"],'
        '"weaknesses":["짧은 약점/리스크 1","약점 2"],'
        '"investor_type":"어울리는 투자자 성향 (예: 성장 추구, 가치 투자, 배당 선호, 공격적 성장)"},'
        '...],"insight":"한국어 종합 인사이트 3~5줄, 공통점/차이점/리스크 균형. '
        "예측·추천 금지. 자연스러운 문단."
        '"}'
        "\n\n각 strengths/weaknesses는 2~3개. 짧은 명사구·서술 (10~20자 권장)."
    )
    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=_model_analysis(),
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text if hasattr(b, "text") else "" for b in resp.content).strip()
        return _extract_json(text)
    except Exception:
        return None


def synthesize_event_briefing_ko(event: dict, market_text: str,
                                  headlines: list[str]) -> Optional[dict]:
    """
    거시 이벤트(FOMC/CPI/PCE/GDP/NFP) 발표 다음날 5분 브리핑.
    event: {date, name, tag}
    market_text: 시장 반응 텍스트 (지수·VIX 변동률)
    headlines: 발표 전후 뉴스 헤드라인 리스트
    반환: {headline, summary, market_reaction, sectors_affected[]}
    """
    key = _key()
    if not key:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None

    hl_block = "\n".join(f"- {h}" for h in headlines[:20] if h)
    system = (
        "당신은 20년 경력의 미국 매크로 애널리스트입니다. "
        "거시지표(FOMC/CPI/PCE/GDP/고용보고서) 발표 결과를 한국 초보 투자자에게 "
        "쉽게 설명합니다.\n"
        "규칙(엄수):\n"
        "1) 가격 예측·목표가·매수/매도 권유 절대 금지.\n"
        "2) 발표 결과 숫자는 헤드라인에서 명시적으로 확인된 것만 사용 — 추측 금지.\n"
        "3) 시장 반응은 주어진 데이터에 근거.\n"
        "4) JSON만 출력. 다른 설명·마크다운·코드펜스 금지."
    )
    user = (
        f"이벤트: {event.get('name')} ({event.get('date')})\n"
        f"태그: {event.get('tag')}\n\n"
        f"[발표 다음날 시장 반응]\n{market_text}\n\n"
        f"[발표 전후 뉴스 헤드라인]\n{hl_block}\n\n"
        "JSON 스키마로만 응답:\n"
        '{"headline":"15~25자 한국어 핵심 한 줄 (예: 「CPI 예상 부합, 시장 안도」)",'
        '"summary":"발표 결과 요약 2~3문장. 헤드라인에서 확인된 구체 숫자(전년대비 %, 컨센서스 비교)와 그 의미.",'
        '"market_reaction":"시장 반응 1~2문장. 지수·VIX 변동률 인용.",'
        '"sectors_affected":["영향 받은 섹터/테마 2~3개, 각각 한 줄 (예: 「AI·빅테크 강세」, 「금리민감 성장주 상승」)"]}'
        "\n\n예측·매매 권유 절대 금지. 모르는 수치 만들지 말 것."
    )
    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=_model_analysis(),
            max_tokens=1800,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text if hasattr(b, "text") else "" for b in resp.content).strip()
        return _extract_json(text)
    except Exception:
        return None


def compare_kr_us_ko(pair: dict) -> Optional[dict]:
    """
    한국 종목 vs 미국 종목 1:1 비교 분석.
    pair: {theme, kr:{name,ticker,desc}, us:{name,ticker,desc}, reason}
    반환: {kr:{strengths[],weaknesses[]}, us:{strengths[],weaknesses[]},
           insight, kr_investor_note}
    """
    key = _key()
    if not key:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None

    kr = pair.get("kr", {})
    us = pair.get("us", {})
    system = (
        "당신은 20년 경력의 한·미 시장 비교 전문 애널리스트입니다. "
        "한국 초보 투자자에게 두 종목을 균형 있게 비교 설명합니다.\n"
        "규칙(엄수):\n"
        "1) 가격 예측·목표가·매수/매도 권유 금지.\n"
        "2) 강점·약점·리스크 균형 있게.\n"
        "3) 한국 투자자 관점의 차이(환율·세금·시장 시간 등) 언급 가능.\n"
        "4) 회사명은 입력한 한국어만 사용.\n"
        "5) JSON만 출력. 마크다운·코드펜스 금지."
    )
    user = (
        f"비교 테마: {pair.get('theme', '')}\n"
        f"비교 이유: {pair.get('reason', '')}\n\n"
        f"[🇰🇷 {kr.get('name')} ({kr.get('ticker')})]\n{kr.get('desc', '')}\n\n"
        f"[🇺🇸 {us.get('name')} ({us.get('ticker')})]\n{us.get('desc', '')}\n\n"
        "JSON 스키마로만 응답:\n"
        '{"kr":{"strengths":["짧은 강점 2~3개"],"weaknesses":["짧은 약점·리스크 2~3개"]},'
        '"us":{"strengths":["..."],"weaknesses":["..."]},'
        '"insight":"두 종목 비교 한국어 종합 3~4문장. 사업 모델/시장 위치 차이/공통 리스크 균형.",'
        '"kr_investor_note":"한국 투자자 관점에서 알면 좋을 점 1~2문장 (환율/세금/배당세/거래시간 등). 매매 권유 금지."}'
        "\n\n예측·매매 권유 절대 금지. 짧은 명사구 위주."
    )
    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=_model_analysis(),
            max_tokens=2200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text if hasattr(b, "text") else "" for b in resp.content).strip()
        return _extract_json(text)
    except Exception:
        return None


def translate_headlines_ko(headlines: list[str]) -> Optional[list[str]]:
    """
    영문 헤드라인 리스트를 한국어로 번역해 같은 순서·같은 개수로 반환.
    실패/키없음 시 None. (요약과 별도로 원문 링크 제목 번역용)
    """
    key = _key()
    if not key or not headlines:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None

    items = [h for h in headlines[:8] if h]
    if not items:
        return None
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(items))
    user = (
        "다음 영문 뉴스 제목들을 한국어로 자연스럽게 번역하세요.\n"
        "- 회사명·티커·고유명사는 그대로 두거나 통용 한글표기.\n"
        "- 각 줄을 '번호. 번역' 형식으로, 입력과 같은 개수·순서로.\n"
        "- 의역하되 과장 금지. 다른 설명 없이 번역 목록만.\n\n"
        f"{numbered}"
    )
    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=_model(),
            max_tokens=600,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            (b.text if hasattr(b, "text") else "") for b in resp.content).strip()
        # '1. ...' 형식 파싱
        out = []
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^\d+[\.\)]\s*(.+)$", line)
            if m:
                out.append(m.group(1).strip())
        if len(out) == len(items):
            return out
        # 개수 안 맞으면 안전하게 포기
        return None
    except Exception:
        return None
