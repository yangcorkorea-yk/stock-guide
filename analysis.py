"""
종목 길잡이 - 분석/설명/차트 로직
-------------------------------------------------
analyze    : 현재 상태 계산
explain    : 간결한 현재 상태 설명 (규칙 기반)
RSI_HELP, BB_HELP : 용어 설명 (하단 접이식 주석용)
make_chart : 가격+볼린저 / RSI 차트
"""

from datetime import datetime, timedelta

import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from secrets_loader import API_KEY, SECRET_KEY
from auto_trader import add_indicators


def get_bars(symbol, days=400):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    req = StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
        start=datetime.now() - timedelta(days=days),
    )
    bars = client.get_stock_bars(req).df
    if bars.empty:
        return None
    bars = bars.reset_index()
    return bars.set_index('timestamp')[['open', 'high', 'low', 'close', 'volume']]


def analyze(df):
    df = add_indicators(df)
    row = df.iloc[-1]
    prev = float(df['close'].iloc[-2])
    rsi = float(row['rsi']); bb = float(row['bb_pct'])
    close = float(row['close']); ma_long = float(row['ma_long'])
    change = (close / prev - 1) * 100
    hi52 = float(df['close'].tail(252).max())
    high_52w_pct = (close / hi52 - 1) * 100
    vol = float(row['volume'])
    vma = float(row['vol_ma'])
    rvol = (vol / vma) if (vma > 0 and vma == vma) else None  # vma==vma → NaN 거르기

    if rsi >= 70 or bb >= 1.0:
        status = "과열"
    elif rsi <= 35 or bb <= 0.15:
        status = "눌림(과매도)"
    else:
        status = "중립"
    trend = "장기 상승 추세 위" if close >= ma_long else "장기 추세 아래"

    return dict(close=close, change=change, rsi=rsi, bb=bb,
                ma_long=ma_long, status=status, trend=trend, rvol=rvol,
                high_52w_pct=high_52w_pct, date=str(df.index[-1].date()))


def explain(symbol, info):
    """간결한 현재 상태 설명 (용어 정의는 하단 주석으로 분리)"""
    rsi, bb = info['rsi'], info['bb']
    lines = [f"**{symbol}는 지금 '{info['status']}' 상태**이고, {info['trend']}에 있어요.", ""]

    if rsi >= 70:
        lines.append(f"- RSI {rsi:.0f} — 과열 구간이에요.")
    elif rsi <= 35:
        lines.append(f"- RSI {rsi:.0f} — 과매도 구간이에요.")
    else:
        lines.append(f"- RSI {rsi:.0f} — 과열도 과매도도 아닌 중간이에요.")

    if bb >= 1.0:
        lines.append("- 볼린저밴드 상단 위 — 평소보다 비싸게 거래되는 중이에요.")
    elif bb <= 0.15:
        lines.append("- 볼린저밴드 하단 근처 — 평소보다 싸 보이는 구간이에요.")
    else:
        lines.append("- 볼린저밴드 가운데쯤 — 평소 범위 안에서 무난하게 움직여요.")

    if info['trend'].startswith("장기 상승"):
        lines.append("- 큰 흐름은 아직 상승 쪽이에요.")
    else:
        lines.append("- 큰 흐름은 약한 편이에요.")

    rv = info.get('rvol')
    if rv is not None:
        if rv >= 1.5:
            lines.append("- 거래량이 평소보다 많아요 — 관심이 쏠리는 중이에요.")
        elif rv < 0.7:
            lines.append("- 거래량이 평소보다 적어요 — 관심이 식은 편이에요.")

    lines += ["", "👉 '현재 상태'를 풀어준 것뿐이에요. 오른다는 뜻도, 사라는 뜻도 아닙니다."]
    return "\n".join(lines)


# ── 하단 접이식 주석용 용어 설명 (초보자용) ───────────────
RSI_HELP = """\
**RSI (과열도)**는 사람들이 요즘 이 주식을 얼마나 '달아올라' 사고팔았는지를
**0~100으로 나타낸 온도계** 같은 지표예요.

- **70 이상** → 과열. 최근 급하게 많이 샀다는 신호 (단, 더 오를 수도 있어요)
- **30 이하** → 과매도. 급하게 많이 팔았다는 신호 (단, 더 내릴 수도 있어요)
- **그 사이** → 중립

⚠️ 과열이라고 꼭 떨어지고, 과매도라고 꼭 오르는 건 아니에요.
"""

BB_HELP = """\
**볼린저밴드 (변동폭)**는 주가가 **'평소 다니던 길'을 위·아래 띠로 그려놓은 것**이에요.
가운데 선은 최근 20일 평균 가격, 위아래 띠는 보통의 변동 범위예요.

- 가격이 **위쪽 띠**에 가까우면 → 평소보다 비싼 편
- **아래쪽 띠**에 가까우면 → 평소보다 싼 편

화면의 **'볼린저밴드 위치'** 숫자는 0(맨 아래 띠)~1(맨 위 띠)로 나타낸 거예요.
1을 넘으면 위쪽 띠까지 뚫고 올라갔다는 뜻이고요.
"""


def make_chart(df, lookback=60):
    df = add_indicators(df).dropna().tail(lookback).copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_heights=[0.55, 0.18, 0.27], vertical_spacing=0.05,
                        subplot_titles=("가격 + 볼린저밴드", "거래량", "RSI"))
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'],
                                 low=df['low'], close=df['close'], name="가격",
                                 increasing_line_color="#e03131", decreasing_line_color="#1c7ed6"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_upper'], name="상단",
                             line=dict(color="gray", width=1, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_mid'], name="중심선",
                             line=dict(color="orange", width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_lower'], name="하단",
                             line=dict(color="gray", width=1, dash="dot")), row=1, col=1)

    vol_colors = ["#e03131" if c >= o else "#1c7ed6"
                  for o, c in zip(df['open'], df['close'])]
    fig.add_trace(go.Bar(x=df.index, y=df['volume'], name="거래량",
                         marker_color=vol_colors, showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['vol_ma'], name="평균거래량",
                             line=dict(color="orange", width=1), showlegend=False), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['rsi'], name="RSI",
                             line=dict(color="#7048e8", width=1.6)), row=3, col=1)
    fig.add_hline(y=70, line=dict(color="#e03131", dash="dash", width=1), row=3, col=1)
    fig.add_hline(y=30, line=dict(color="#1c7ed6", dash="dash", width=1), row=3, col=1)

    fig.update_layout(height=640, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0))
    fig.update_yaxes(title_text="$", row=1, col=1)
    fig.update_yaxes(title_text="거래량", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)

    # 휴장일(주말·공휴일) 제거 → 일봉 차트의 빈 칸 없애기
    diffs = df.index.to_series().diff().dropna().dt.days
    if len(diffs) and diffs.median() <= 3:  # 일봉일 때만 적용 (주봉/월봉은 불필요)
        breaks = [dict(bounds=["sat", "mon"])]              # 주말 제거
        bdays = pd.bdate_range(df.index.min(), df.index.max())
        holidays = bdays.difference(df.index)               # 거래 없는 평일 = 공휴일
        if len(holidays):
            breaks.append(dict(values=list(holidays)))
        fig.update_xaxes(rangebreaks=breaks)
    return fig


def resample_bars(df, tf):
    """일봉 df를 주봉('W')/월봉('M')으로 합침. 그 외는 일봉 그대로."""
    if tf not in ("W", "M"):
        return df
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    if tf == "W":
        return df.resample("W").agg(agg).dropna()
    for rule in ("ME", "M"):  # pandas 버전 호환 (신: ME, 구: M)
        try:
            return df.resample(rule).agg(agg).dropna()
        except (ValueError, KeyError):
            continue
    return df


# ── Phase 2: 섹터 → 대표 종목 (큐레이션) ─────────────────
SECTORS = {
    "AI · 빅테크": ["MSFT", "GOOGL", "META", "AMZN", "AAPL"],
    "반도체": ["NVDA", "AMD", "AVGO", "TSM", "MU", "INTC"],
    "양자컴퓨팅": ["IONQ", "RGTI", "QBTS"],
    "전기차 · 2차전지": ["TSLA", "RIVN", "LCID"],
    "클라우드 · SaaS": ["CRM", "NOW", "SNOW", "DDOG"],
    "핀테크 · 결제": ["PYPL", "COIN", "V", "MA"],
    "헬스케어 · 제약": ["LLY", "JNJ", "PFE", "MRNA"],
    "방산 · 항공": ["LMT", "RTX", "BA"],
    "에너지": ["XOM", "CVX", "OXY"],
}


# ── Phase 3: 테마 → 흐름(단계별 파생 섹터) → 종목 (큐레이션) ──
# 주의: '지금 주목받는 흐름'을 정리한 것이지, 오른다는 예측이 아닙니다.
# chain = 단계 리스트, 각 단계에 그 단계의 종목들.
THEMES = {
    "AI 인프라": {
        "desc": "AI를 돌리려면 엄청난 계산이 필요해요. 그래서 'AI 골드러시의 곡괭이' 격인 "
                "칩·서버·전력·냉각 수요가 단계적으로 함께 커지는 흐름이에요.",
        "chain": [
            {"name": "반도체", "stocks": ["NVDA", "AVGO", "AMD"]},
            {"name": "데이터센터 장비", "stocks": ["SMCI", "ANET", "DELL"]},
            {"name": "전력", "stocks": ["ETN", "GEV"]},
            {"name": "냉각", "stocks": ["VRT"]},
        ],
    },
    "비만 치료제 (GLP-1)": {
        "desc": "비만·당뇨 치료제(위고비·젭바운드 등)가 폭발적으로 팔리면서, "
                "이를 만드는 제약사에 관심이 쏠리는 흐름이에요.",
        "chain": [
            {"name": "제약", "stocks": ["LLY", "NVO"]},
        ],
    },
    "양자컴퓨팅": {
        "desc": "기존 컴퓨터로 어려운 계산을 푸는 차세대 컴퓨팅 기대주예요. "
                "아직 초기 단계라 변동이 크고 기대가 앞서가는 편입니다.",
        "chain": [
            {"name": "양자 하드웨어·소프트웨어", "stocks": ["IONQ", "RGTI", "QBTS"]},
        ],
    },
    "방산 · 안보": {
        "desc": "지정학 긴장과 각국 국방비 증가로, 무기·항공·방위 기업에 "
                "관심이 쏠리는 흐름이에요.",
        "chain": [
            {"name": "방산·항공", "stocks": ["LMT", "RTX", "NOC", "GD"]},
        ],
    },
    "전력 · 에너지전환": {
        "desc": "AI 데이터센터와 전기화로 전력 수요가 급증하면서, "
                "발전·전력장비 기업이 주목받는 흐름이에요.",
        "chain": [
            {"name": "발전", "stocks": ["GEV", "VST", "NRG"]},
            {"name": "전력장비", "stocks": ["ETN"]},
        ],
    },
    "사이버보안": {
        "desc": "디지털·AI 확산으로 보안 위협이 늘면서, "
                "보안 소프트웨어 기업 수요가 커지는 흐름이에요.",
        "chain": [
            {"name": "보안 소프트웨어", "stocks": ["CRWD", "PANW", "ZS", "S"]},
        ],
    },
}


# ── 벤치마킹: 회사 한눈에 브리프 + 근거(업종/뉴스) ──────────
# yfinance로 미국 종목 기본정보·뉴스를 가져옴. 실패해도 앱은 정상 동작(빈 값 반환).
_SECTOR_KO = {
    "Technology": "기술", "Communication Services": "커뮤니케이션",
    "Healthcare": "헬스케어", "Financial Services": "금융",
    "Consumer Cyclical": "소비재(경기민감)", "Consumer Defensive": "소비재(필수)",
    "Industrials": "산업재", "Energy": "에너지", "Utilities": "유틸리티",
    "Basic Materials": "소재", "Real Estate": "부동산",
}


def _humanize_cap(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v >= 1e12:
        return f"${v/1e12:.2f}조"
    if v >= 1e8:
        return f"${v/1e8:,.0f}억"
    return f"${v:,.0f}"


def company_brief(symbol):
    """회사 기본정보 + 최근 뉴스 2건. 못 가져오면 빈 값으로 graceful."""
    out = {"name": symbol, "sector": None, "industry": None,
           "cap": None, "pe": None, "news": []}
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        out["name"] = info.get("shortName") or info.get("longName") or symbol
        sec = info.get("sector")
        out["sector"] = _SECTOR_KO.get(sec, sec)
        out["industry"] = info.get("industry")
        out["cap"] = _humanize_cap(info.get("marketCap"))
        pe = info.get("trailingPE")
        out["pe"] = f"{pe:.1f}배" if isinstance(pe, (int, float)) else None
        try:
            raw = tk.news or []
        except Exception:
            raw = []
        titles = []
        for item in raw[:6]:
            t = item.get("title")
            if not t and isinstance(item.get("content"), dict):
                t = item["content"].get("title")
            if t:
                titles.append(t)
        out["news"] = titles[:2]
    except Exception:
        pass
    return out
