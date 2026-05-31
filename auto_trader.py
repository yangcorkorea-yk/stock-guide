"""
멀티 지표 종합 매매 전략 + 백테스트 엔진
-------------------------------------------------
설계 원칙:
  - 진입(매수): 설정한 여러 기법이 '모두 Y(True)'일 때만 매수
  - 청산(매도): 설정한 청산 조건 중 '하나라도' 깨지면 매도
  - 증권사와 무관한 순수 전략/검증 레이어 (실거래 연동은 별도)

데이터 형식:
  df 컬럼 = ['open', 'high', 'low', 'close', 'volume'], index = 날짜
"""

import pandas as pd
import numpy as np


# ──────────────────────────────────────────────
# 1) 보조지표 계산
# ──────────────────────────────────────────────
def add_indicators(df, bb_period=20, bb_std=2.0, rsi_period=14,
                   ma_short=5, ma_long=20, vol_ma=20):
    df = df.copy()

    # 볼린저밴드
    mid = df['close'].rolling(bb_period).mean()
    std = df['close'].rolling(bb_period).std()
    df['bb_mid'] = mid
    df['bb_upper'] = mid + bb_std * std
    df['bb_lower'] = mid - bb_std * std
    # 밴드 내 위치(0=하단, 1=상단)
    df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # 이동평균
    df['ma_short'] = df['close'].rolling(ma_short).mean()
    df['ma_long'] = df['close'].rolling(ma_long).mean()

    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    # 거래량 평균
    df['vol_ma'] = df['volume'].rolling(vol_ma).mean()

    return df


# ──────────────────────────────────────────────
# 2) 진입 조건 (모두 True여야 매수)
#    config로 어떤 기법을 쓸지 켜고 끌 수 있음
# ──────────────────────────────────────────────
def entry_conditions(df, cfg):
    conds = {}

    # 저점 매수: 종가가 볼린저 하단 근처 (밴드 위치 <= 임계값)
    if cfg.get('use_bollinger', True):
        conds['볼린저_저점'] = df['bb_pct'] <= cfg.get('bb_entry_pct', 0.15)

    # RSI 과매도
    if cfg.get('use_rsi', True):
        conds['RSI_과매도'] = df['rsi'] <= cfg.get('rsi_oversold', 35)

    # 거래량 증가 (평소보다 활발)
    if cfg.get('use_volume', True):
        conds['거래량_증가'] = df['volume'] >= df['vol_ma'] * cfg.get('vol_mult', 1.2)

    # 반등 시작: 종가가 단기 이평 위로 올라옴 (추세 전환 신호)
    if cfg.get('use_ma_turn', True):
        conds['단기반등'] = df['close'] > df['ma_short']

    # MACD가 시그널 위 (상승 모멘텀)
    if cfg.get('use_macd', False):
        conds['MACD_상승'] = df['macd'] > df['macd_signal']

    if not conds:
        raise ValueError("진입 조건이 하나도 켜져 있지 않습니다.")

    # 모든 조건 AND → '모두 Y'
    combined = pd.concat(conds.values(), axis=1).all(axis=1)
    return combined, conds


# ──────────────────────────────────────────────
# 3) 청산 조건 (하나라도 깨지면 매도)
# ──────────────────────────────────────────────
def should_exit(row, entry_price, cfg):
    # 손절
    if row['close'] <= entry_price * (1 - cfg.get('stop_loss', 0.05)):
        return '손절'
    # 익절
    if row['close'] >= entry_price * (1 + cfg.get('take_profit', 0.10)):
        return '익절'
    # 볼린저 상단 도달
    if cfg.get('exit_bb_upper', True) and row['close'] >= row['bb_upper']:
        return '밴드상단'
    # RSI 과매수
    if cfg.get('exit_rsi', True) and row['rsi'] >= cfg.get('rsi_overbought', 70):
        return 'RSI과열'
    # 추세 깨짐: 종가가 장기 이평 아래로
    if cfg.get('exit_ma_break', True) and row['close'] < row['ma_long']:
        return '추세이탈'
    return None


# ──────────────────────────────────────────────
# 4) 백테스트 엔진
# ──────────────────────────────────────────────
def backtest(df, cfg, capital=10_000_000, fee=0.00015, tax=0.0018, slippage=0.001):
    """
    fee: 매매 수수료(편도), tax: 매도세, slippage: 체결 미끄러짐 가정
    """
    df = add_indicators(df, **cfg.get('indicators', {}))
    entry_signal, _ = entry_conditions(df, cfg)

    cash = capital
    shares = 0
    entry_price = 0.0
    trades = []
    equity_curve = []

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]

        if row.isna().any():  # 지표 워밍업 구간
            equity_curve.append(cash)
            continue

        # 보유 중 → 청산 판단
        if shares > 0:
            reason = should_exit(row, entry_price, cfg)
            if reason:
                sell_price = row['close'] * (1 - slippage)
                proceeds = shares * sell_price * (1 - fee - tax)
                pnl = proceeds - (shares * entry_price)
                cash += proceeds
                trades.append({
                    '진입일': entry_date, '청산일': date,
                    '진입가': round(entry_price), '청산가': round(sell_price),
                    '사유': reason, '손익': round(pnl),
                    '수익률%': round((sell_price / entry_price - 1) * 100, 2)
                })
                shares = 0
                entry_price = 0.0

        # 미보유 → 진입 판단 (모든 조건 Y)
        elif entry_signal.iloc[i]:
            buy_price = row['close'] * (1 + slippage)
            qty = int(cash // (buy_price * (1 + fee)))
            if qty > 0:
                cost = qty * buy_price * (1 + fee)
                cash -= cost
                shares = qty
                entry_price = buy_price
                entry_date = date

        # 평가자산 기록
        equity_curve.append(cash + shares * row['close'])

    # 결과 정리
    trades_df = pd.DataFrame(trades)
    equity = pd.Series(equity_curve, index=df.index)
    final = equity.iloc[-1]

    stats = {
        '초기자본': capital,
        '최종자산': round(final),
        '총수익률%': round((final / capital - 1) * 100, 2),
        '매매횟수': len(trades_df),
        '승률%': round((trades_df['손익'] > 0).mean() * 100, 1) if len(trades_df) else 0,
        'MDD%': round((equity / equity.cummax() - 1).min() * 100, 2),
    }
    return stats, trades_df, equity


# ──────────────────────────────────────────────
# 실행 예시 (합성 데이터로 동작 확인)
# ──────────────────────────────────────────────
if __name__ == '__main__':
    # 진입/청산 기법 종합 설정
    config = {
        'use_bollinger': True, 'bb_entry_pct': 0.15,
        'use_rsi': True, 'rsi_oversold': 35,
        'use_volume': True, 'vol_mult': 1.2,
        'use_ma_turn': True,
        'use_macd': False,
        'stop_loss': 0.05, 'take_profit': 0.10,
        'exit_bb_upper': True, 'exit_rsi': True,
        'rsi_overbought': 70, 'exit_ma_break': True,
        'indicators': {'bb_period': 20, 'rsi_period': 14},
    }

    # 합성 가격 데이터 생성 (실제로는 yfinance/pykrx로 교체)
    np.random.seed(42)
    n = 400
    ret = np.random.normal(0.0003, 0.02, n)
    price = 50000 * np.exp(np.cumsum(ret))
    dates = pd.date_range('2023-01-01', periods=n, freq='B')
    df = pd.DataFrame({
        'open': price * (1 + np.random.normal(0, 0.003, n)),
        'high': price * (1 + abs(np.random.normal(0, 0.01, n))),
        'low': price * (1 - abs(np.random.normal(0, 0.01, n))),
        'close': price,
        'volume': np.random.randint(100000, 1000000, n),
    }, index=dates)

    stats, trades, equity = backtest(df, config)
    print("=== 백테스트 결과 ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print(f"\n=== 매매 내역 (최근 5건) ===")
    print(trades.tail().to_string(index=False) if len(trades) else "매매 없음")
