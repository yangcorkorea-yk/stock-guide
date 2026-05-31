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


def reference_levels(df):
    """
    규칙 기반 진입/매도/손절 참고 가격대. **예측·추천이 아님 — 규칙으로 계산한 참고값**.

    반환:
      close: 현재가
      atr14: 최근 14일 평균 진폭(ATR)
      entry: [{label, price, rule}, ...]  # 진입 후보 가격대
      exit:  [{label, price, rule}, ...]  # 매도 후보 가격대
      stop:  [{label, price, rule}, ...]  # 손절 후보 라인
    """
    df2 = add_indicators(df).dropna()
    last = df2.iloc[-1]
    close = float(last['close'])
    bb_lower = float(last['bb_lower'])
    bb_upper = float(last['bb_upper'])
    ma_long = float(last['ma_long'])

    recent = df2.tail(20)
    swing_low_20 = float(recent['low'].min())
    swing_high_20 = float(recent['high'].max())
    high_52 = float(df2['high'].tail(252).max())

    # ATR(14): True Range 14일 평균
    hl = df2['high'] - df2['low']
    hc = (df2['high'] - df2['close'].shift()).abs()
    lc = (df2['low'] - df2['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr14 = float(tr.tail(14).mean())

    return {
        "close": close,
        "atr14": atr14,
        "entry": [
            {"label": "볼린저 하단", "price": bb_lower,
             "rule": "최근 20일 변동폭의 아래쪽 띠 — '평소보다 싸 보이는' 가격대"},
            {"label": "최근 20일 저점", "price": swing_low_20,
             "rule": "지지선으로 자주 거론되는 가격"},
            {"label": "장기(20일) 이평선", "price": ma_long,
             "rule": "추세를 가르는 평균선 — 위로 회복하면 추세 복귀로 해석"},
        ],
        "exit": [
            {"label": "볼린저 상단", "price": bb_upper,
             "rule": "최근 20일 변동폭의 위쪽 띠 — '평소보다 비싼' 가격대"},
            {"label": "최근 20일 고점", "price": swing_high_20,
             "rule": "저항선으로 자주 거론되는 가격"},
            {"label": "52주 고점", "price": high_52,
             "rule": "장기 강세 천장"},
        ],
        "stop": [
            {"label": "최근 20일 저점 −3%", "price": swing_low_20 * 0.97,
             "rule": "스윙 저점 살짝 아래 — 이 선을 깨면 흐름이 무너졌다고 봄"},
            {"label": f"현재가 − ATR×2", "price": close - 2 * atr14,
             "rule": f"평균 일일 진폭(${atr14:.2f})의 2배 만큼 아래"},
        ],
    }


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
# 모든 티커는 실재하는 미국 상장 티커. scripts/verify_tickers.py로 검증함.
SECTORS = {
    "AI · 빅테크": ["MSFT", "GOOGL", "META", "AMZN", "AAPL", "NVDA", "ORCL",
                  "IBM", "ADBE", "CRM", "PLTR"],
    "반도체": ["NVDA", "AMD", "AVGO", "TSM", "MU", "INTC", "QCOM", "TXN",
              "AMAT", "LRCX", "KLAC", "ASML", "ARM"],
    "반도체 장비": ["AMAT", "LRCX", "KLAC", "ASML", "TER", "AMKR", "ONTO",
                  "CDNS", "SNPS", "ARM", "ENTG", "MKSI"],
    "양자컴퓨팅": ["IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL", "MSFT",
                  "HON", "AMZN", "INTC"],
    "전기차 · 2차전지": ["TSLA", "RIVN", "LCID", "NIO", "LI", "XPEV", "F",
                       "GM", "ALB", "LIT", "QS", "CHPT"],
    "클라우드 · SaaS": ["CRM", "NOW", "SNOW", "DDOG", "NET", "MDB", "OKTA",
                      "ZS", "TEAM", "WDAY", "ADBE", "ORCL"],
    "핀테크 · 결제": ["PYPL", "COIN", "V", "MA", "XYZ", "AFRM", "SOFI",
                    "HOOD", "NU", "FOUR", "MELI", "MSTR"],
    "헬스케어 · 제약": ["LLY", "JNJ", "PFE", "MRNA", "MRK", "ABBV", "BMY",
                      "NVS", "GILD", "AMGN", "AZN", "NVO"],
    "바이오테크": ["REGN", "VRTX", "ISRG", "IDXX", "ILMN", "BIIB", "BMRN",
                 "ALNY", "IONS", "CRSP", "MRNA", "BNTX"],
    "방산 · 항공": ["LMT", "RTX", "BA", "NOC", "GD", "LHX", "TDG", "HII",
                  "KTOS", "BWXT", "AVAV"],
    "에너지": ["XOM", "CVX", "OXY", "COP", "SLB", "EOG", "PSX", "MPC",
              "VLO", "KMI", "FANG", "WMB"],
    "유틸리티": ["NEE", "SO", "DUK", "AEP", "EXC", "SRE", "D", "PCG",
               "XEL", "ED", "VST", "CEG"],
    "소비재 (필수)": ["WMT", "PG", "KO", "PEP", "COST", "MCD", "CL", "KMB",
                   "MDLZ", "GIS", "MNST", "HSY"],
    "소비재 (경기)": ["AMZN", "HD", "NKE", "SBUX", "TJX", "LOW", "BKNG",
                   "MAR", "ROST", "DPZ", "CMG", "F"],
    "금융 · 은행": ["JPM", "BAC", "WFC", "GS", "MS", "C", "USB", "PNC",
                  "TFC", "BLK", "BX", "SCHW"],
    "미디어 · 엔터": ["NFLX", "DIS", "WBD", "WMG", "EA", "TTWO", "RBLX",
                    "SPOT", "LYV", "FWONK", "FOXA", "NWSA"],
    "통신": ["T", "VZ", "TMUS", "CMCSA", "CHTR", "AMX", "BCE", "CCOI",
            "LUMN", "VOD", "NOK"],
    "부동산 (REIT)": ["PLD", "AMT", "EQIX", "PSA", "O", "SPG", "WELL",
                    "DLR", "VICI", "EXR", "CCI", "AVB"],
    "산업재 · 기계": ["CAT", "DE", "HON", "GE", "MMM", "ETN", "EMR", "ITW",
                    "ROK", "PH", "CMI", "FAST"],
    "소재": ["LIN", "SHW", "APD", "FCX", "NEM", "ECL", "NUE", "DD",
            "DOW", "CTVA", "ALB", "VMC"],
    "운송 · 물류": ["UPS", "FDX", "UNP", "NSC", "CSX", "ODFL", "JBHT",
                  "EXPD", "CHRW", "LUV", "DAL", "UAL"],
    "여행 · 호텔": ["BKNG", "MAR", "HLT", "ABNB", "RCL", "CCL", "NCLH",
                  "EXPE", "H", "MGM", "WYNN", "LVS"],
}


# ── Phase 3: 테마 → 흐름(단계별 파생 섹터) → 종목 (큐레이션) ──
# 주의: '지금 주목받는 흐름'을 정리한 것이지, 오른다는 예측이 아닙니다.
# chain = 단계 리스트, 각 단계에 그 단계의 종목들.
# keywords = '뜨는 테마' 집계용 (뉴스 본문/제목에서 매칭할 영문 키워드)
THEMES = {
    "AI 인프라": {
        "desc": "AI를 돌리려면 엄청난 계산이 필요해요. 그래서 'AI 골드러시의 곡괭이' 격인 "
                "칩·서버·전력·냉각 수요가 단계적으로 함께 커지는 흐름이에요.",
        "keywords": ["AI infrastructure", "GPU", "data center", "datacenter",
                     "artificial intelligence", "AI chip", "AI server"],
        "chain": [
            {"name": "반도체", "stocks": ["NVDA", "AVGO", "AMD", "TSM"]},
            {"name": "데이터센터 장비", "stocks": ["SMCI", "ANET", "DELL", "HPE"]},
            {"name": "전력", "stocks": ["ETN", "GEV", "VST", "NRG"]},
            {"name": "냉각", "stocks": ["VRT"]},
        ],
    },
    "비만 치료제 (GLP-1)": {
        "desc": "비만·당뇨 치료제(위고비·젭바운드 등)가 폭발적으로 팔리면서, "
                "이를 만드는 제약사·관련 기업들에 관심이 쏠리는 흐름이에요.",
        "keywords": ["GLP-1", "Wegovy", "Ozempic", "Zepbound", "Mounjaro",
                     "obesity drug", "weight loss drug", "semaglutide", "tirzepatide"],
        "chain": [
            {"name": "제약 메이저", "stocks": ["LLY", "NVO", "PFE", "AMGN"]},
            {"name": "차세대 후보", "stocks": ["VKTX", "ALT"]},
            {"name": "당뇨/진단", "stocks": ["DXCM", "MDT", "ABT", "ISRG"]},
        ],
    },
    "양자컴퓨팅": {
        "desc": "기존 컴퓨터로 어려운 계산을 푸는 차세대 컴퓨팅 기대주예요. "
                "아직 초기 단계라 변동이 크고 기대가 앞서가는 편입니다.",
        "keywords": ["quantum computing", "qubit", "quantum computer",
                     "quantum supremacy"],
        "chain": [
            {"name": "양자 순수주", "stocks": ["IONQ", "RGTI", "QBTS", "QUBT"]},
            {"name": "빅테크 양자", "stocks": ["IBM", "GOOGL", "MSFT", "HON"]},
            {"name": "인접 반도체", "stocks": ["NVDA", "INTC"]},
        ],
    },
    "방산 · 안보": {
        "desc": "지정학 긴장과 각국 국방비 증가로, 무기·항공·방위 기업에 "
                "관심이 쏠리는 흐름이에요.",
        "keywords": ["defense", "military", "missile", "weapons", "Pentagon",
                     "NATO", "geopolitical"],
        "chain": [
            {"name": "방산 메이저", "stocks": ["LMT", "RTX", "NOC", "GD", "LHX"]},
            {"name": "드론·무인", "stocks": ["KTOS", "AVAV"]},
            {"name": "사이버 안보", "stocks": ["CRWD", "PANW", "PLTR"]},
        ],
    },
    "전력 · 에너지전환": {
        "desc": "AI 데이터센터와 전기화로 전력 수요가 급증하면서, "
                "발전·전력장비·원자력 기업이 주목받는 흐름이에요.",
        "keywords": ["power grid", "electricity demand", "nuclear power",
                     "small modular reactor", "SMR", "energy transition"],
        "chain": [
            {"name": "발전", "stocks": ["GEV", "VST", "NRG", "CEG"]},
            {"name": "전력장비", "stocks": ["ETN", "EMR", "ROK"]},
            {"name": "원자력", "stocks": ["CCJ", "BWXT", "SMR"]},
            {"name": "천연가스", "stocks": ["KMI", "WMB"]},
        ],
    },
    "사이버보안": {
        "desc": "디지털·AI 확산으로 보안 위협이 늘면서, "
                "보안 소프트웨어 기업 수요가 커지는 흐름이에요.",
        "keywords": ["cybersecurity", "data breach", "ransomware",
                     "hack", "zero trust", "endpoint security"],
        "chain": [
            {"name": "보안 소프트웨어", "stocks": ["CRWD", "PANW", "FTNT"]},
            {"name": "클라우드 보안", "stocks": ["ZS", "S", "NET"]},
            {"name": "ID/액세스", "stocks": ["OKTA", "GEN"]},
            {"name": "데이터 보안", "stocks": ["VRNS", "RPD"]},
        ],
    },
    "전기차 · 자율주행": {
        "desc": "전기차 보급과 자율주행 기술 발전으로, 완성차·배터리·"
                "충전 인프라까지 함께 움직이는 흐름이에요.",
        "keywords": ["electric vehicle", "EV", "autonomous driving",
                     "self-driving", "robotaxi", "battery", "lidar"],
        "chain": [
            {"name": "EV 완성차", "stocks": ["TSLA", "RIVN", "LCID", "NIO", "LI", "XPEV"]},
            {"name": "전통 OEM", "stocks": ["F", "GM", "STLA"]},
            {"name": "배터리·소재", "stocks": ["ALB", "LIT"]},
            {"name": "충전·라이다", "stocks": ["CHPT", "MBLY", "OUST"]},
        ],
    },
    "우주 · 위성": {
        "desc": "민간 우주 시대가 열리며, 로켓 발사·위성 통신·우주 "
                "방산까지 관심이 쏠리는 흐름이에요.",
        "keywords": ["space", "rocket launch", "satellite", "SpaceX",
                     "low earth orbit", "LEO"],
        "chain": [
            {"name": "발사·로켓", "stocks": ["RKLB", "ASTS", "SPCE"]},
            {"name": "위성", "stocks": ["IRDM", "PL", "BKSY"]},
            {"name": "방산 우주", "stocks": ["LMT", "NOC", "BA", "RTX"]},
        ],
    },
    "로봇 · 자동화": {
        "desc": "AI와 결합한 휴머노이드·산업 로봇·창고 자동화가 "
                "동시에 부상하는 흐름이에요.",
        "keywords": ["humanoid robot", "robotics", "automation",
                     "industrial robot", "warehouse robot"],
        "chain": [
            {"name": "산업 로봇", "stocks": ["HON", "ROK", "FANUY"]},
            {"name": "의료 로봇", "stocks": ["ISRG", "SYK"]},
            {"name": "휴머노이드·AI", "stocks": ["TSLA", "NVDA", "MSFT", "GOOGL"]},
            {"name": "창고 자동화", "stocks": ["AMZN", "SYM"]},
        ],
    },
    "클라우드 · SaaS": {
        "desc": "기업의 데이터·업무가 클라우드로 옮겨가면서, 인프라부터 "
                "분석·협업 소프트웨어까지 함께 큰 흐름이에요.",
        "keywords": ["cloud computing", "SaaS", "AWS", "Azure", "Google Cloud",
                     "cloud infrastructure"],
        "chain": [
            {"name": "하이퍼스케일러", "stocks": ["MSFT", "GOOGL", "AMZN", "ORCL"]},
            {"name": "데이터·관측", "stocks": ["SNOW", "DDOG", "MDB", "NET"]},
            {"name": "디자인·협업", "stocks": ["NOW", "CRM", "TEAM", "ADBE"]},
        ],
    },
    "핀테크 · 디지털 결제": {
        "desc": "스마트폰 결제·BNPL·디지털 자산이 일상으로 들어오며, "
                "기존 결제 인프라와 핀테크 신흥주가 함께 움직여요.",
        "keywords": ["fintech", "digital payment", "BNPL", "stablecoin",
                     "crypto", "neobank"],
        "chain": [
            {"name": "결제 인프라", "stocks": ["V", "MA"]},
            {"name": "디지털 지갑", "stocks": ["PYPL", "XYZ", "AFRM"]},
            {"name": "핀테크 신흥", "stocks": ["SOFI", "HOOD", "NU"]},
            {"name": "크립토 연관", "stocks": ["COIN", "MSTR"]},
        ],
    },
    "친환경 · 신재생": {
        "desc": "탄소중립과 정부 보조금으로 태양광·풍력·수소 등 "
                "신재생 에너지 기업이 주목받는 흐름이에요.",
        "keywords": ["solar power", "wind power", "renewable energy",
                     "clean energy", "hydrogen", "green energy"],
        "chain": [
            {"name": "태양광", "stocks": ["FSLR", "ENPH", "RUN", "SEDG"]},
            {"name": "풍력", "stocks": ["GE", "GEV", "NEE"]},
            {"name": "수소", "stocks": ["PLUG", "BE", "BLDP"]},
        ],
    },
    "반도체 첨단공정": {
        "desc": "AI 칩 수요로 첨단 미세공정·패키징·EDA 도구까지 "
                "반도체 장비 생태계 전체가 바쁘게 도는 흐름이에요.",
        "keywords": ["semiconductor equipment", "lithography", "EUV",
                     "chip manufacturing", "advanced packaging"],
        "chain": [
            {"name": "노광", "stocks": ["ASML"]},
            {"name": "식각·증착", "stocks": ["AMAT", "LRCX", "KLAC", "TER"]},
            {"name": "후공정·패키징", "stocks": ["AMKR", "ONTO"]},
            {"name": "EDA/IP", "stocks": ["CDNS", "SNPS", "ARM"]},
        ],
    },
    "데이터센터 인프라": {
        "desc": "AI 붐으로 데이터센터 자체가 부동산·서버·네트워킹·광통신 "
                "전 영역에서 폭발적으로 늘어나는 흐름이에요.",
        "keywords": ["data center", "datacenter", "colocation",
                     "hyperscale", "fiber optic", "interconnect"],
        "chain": [
            {"name": "DC REIT", "stocks": ["EQIX", "DLR", "IRM"]},
            {"name": "서버·HW", "stocks": ["SMCI", "DELL", "HPE"]},
            {"name": "네트워킹", "stocks": ["ANET", "CSCO", "CIEN"]},
            {"name": "광통신", "stocks": ["COHR", "LITE"]},
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
    """회사 기본정보 + 펀더멘털 + 최근 뉴스. 못 가져온 항목은 None으로 graceful."""
    out = {
        "name": symbol, "sector": None, "industry": None,
        "cap": None, "pe": None,
        # 펀더멘털
        "pe_fwd": None, "psr": None, "pbr": None,
        "div_yield": None, "op_margin": None, "profit_margin": None,
        "rev_growth": None, "earnings_growth": None,
        "roe": None, "beta": None,
        "news": [],
    }
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

        def _ratio(v, suffix="배"):
            return f"{v:.1f}{suffix}" if isinstance(v, (int, float)) else None

        def _pct(v, signed=False):
            if not isinstance(v, (int, float)):
                return None
            fmt = f"{v*100:+.1f}%" if signed else f"{v*100:.1f}%"
            return fmt

        out["pe"] = _ratio(info.get("trailingPE"))
        out["pe_fwd"] = _ratio(info.get("forwardPE"))
        out["psr"] = _ratio(info.get("priceToSalesTrailing12Months"))
        out["pbr"] = _ratio(info.get("priceToBook"))

        # 배당수익률: yfinance 최근 버전은 percent(2.5=2.5%), 옛 버전은 decimal(0.025).
        dy = info.get("dividendYield")
        if isinstance(dy, (int, float)) and dy > 0:
            pct = dy if dy > 1 else dy * 100
            out["div_yield"] = f"{pct:.2f}%"
        elif isinstance(dy, (int, float)):
            out["div_yield"] = "0%"

        out["op_margin"] = _pct(info.get("operatingMargins"))
        out["profit_margin"] = _pct(info.get("profitMargins"))
        out["rev_growth"] = _pct(info.get("revenueGrowth"), signed=True)
        out["earnings_growth"] = _pct(info.get("earningsGrowth"), signed=True)
        out["roe"] = _pct(info.get("returnOnEquity"))
        beta = info.get("beta")
        if isinstance(beta, (int, float)):
            out["beta"] = f"{beta:.2f}"

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


FUNDAMENTALS_HELP = """\
**PER (주가수익비율)** : 주가 ÷ 1주당 순이익. 작을수록 '버는 돈 대비 주가가 싸 보임'.
같은 업종끼리만 비교가 의미 있어요. 적자 회사는 표시 안 됨.

**PSR (주가매출비율)** : 주가 ÷ 1주당 매출. 적자 회사·성장주 평가에 유용.

**배당수익률** : 1년 배당금 ÷ 주가. 0%면 배당 없는 회사예요.

**영업이익률** : 매출 100원 중 본업으로 남긴 이익이 몇 원인지. 클수록 본업 잘 버는 회사.

**매출 성장(YoY)** : 작년 같은 분기 대비 매출이 얼마나 늘었나. 성장주일수록 큼.

**ROE (자기자본수익률)** : 자기 돈으로 얼마나 효율적으로 이익을 냈나. 15%↑면 보통 우량으로 봄.

⚠️ 위 숫자들은 한 시점의 스냅샷이에요. 한 줄 비교보단 **추세**와 **업종 동료**랑의 비교가 더 중요해요.
"""
