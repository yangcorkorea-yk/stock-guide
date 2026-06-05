"""
일봉 데이터에서 교과서 기술적 신호를 룰 기반으로 감지.

핵심 원칙 (프로젝트 CLAUDE.md):
- 예측·매수/매도 라벨 금지 → "강세 반전 후보 / 약세 반전 후보" 같은 서술형
- 후행지표·오탐 가능성은 caveat에 솔직히 표시
- 최근 N일 안에서만 감지 (오래된 신호는 의미 없음)

반환 스키마 (모든 detect_* 함수):
  {
    "name": "한국어 이름 (예: '망치형')",
    "kind": "candle | cross | breakout",
    "direction": "강세 | 약세 | 중립",
    "date": "YYYY-MM-DD",
    "desc": "한 줄 설명",
    "caveat": "한계·주의사항",
  }
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional


# ──────────────────────────────────────────────
# 캔들 패턴 (반전 신호)
# ──────────────────────────────────────────────
def _candle_anatomy(row) -> dict:
    o, c, h, l = float(row['open']), float(row['close']), float(row['high']), float(row['low'])
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    total = h - l
    return {
        "o": o, "c": c, "h": h, "l": l,
        "body": body, "upper": upper, "lower": lower, "total": total,
        "is_up": c >= o,
    }


def _is_hammer(a: dict) -> bool:
    """망치형 — 아래꼬리 ≥ 몸통×2, 위꼬리 작음, 몸통이 봉 상단에 위치."""
    if a["total"] == 0 or a["body"] == 0:
        return False
    return (a["lower"] >= a["body"] * 2
            and a["upper"] <= a["body"] * 0.5
            and a["body"] / a["total"] >= 0.1)


def _is_shooting_star(a: dict) -> bool:
    """유성형 — 위꼬리 ≥ 몸통×2, 아래꼬리 작음."""
    if a["total"] == 0 or a["body"] == 0:
        return False
    return (a["upper"] >= a["body"] * 2
            and a["lower"] <= a["body"] * 0.5
            and a["body"] / a["total"] >= 0.1)


def _is_bullish_engulfing(prev: dict, curr: dict) -> bool:
    """상승장악형 — 어제 음봉, 오늘 양봉이 어제 몸통을 감쌈."""
    if prev["is_up"] or not curr["is_up"]:
        return False
    return (curr["o"] <= prev["c"]
            and curr["c"] >= prev["o"]
            and curr["body"] > prev["body"])


def _is_bearish_engulfing(prev: dict, curr: dict) -> bool:
    """하락장악형 — 어제 양봉, 오늘 음봉이 어제 몸통을 감쌈."""
    if not prev["is_up"] or curr["is_up"]:
        return False
    return (curr["o"] >= prev["c"]
            and curr["c"] <= prev["o"]
            and curr["body"] > prev["body"])


def _is_morning_star(d1: dict, d2: dict, d3: dict) -> bool:
    """샛별형 — 큰 음봉 → 작은 몸통 → 큰 양봉 (D1 중점 위에서 마감)."""
    if d1["is_up"] or not d3["is_up"]:
        return False
    if d1["total"] == 0 or d3["total"] == 0:
        return False
    small = d2["body"] <= d1["body"] * 0.5
    midpoint_d1 = (d1["o"] + d1["c"]) / 2
    return small and d3["c"] >= midpoint_d1


def _is_evening_star(d1: dict, d2: dict, d3: dict) -> bool:
    """석별형 — 큰 양봉 → 작은 몸통 → 큰 음봉."""
    if not d1["is_up"] or d3["is_up"]:
        return False
    if d1["total"] == 0 or d3["total"] == 0:
        return False
    small = d2["body"] <= d1["body"] * 0.5
    midpoint_d1 = (d1["o"] + d1["c"]) / 2
    return small and d3["c"] <= midpoint_d1


def _is_doji(a: dict) -> bool:
    """도지 — 몸통이 봉 전체의 10% 이하."""
    if a["total"] == 0:
        return False
    return a["body"] / a["total"] <= 0.1


CANDLE_DEFS = {
    "망치형": {
        "direction": "강세",
        "desc": "아래꼬리 긴 캔들 — 내렸다가 매수세가 되받침. 추세 끝에서 나타나면 강세 반전 후보.",
        "caveat": "추세 끝(과매도)에서 거래량 동반될 때만 신뢰. 거래량 없이는 우연일 가능성.",
        "glossary_key": "망치형",
    },
    "유성형": {
        "direction": "약세",
        "desc": "위꼬리 긴 캔들 — 올랐다가 매도세에 눌림. 추세 끝에서 약세 반전 후보.",
        "caveat": "추세 끝(과열)에서 거래량 동반될 때만 신뢰.",
        "glossary_key": "유성형",
    },
    "상승장악형": {
        "direction": "강세",
        "desc": "어제 음봉을 오늘 양봉이 완전히 감쌈. 매수세 우위 전환 신호.",
        "caveat": "하락 추세 끝에서 나와야 의미. 횡보 중에는 약한 신호.",
        "glossary_key": "상승장악형",
    },
    "하락장악형": {
        "direction": "약세",
        "desc": "어제 양봉을 오늘 음봉이 완전히 감쌈. 매도세 우위 전환 신호.",
        "caveat": "상승 추세 끝에서 나와야 의미. 횡보 중에는 약한 신호.",
        "glossary_key": "하락장악형",
    },
    "샛별형": {
        "direction": "강세",
        "desc": "큰 음봉 → 망설임(작은 몸통) → 큰 양봉. 3봉짜리 바닥권 반전 신호.",
        "caveat": "3일짜리라 확인까지 시간 걸림. 4번째 봉에서도 추세 이어져야 진짜.",
        "glossary_key": "샛별형",
    },
    "석별형": {
        "direction": "약세",
        "desc": "큰 양봉 → 망설임 → 큰 음봉. 3봉짜리 천장권 반전 신호.",
        "caveat": "확인까지 시간 걸림. 다음 봉 흐름 같이 봐야.",
        "glossary_key": "석별형",
    },
    "도지": {
        "direction": "중립",
        "desc": "시가≈종가 — 매수·매도 힘이 균형. 추세 끝에 나오면 전환 신호로 자주 거론.",
        "caveat": "단독으론 약함. 위치(과열/과매도 구간)와 거래량 함께 봐야.",
        "glossary_key": "도지",
    },
}


def detect_candles(df: pd.DataFrame, lookback: int = 10) -> list[dict]:
    """최근 lookback 일 안에서 캔들 패턴 감지."""
    if len(df) < 4:
        return []
    results = []
    start = max(0, len(df) - lookback)
    # 단일·2봉 패턴
    for i in range(max(start, 1), len(df)):
        curr = _candle_anatomy(df.iloc[i])
        prev = _candle_anatomy(df.iloc[i - 1])
        d = str(df.index[i].date())
        if _is_hammer(curr):
            results.append({"name": "망치형", "kind": "candle", "date": d, **CANDLE_DEFS["망치형"]})
        if _is_shooting_star(curr):
            results.append({"name": "유성형", "kind": "candle", "date": d, **CANDLE_DEFS["유성형"]})
        if _is_doji(curr):
            results.append({"name": "도지", "kind": "candle", "date": d, **CANDLE_DEFS["도지"]})
        if _is_bullish_engulfing(prev, curr):
            results.append({"name": "상승장악형", "kind": "candle", "date": d, **CANDLE_DEFS["상승장악형"]})
        if _is_bearish_engulfing(prev, curr):
            results.append({"name": "하락장악형", "kind": "candle", "date": d, **CANDLE_DEFS["하락장악형"]})
    # 3봉 패턴
    for i in range(max(start, 2), len(df)):
        d1 = _candle_anatomy(df.iloc[i - 2])
        d2 = _candle_anatomy(df.iloc[i - 1])
        d3 = _candle_anatomy(df.iloc[i])
        d = str(df.index[i].date())
        if _is_morning_star(d1, d2, d3):
            results.append({"name": "샛별형", "kind": "candle", "date": d, **CANDLE_DEFS["샛별형"]})
        if _is_evening_star(d1, d2, d3):
            results.append({"name": "석별형", "kind": "candle", "date": d, **CANDLE_DEFS["석별형"]})
    return results


# ──────────────────────────────────────────────
# 이동평균선 크로스
# ──────────────────────────────────────────────
def _find_cross(short: pd.Series, long: pd.Series, lookback: int) -> Optional[tuple[str, int]]:
    """
    short가 long을 위로 뚫은 가장 최근 시점 → ("golden", index)
    아래로 뚫은 가장 최근 시점 → ("dead", index)
    lookback 안에 없으면 None.
    """
    if len(short) < 2:
        return None
    diff = short - long
    sign = np.sign(diff)
    # 마지막 lookback 구간에서 부호 전환점 찾기
    start = max(1, len(diff) - lookback)
    last_cross = None
    for i in range(start, len(diff)):
        if pd.isna(sign.iloc[i]) or pd.isna(sign.iloc[i - 1]):
            continue
        if sign.iloc[i - 1] <= 0 and sign.iloc[i] > 0:
            last_cross = ("golden", i)
        elif sign.iloc[i - 1] >= 0 and sign.iloc[i] < 0:
            last_cross = ("dead", i)
    return last_cross


def detect_ma_crosses(df: pd.DataFrame, lookback: int = 10) -> list[dict]:
    """
    두 종류 크로스를 본다:
      · 50/200 (전통적 골든·데드 크로스 — 장기)
      · 20/60 (단기 추세 전환 — 빨리 잡힘)
    """
    close = df["close"]
    if len(close) < 200:
        # 200일 미만이면 장기 크로스는 못 봄
        ma50, ma200 = None, None
    else:
        ma50 = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    results = []

    if ma50 is not None and ma200 is not None:
        cr = _find_cross(ma50, ma200, lookback)
        if cr:
            kind, i = cr
            d = str(df.index[i].date())
            if kind == "golden":
                results.append({
                    "name": "골든크로스 (50일·200일)",
                    "kind": "cross",
                    "direction": "강세",
                    "date": d,
                    "desc": "50일선이 200일선을 위로 뚫음. 장기 추세 강세 전환의 대표 신호.",
                    "caveat": "후행지표 — 신호 발생 시점엔 이미 한참 오른 뒤일 수 있음. 200일선이 아직 하락 중이면 가짜 신호 가능.",
                    "glossary_key": "골든크로스",
                })
            else:
                results.append({
                    "name": "데드크로스 (50일·200일)",
                    "kind": "cross",
                    "direction": "약세",
                    "date": d,
                    "desc": "50일선이 200일선을 아래로 뚫음. 장기 추세 약세 전환의 대표 신호.",
                    "caveat": "후행지표 — 200일선이 아직 상승 중이면 흔들리지 마세요. 휩쏘(가짜 신호) 가능.",
                    "glossary_key": "데드크로스",
                })

    cr = _find_cross(ma20, ma60, lookback)
    if cr:
        kind, i = cr
        d = str(df.index[i].date())
        if kind == "golden":
            results.append({
                "name": "단기 크로스 (20일·60일 ↑)",
                "kind": "cross",
                "direction": "강세",
                "date": d,
                "desc": "20일선이 60일선을 위로 뚫음. 단기 추세 전환 후보.",
                "caveat": "장기 크로스보다 빨리 잡히지만 그만큼 휩쏘도 잦음. 거래량 동반 여부 같이 보세요.",
                "glossary_key": "골든크로스",
            })
        else:
            results.append({
                "name": "단기 크로스 (20일·60일 ↓)",
                "kind": "cross",
                "direction": "약세",
                "date": d,
                "desc": "20일선이 60일선을 아래로 뚫음. 단기 추세 약화 후보.",
                "caveat": "장기 추세가 살아있으면 흔들리지 마세요. 휩쏘 가능.",
                "glossary_key": "데드크로스",
            })

    return results


# ──────────────────────────────────────────────
# 거래량 동반 돌파
# ──────────────────────────────────────────────
def detect_breakouts(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
    """
    최근 lookback 일 안에서:
      · 신고가(20일/52주) + 거래량 평균×1.5↑ → 강세 돌파
      · 신저가(20일) + 거래량 평균×1.5↑ → 약세 이탈
    """
    if len(df) < 21:
        return []
    results = []
    vol_ma20 = df["volume"].rolling(20).mean()
    start = max(20, len(df) - lookback)
    for i in range(start, len(df)):
        row = df.iloc[i]
        close = float(row["close"])
        vol = float(row["volume"])
        vma = float(vol_ma20.iloc[i]) if not pd.isna(vol_ma20.iloc[i]) else 0
        if vma == 0:
            continue

        # 직전 20일 고가·저가 (오늘 제외)
        prev_high_20 = float(df["high"].iloc[i - 20:i].max())
        prev_low_20 = float(df["low"].iloc[i - 20:i].min())
        d = str(df.index[i].date())

        if close > prev_high_20 and vol >= vma * 1.5:
            # 52주 신고가도 같이 체크
            tail_252 = df["high"].iloc[max(0, i - 252):i]
            is_52w = len(tail_252) > 0 and close > float(tail_252.max())
            label = "52주 신고가 돌파" if is_52w else "20일 신고가 돌파"
            results.append({
                "name": f"{label} (거래량 동반)",
                "kind": "breakout",
                "direction": "강세",
                "date": d,
                "desc": f"종가가 최근 {'52주' if is_52w else '20일'} 고점을 넘김 + 거래량 평균×1.5 이상. 진짜 돌파 신호로 자주 거론.",
                "caveat": "돌파 후 그 자리까지 눌렸다 다시 위로 가야 '진짜'. 거래량 없이 박스 안으로 회귀하면 가짜.",
                "glossary_key": "거래량 동반 돌파",
            })

        if close < prev_low_20 and vol >= vma * 1.5:
            results.append({
                "name": "20일 신저가 이탈 (거래량 동반)",
                "kind": "breakout",
                "direction": "약세",
                "date": d,
                "desc": "종가가 최근 20일 저점을 깸 + 거래량 평균×1.5 이상. 지지 이탈 신호.",
                "caveat": "단발성 패닉성 하락일 수 있음. 다음 날 회복하는지 같이 보세요.",
                "glossary_key": "신저가 이탈",
            })

    return results


# ──────────────────────────────────────────────
# 돌파 후 되돌림(리테스트) 감지
# ──────────────────────────────────────────────
def detect_retests(df: pd.DataFrame, lookback: int = 20, tol_pct: float = 0.01) -> list[dict]:
    """
    최근 lookback 일 안의 돌파를 찾아서, 그 이후 흐름이 리테스트 패턴인지 평가.

    상태 분류:
      · 진짜(성공): 돌파 → tol_pct 이내까지 눌렸다가 → 다시 돌파선 위로 회복
      · 가짜(실패): 돌파 → 박스 안으로 다시 회귀해 머무름(돌파선 -tol_pct*2 아래로 종가)
      · 진행 중:    돌파 → 아직 리테스트 또는 회복 미완

    돌파 기준: 종가 > 직전 20일 고점 + 거래량 ≥ 평균×1.5
    """
    if len(df) < 25:
        return []
    results = []
    vol_ma20 = df["volume"].rolling(20).mean()
    last_i = len(df) - 1
    start = max(20, len(df) - lookback)
    for i in range(start, len(df) - 1):  # 마지막 봉 자체는 후속 흐름 평가 불가
        row = df.iloc[i]
        close_t = float(row["close"])
        vol_t = float(row["volume"])
        vma = float(vol_ma20.iloc[i]) if not pd.isna(vol_ma20.iloc[i]) else 0
        if vma == 0:
            continue
        prev_high = float(df["high"].iloc[i - 20:i].max())
        if not (close_t > prev_high and vol_t >= vma * 1.5):
            continue  # 돌파 아님

        break_level = prev_high
        d_break = str(df.index[i].date())

        # 돌파 이후 흐름 (최대 10일 또는 데이터 끝까지)
        after = df.iloc[i + 1:min(i + 11, last_i + 1)]
        if len(after) == 0:
            continue

        touched_back = False
        recovered = False
        fell_through = False
        touch_idx = None
        for j in range(len(after)):
            row_a = after.iloc[j]
            low_a = float(row_a["low"])
            close_a = float(row_a["close"])
            # 박스 깊이 회귀 (가짜 신호)
            if close_a < break_level * (1 - tol_pct * 2):
                fell_through = True
                break
            # 돌파선 부근 터치
            if not touched_back and low_a <= break_level * (1 + tol_pct):
                touched_back = True
                touch_idx = j
            # 터치 후 다시 위로 회복
            if touched_back and close_a > break_level * (1 + tol_pct):
                recovered = True
                break

        last_date = str(after.index[-1].date())
        if fell_through:
            results.append({
                "name": "리테스트 실패 — 박스 회귀 (가짜 돌파)",
                "kind": "retest",
                "direction": "약세",
                "date": last_date,
                "desc": f"{d_break} 돌파 후 돌파선(\\${break_level:.2f}) 아래로 다시 깊게 내려가 머무름. 휩쏘 가능성.",
                "caveat": "패닉성 일시 하락일 수도 있음. 거래량과 다음 봉 확인.",
                "glossary_key": "돌파 후 리테스트",
            })
        elif recovered:
            results.append({
                "name": "리테스트 성공 — 진짜 돌파",
                "kind": "retest",
                "direction": "강세",
                "date": last_date,
                "desc": f"{d_break} 돌파 후 돌파선(\\${break_level:.2f})까지 눌렸다 다시 위로 회복. 옛 저항이 지지로 역할 전환.",
                "caveat": "추세가 약하거나 시장 전체가 약하면 다시 무너지기도 함.",
                "glossary_key": "돌파 후 리테스트",
            })
        elif touched_back:
            # 터치는 했는데 아직 회복 못 함
            results.append({
                "name": "리테스트 진행 중",
                "kind": "retest",
                "direction": "중립",
                "date": last_date,
                "desc": f"{d_break} 돌파 후 돌파선(\\${break_level:.2f}) 부근까지 눌림. 아직 회복 여부 미정.",
                "caveat": "다음 1~3봉에서 회복하면 진짜 / 더 내려가면 가짜로 판가름.",
                "glossary_key": "돌파 후 리테스트",
            })
    return results


# ──────────────────────────────────────────────
# 거래량 다이버전스 (가격↑ but 거래량 못 따라옴)
# ──────────────────────────────────────────────
def detect_divergence(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
    """
    가장 단순한 형태:
      · 종가가 직전 20일 최고치를 새로 갱신 + 그날 거래량 < 20일 평균 → 약세 다이버전스
      · 종가가 직전 20일 최저치를 새로 깨는데 + 거래량 < 20일 평균 → 강세 다이버전스
        (매도세조차 식어가는 신호 — '바닥권' 후보)
    """
    if len(df) < 25:
        return []
    results = []
    vol_ma20 = df["volume"].rolling(20).mean()
    start = max(20, len(df) - lookback)
    for i in range(start, len(df)):
        row = df.iloc[i]
        close = float(row["close"])
        vol = float(row["volume"])
        vma = float(vol_ma20.iloc[i]) if not pd.isna(vol_ma20.iloc[i]) else 0
        if vma == 0:
            continue
        prev_high = float(df["high"].iloc[i - 20:i].max())
        prev_low = float(df["low"].iloc[i - 20:i].min())
        d = str(df.index[i].date())

        # 약세 다이버전스: 신고가인데 거래량 못 따라옴
        if close > prev_high and vol < vma:
            results.append({
                "name": "거래량 다이버전스 (가격↑ 거래량↓)",
                "kind": "divergence",
                "direction": "약세",
                "date": d,
                "desc": "20일 신고가를 갱신했는데 거래량이 평소보다 적음. 상승 동력이 약해지는 신호.",
                "caveat": "단발성 휴장·반차익 매도일 수도 있음. 며칠 더 이어지면 신뢰도 ↑.",
                "glossary_key": "거래량 다이버전스",
            })

        # 강세 다이버전스: 신저가인데 매도조차 식음
        if close < prev_low and vol < vma:
            results.append({
                "name": "거래량 다이버전스 (가격↓ 거래량↓)",
                "kind": "divergence",
                "direction": "강세",
                "date": d,
                "desc": "20일 신저가를 깼는데 거래량도 평소보다 적음. 매도세가 식어가는 바닥권 후보.",
                "caveat": "추가 하락 후 반등으로 이어지는 경우도, 그대로 추세 이탈하는 경우도 있음.",
                "glossary_key": "거래량 다이버전스",
            })

    return results


# ──────────────────────────────────────────────
# 수평 지지·저항선 자동 감지
# ──────────────────────────────────────────────
def _local_peaks(series: pd.Series, window: int = 5) -> list[int]:
    """좌우 window 안에서 최대인 점들의 인덱스."""
    peaks = []
    for i in range(window, len(series) - window):
        left = series.iloc[i - window:i]
        right = series.iloc[i + 1:i + window + 1]
        v = series.iloc[i]
        if v >= left.max() and v >= right.max() and v > left.min():
            peaks.append(i)
    return peaks


def _local_troughs(series: pd.Series, window: int = 5) -> list[int]:
    """좌우 window 안에서 최소인 점들의 인덱스."""
    troughs = []
    for i in range(window, len(series) - window):
        left = series.iloc[i - window:i]
        right = series.iloc[i + 1:i + window + 1]
        v = series.iloc[i]
        if v <= left.min() and v <= right.min() and v < left.max():
            troughs.append(i)
    return troughs


def _cluster_levels(values: list[float], tol_pct: float = 0.015) -> list[dict]:
    """
    가격이 tol_pct(예: 1.5%) 이내인 값끼리 묶어서 평균 가격과 터치 횟수를 반환.
    반환: [{price, touches, members}], 터치 횟수 내림차순.
    """
    if not values:
        return []
    sorted_v = sorted(values)
    clusters = []
    cur = [sorted_v[0]]
    for v in sorted_v[1:]:
        if abs(v - cur[-1]) / cur[-1] <= tol_pct:
            cur.append(v)
        else:
            clusters.append(cur)
            cur = [v]
    clusters.append(cur)
    out = [{"price": sum(c) / len(c), "touches": len(c), "members": c} for c in clusters]
    out.sort(key=lambda x: (-x["touches"], -x["price"]))
    return out


def find_support_resistance(df: pd.DataFrame, window: int = 5, lookback: int = 120,
                            tol_pct: float = 0.015, min_touches: int = 2,
                            max_levels: int = 3) -> dict:
    """
    최근 lookback 일 안에서 지지선(저점 클러스터)과 저항선(고점 클러스터)을 찾는다.
    - min_touches 이상 반응한 자리만 유지
    - 현재가 기준 위쪽 = 저항, 아래쪽 = 지지로 분류
    - 각 max_levels 개까지

    반환:
      {
        "support":    [{price, touches}, ...],   # 현재가 아래
        "resistance": [{price, touches}, ...],   # 현재가 위
      }
    """
    if len(df) < window * 4:
        return {"support": [], "resistance": []}
    tail = df.tail(lookback)
    highs = tail["high"]
    lows = tail["low"]
    cur = float(df["close"].iloc[-1])

    peak_idx = _local_peaks(highs, window=window)
    trough_idx = _local_troughs(lows, window=window)
    peak_prices = [float(highs.iloc[i]) for i in peak_idx]
    trough_prices = [float(lows.iloc[i]) for i in trough_idx]

    # 클러스터링 (저점·고점 합쳐서 — 역할 전환 고려)
    all_levels = _cluster_levels(peak_prices + trough_prices, tol_pct=tol_pct)
    valid = [c for c in all_levels if c["touches"] >= min_touches]

    support = [c for c in valid if c["price"] < cur * 0.998]
    resistance = [c for c in valid if c["price"] > cur * 1.002]

    return {
        "support": support[:max_levels],
        "resistance": resistance[:max_levels],
    }


# ──────────────────────────────────────────────
# 차트 패턴 (더블바텀·더블탑·헤드앤숄더) — '후보' 수준 휴리스틱
# ──────────────────────────────────────────────
def _is_close(a: float, b: float, tol_pct: float = 0.02) -> bool:
    """두 값이 tol_pct 이내인가."""
    if max(abs(a), abs(b)) == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tol_pct


def detect_chart_patterns(df: pd.DataFrame, lookback: int = 90, window: int = 5,
                          tol_pct: float = 0.03) -> list[dict]:
    """
    최근 lookback 일 안에서 단순 차트 패턴 후보를 찾는다.
    엄격한 정의 대신 '관용적 룰' 사용 — 오탐 가능하므로 결과는 모두 '후보'로 표시.

    감지 패턴:
      · 더블바텀(W): 비슷한 높이 트로프 2개 + 사이에 피크 → 강세 후보
      · 더블탑(M):   비슷한 높이 피크 2개 + 사이에 트로프 → 약세 후보
      · 헤드앤숄더:  피크3 (가운데가 가장 높음) → 약세 후보
      · 역 헤드앤숄더: 트로프3 (가운데가 가장 낮음) → 강세 후보

    조건:
      · 패턴의 마지막 점이 lookback 안에 있어야 함
      · 양쪽 어깨/바닥은 tol_pct(3%) 이내 유사
      · 가운데 점은 양쪽보다 1.5% 이상 두드러져야 함
    """
    if len(df) < 30:
        return []
    tail = df.tail(lookback)
    highs = tail["high"].reset_index(drop=True)
    lows = tail["low"].reset_index(drop=True)
    dates = tail.index

    peak_idx = _local_peaks(highs, window=window)
    trough_idx = _local_troughs(lows, window=window)

    results = []

    # 더블탑 (M): 마지막 두 피크가 비슷한 높이
    if len(peak_idx) >= 2:
        p1, p2 = peak_idx[-2], peak_idx[-1]
        v1, v2 = highs.iloc[p1], highs.iloc[p2]
        # 사이에 트로프 존재
        between_troughs = [t for t in trough_idx if p1 < t < p2]
        if _is_close(v1, v2, tol_pct) and between_troughs:
            results.append({
                "name": "더블탑 (M) 후보",
                "kind": "pattern",
                "direction": "약세",
                "date": str(dates[p2].date()),
                "desc": f"비슷한 높이 두 봉우리 (\\${v1:.2f}, \\${v2:.2f}) 사이에 골 — 천장권 패턴 후보.",
                "caveat": "두 번째 봉우리 후 사이 골을 아래로 깰 때 '확정'으로 거론됨. 오탐 잦은 패턴이라 단독으론 약함.",
                "glossary_key": "차트 패턴 (더블탑·더블바텀)",
            })

    # 더블바텀 (W): 마지막 두 트로프가 비슷한 깊이
    if len(trough_idx) >= 2:
        t1, t2 = trough_idx[-2], trough_idx[-1]
        v1, v2 = lows.iloc[t1], lows.iloc[t2]
        between_peaks = [p for p in peak_idx if t1 < p < t2]
        if _is_close(v1, v2, tol_pct) and between_peaks:
            results.append({
                "name": "더블바텀 (W) 후보",
                "kind": "pattern",
                "direction": "강세",
                "date": str(dates[t2].date()),
                "desc": f"비슷한 깊이 두 바닥 (\\${v1:.2f}, \\${v2:.2f}) 사이에 봉우리 — 바닥권 패턴 후보.",
                "caveat": "두 번째 바닥 후 사이 봉우리를 위로 뚫을 때 '확정'으로 거론됨. 오탐 잦음.",
                "glossary_key": "차트 패턴 (더블탑·더블바텀)",
            })

    # 헤드앤숄더 (피크 3개, 가운데 가장 높음)
    if len(peak_idx) >= 3:
        ls, head, rs = peak_idx[-3], peak_idx[-2], peak_idx[-1]
        ls_v, head_v, rs_v = highs.iloc[ls], highs.iloc[head], highs.iloc[rs]
        if (head_v > ls_v * 1.015 and head_v > rs_v * 1.015
                and _is_close(ls_v, rs_v, tol_pct)):
            results.append({
                "name": "헤드앤숄더 후보",
                "kind": "pattern",
                "direction": "약세",
                "date": str(dates[rs].date()),
                "desc": f"세 봉우리 — 가운데(\\${head_v:.2f})가 양 어깨(\\${ls_v:.2f}, \\${rs_v:.2f})보다 도드라짐. 천장권 패턴 후보.",
                "caveat": "양 어깨 잇는 '넥라인'을 아래로 깰 때 확정으로 거론됨. 시각적 패턴이라 사람마다 다르게 봄.",
                "glossary_key": "차트 패턴 (헤드앤숄더)",
            })

    # 역 헤드앤숄더 (트로프 3개, 가운데 가장 낮음)
    if len(trough_idx) >= 3:
        ls, head, rs = trough_idx[-3], trough_idx[-2], trough_idx[-1]
        ls_v, head_v, rs_v = lows.iloc[ls], lows.iloc[head], lows.iloc[rs]
        if (head_v < ls_v * 0.985 and head_v < rs_v * 0.985
                and _is_close(ls_v, rs_v, tol_pct)):
            results.append({
                "name": "역 헤드앤숄더 후보",
                "kind": "pattern",
                "direction": "강세",
                "date": str(dates[rs].date()),
                "desc": f"세 바닥 — 가운데(\\${head_v:.2f})가 양 어깨(\\${ls_v:.2f}, \\${rs_v:.2f})보다 도드라짐. 바닥권 패턴 후보.",
                "caveat": "넥라인을 위로 뚫을 때 확정으로 거론됨. 시각적 패턴이라 주관적.",
                "glossary_key": "차트 패턴 (헤드앤숄더)",
            })

    return results


# ──────────────────────────────────────────────
# 종합: 모든 신호 한 번에 + 정리
# ──────────────────────────────────────────────
def detect_all(df: pd.DataFrame, lookback: int = 10) -> dict:
    """
    반환:
      {
        "bullish": [...],   # 강세 신호
        "bearish": [...],   # 약세 신호
        "neutral": [...],   # 중립 (도지 등)
        "lookback_days": int,
      }
    각 리스트는 날짜 내림차순 (최근부터).
    """
    all_sigs = (
        detect_candles(df, lookback=lookback)
        + detect_ma_crosses(df, lookback=lookback)
        + detect_breakouts(df, lookback=min(lookback, 5))
        + detect_divergence(df, lookback=min(lookback, 5))
        + detect_retests(df, lookback=min(lookback * 2, 20))
        + detect_chart_patterns(df, lookback=90)
    )
    bullish, bearish, neutral = [], [], []
    for s in all_sigs:
        if s["direction"] == "강세":
            bullish.append(s)
        elif s["direction"] == "약세":
            bearish.append(s)
        else:
            neutral.append(s)
    for lst in (bullish, bearish, neutral):
        lst.sort(key=lambda x: x["date"], reverse=True)
    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "lookback_days": lookback,
    }
