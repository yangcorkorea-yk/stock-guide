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


# 태그별 상세 설명 — 클릭 시 펼침. 각 항목:
#   what: 한 줄 정의
#   high: 예상보다 높을 때 시장 해석
#   low:  예상보다 낮을 때 시장 해석
#   watch: 함께 봐야 할 포인트
TAG_INFO = {
    "📊 CPI": {
        "what": "소비자물가지수. 미국인이 사는 물건·서비스 가격이 1년 전 대비 얼마나 올랐는지.",
        "high": "예상보다 높게 나오면 → 인플레이션이 안 잡힘 → Fed가 금리 인하를 늦춤 → **성장주·기술주 부담**.",
        "low": "예상보다 낮으면 → 인플레 안정 → 금리 인하 기대 → **성장주에 우호적**.",
        "watch": "헤드라인 vs 컨센서스. 식품·에너지 뺀 'Core CPI'가 더 중요해요.",
    },
    "🏦 FOMC": {
        "what": "연준(Fed) 정례회의. 미국 기준금리 결정 + 통화정책 방향 발표.",
        "high": "금리 동결·인상 시그널 → 위험자산 부담, 채권·달러 강세.",
        "low": "금리 인하·완화 시그널 → 주식 등 위험자산 우호, 달러 약세.",
        "watch": "결정 자체보다 **파월 의장 기자회견·점도표(SEP)**에서 향후 방향 힌트가 핵심.",
    },
    "💵 PCE": {
        "what": "개인소비지출 물가지수. **Fed가 가장 중시하는** 인플레이션 지표.",
        "high": "Core PCE가 높으면 금리 인하 후퇴 부담 → 시장 압박.",
        "low": "Fed의 인플레 목표(2%)에 가까워질수록 시장 안도.",
        "watch": "Core PCE (식품·에너지 제외)가 진짜 지표.",
    },
    "📈 GDP": {
        "what": "국내총생산. 미국 경제 성장률.",
        "high": "강한 성장 → 기업 실적 우호. 다만 너무 강하면 금리 인하 늦춤.",
        "low": "약하거나 마이너스 → 경기침체 우려. 다만 금리 인하 기대 강화.",
        "watch": "속보치 → 잠정치 → 확정치 세 번 발표. **속보치가 시장 영향 가장 큼**.",
    },
    "📈 PPI": {
        "what": "생산자물가지수. CPI보다 한 단계 앞(도매 단계) 물가.",
        "high": "기업 비용 상승 → 향후 CPI 상승 압력.",
        "low": "비용 안정 → 인플레 완화 신호.",
        "watch": "CPI 다음날 발표라 둘을 묶어서 해석해요.",
    },
    "💼 NFP": {
        "what": "비농업 신규 고용 + 실업률. **미국 노동시장 가장 핵심** 지표.",
        "high": "고용 강세 → 경기 견조. 단 금리 인하 늦춤 부담.",
        "low": "고용 식음 → 경기 둔화 우려. 단 금리 인하 기대 강화 ('나쁜 뉴스가 좋은 뉴스').",
        "watch": "신규 고용 + **실업률** + **임금상승률** 세 가지를 함께 봐야 해요.",
    },
    "👥 ADP": {
        "what": "민간기업 신규 고용 (ADP 자체 집계). NFP 이틀 전 발표돼 미니 프리뷰.",
        "high": "NFP 강세 시사 → 금리 인하 늦춤 우려.",
        "low": "NFP 약세 시사 → 금리 인하 기대.",
        "watch": "ADP와 실제 NFP는 가끔 크게 어긋남 → 참고용으로만.",
    },
    "🏭 ISM": {  # 제조업 PMI
        "what": "ISM 제조업 PMI. 50 위면 경기 확장, 아래면 위축.",
        "high": "50↑ + 상승 추세 → 경기 확장 / 산업재·소재 우호.",
        "low": "50↓ + 하락 → 경기 위축 / 채권·방어주 선호.",
        "watch": "**신규주문(New Orders) sub-index**가 향후 6개월 선행 지표로 가장 중요.",
    },
    "🛎️ ISM": {  # 서비스업 PMI
        "what": "ISM 서비스업 PMI. **미국 GDP의 70%**를 차지하는 서비스업 경기.",
        "high": "50↑ → 소비·서비스 강세 / 빅테크·소비재 우호.",
        "low": "50↓ → 경기 둔화 신호 (제조업보다 영향이 더 큼).",
        "watch": "신규주문·고용 sub-index 같이 보면 좋아요.",
    },
    "📋 JOLTS": {
        "what": "구인 건수·이직률 (Job Openings and Labor Turnover Survey).",
        "high": "구인 많음 → 노동시장 강세 → 임금 인상 압력 → 금리 인하 부담.",
        "low": "구인 줄어듦 → 노동시장 식음 → 금리 인하 기대.",
        "watch": "**Quits Rate(자발 이직률)**이 임금·소비 선행 지표.",
    },
    "🦇 네마녀": {
        "what": "주가지수·개별주 선물·옵션이 동시 만기 (분기 셋째 금요일).",
        "high": "장 마감 부근 대량 매매 → 변동성 큼.",
        "low": "방향성보다 **변동성 자체**가 이슈.",
        "watch": "방향성 예측은 어렵고, 변동성에 대비해야 해요.",
    },
    "📋 옵션만기": {
        "what": "월간 주식·지수 옵션 만기 (셋째 금요일).",
        "high": "장 마감 부근 변동성 증가 가능.",
        "low": "네마녀보단 영향 작아요.",
        "watch": "특정 종목의 옵션 OI 큰 행사가 부근에서 가격이 끌리는 'pinning' 현상.",
    },
}


def get_tag_info(tag: str) -> dict:
    """태그(예: '📊 CPI')에 해당하는 상세 설명 dict 또는 빈 dict."""
    return TAG_INFO.get(tag, {})


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
    """규칙 기반 이벤트. start ~ end 범위 (inclusive).
    is_estimate=True 인 이벤트는 기관 발표 일정에 따라 ±수일 차이날 수 있음.
    """
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
                    "desc": "주가지수·개별주 선물·옵션이 동시에 만기. 장 마감 부근 변동성 큰 날.",
                    "is_estimate": False,
                })
            else:
                events.append({
                    "date": str(tf),
                    "name": "월간 옵션 만기",
                    "tag": "📋 옵션만기",
                    "desc": "월간 주식·지수 옵션 만기.",
                    "is_estimate": False,
                })
        ff = _first_friday(y, m)
        if start <= ff <= end:
            events.append({
                "date": str(ff),
                "name": "고용보고서 (NFP) 발표",
                "tag": "💼 NFP",
                "desc": "비농업 고용·실업률 (BLS). 시장 방향에 영향 큰 지표.",
                "is_estimate": False,
            })

        # ADP 민간고용: 매월 첫째 수요일 (NFP 미니 프리뷰)
        fw = _first_weekday(y, m, 2)
        if start <= fw <= end:
            events.append({
                "date": str(fw),
                "name": "ADP 민간고용 발표",
                "tag": "👥 ADP",
                "desc": "민간기업 신규 고용. NFP 이틀 전 발표돼 시장이 '맛보기'로 본다.",
                "is_estimate": True,
            })

        # ISM 제조업 PMI: 매월 첫째 영업일
        ism_m = _nth_business_day(y, m, 1)
        if start <= ism_m <= end:
            events.append({
                "date": str(ism_m),
                "name": "ISM 제조업 PMI",
                "tag": "🏭 ISM",
                "desc": "제조업 경기지수 (50↑ 확장 / 50↓ 위축). 경기 선행 지표.",
                "is_estimate": True,
            })

        # ISM 서비스업 PMI: 매월 셋째 영업일
        ism_s = _nth_business_day(y, m, 3)
        if start <= ism_s <= end:
            events.append({
                "date": str(ism_s),
                "name": "ISM 서비스업 PMI",
                "tag": "🛎️ ISM",
                "desc": "서비스업 경기지수. 미국 경제의 70%를 차지.",
                "is_estimate": True,
            })

        # JOLTS 구인·이직: 매월 첫째 화요일 (BLS 일정 추정)
        ft = _first_weekday(y, m, 1)
        if start <= ft <= end:
            events.append({
                "date": str(ft),
                "name": "JOLTS 구인·이직 보고서",
                "tag": "📋 JOLTS",
                "desc": "구인 건수·이직률 (BLS). 노동시장 강도 지표.",
                "is_estimate": True,
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
