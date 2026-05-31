# 종목 길잡이 (Stock Guide) — 프로젝트 컨텍스트

미국주식 **초보자용 리서치/교육 도구**. "지금 이 종목, 어떤 상태인가?"를 쉬운 말로 보여주는 Streamlit 웹앱. 모바일에서 쓰는 게 1차 목적이고, 잘 되면 수익화 검토.

> ⚠️ 자동매매 봇이 아니고, 가격 예측 도구도 아님. (초기엔 자동매매로 시작했으나, 기술적 전략이 단순보유를 못 이긴다는 백테스트 결과 후 리서치 도구로 피벗함.)

## 핵심 원칙 (절대 깨지 말 것)
1. **정보를 주되 예측하지 않는다.** 최종 판단은 사용자 몫.
2. **불확실성을 숨기지 않는다.** 데이터 한계(아래)를 화면에 솔직히 표시.
3. **초보자 눈높이.** 전문용어엔 별칭을 붙임: RSI=과열도, 볼린저밴드=변동폭, 거래량=거래쏠림.
4. **상태 라벨은 서술형으로 유지** — `과열 / 중립 / 눌림`. ❌ "매수후보/매도" 같은 행동 유도 라벨 금지.
5. **투자조언이 아님**을 항상 명시. (개인용 기능이라도 "규칙으로 계산한 참고값"으로 솔직하게.)
6. UI는 **모바일 우선**. 종목 표는 Streamlit 기본 `st.dataframe`(반응형, 체크박스 선택)을 씀 — aggrid는 기기별 너비가 깨져서 폐기함.

## 기술 스택 / 실행
- Python + Streamlit + Plotly + pandas/numpy
- 데이터: **Alpaca**(일봉 시세) + **yfinance**(회사정보·뉴스)
- 실행: `python -m streamlit run app.py`  (`streamlit run`은 일부 환경서 PATH 문제 → `python -m` 권장)
- 배포: Streamlit Community Cloud (GitHub 연동, push 시 자동 재배포). 라이브: `stock-guide-skorea.streamlit.app`

## 데이터의 한계 (중요 — 화면에 솔직히 반영해야 함)
- 시세는 **일봉**(분/초 실시간 아님), 캐시 약 10분.
- Alpaca **무료 플랜 = IEX 피드** → 전체 시장의 일부만. 그래서 **거래량이 실제보다 작게** 나옴(절대값 말고 '평소 대비'로만 의미). 전체 시장(SIP)은 유료.
- 뉴스/회사정보는 yfinance(야후), 캐시 약 1시간. 실시간 스트리밍 아님.

## 파일 구조
- `app.py` — Streamlit UI. 탭 3개: `🔍 종목 검색 / 📂 섹터 탐색 / 🔥 테마 탐색`.
  - 핵심 함수: `cached_bars`(10분 캐시), `cached_bars_long`(1800일, 주/월봉용), `cached_brief`(1시간),
    `analyze_tickers(tickers)`, `show_detail(symbol, df, context=None)`, `render_stock_table(rows, key, context=None)`, `badge(status)`.
  - 종목 상세(show_detail): 현재가/상태 → 차트(일/주/월봉 `st.pills`) → 🏢 회사 한눈에 → 💡 왜 이 종목?(근거: 업종+뉴스) → 📊 기술적 상태 → 🗣️ 쉬운 설명.
  - 세션 상태: `sector_rows`, `theme_name`, `search_symbol`.
- `analysis.py` — 리서치 로직.
  - `get_bars(symbol, days=400)` → Alpaca 일봉 DataFrame(DatetimeIndex, OHLCV).
  - `analyze(df)` → dict: `close, change, rsi, bb, ma_long, status, trend, rvol, high_52w_pct, date`.
  - `explain(symbol, info)` → 규칙기반 한국어 설명 텍스트.
  - `make_chart(df, lookback=60)` → Plotly 3단(가격+볼린저 / 거래량 / RSI). 일봉은 주말·공휴일 rangebreaks로 빈칸 제거.
  - `resample_bars(df, tf)` → 'W'주봉 / 'M'월봉 / 그외 일봉.
  - `company_brief(symbol)` → yfinance: `{name, sector, industry, cap, pe, news[]}` (실패해도 빈값으로 graceful).
  - `SECTORS` (현재 9개) — `{섹터명: [티커...]}`.
  - `THEMES` (현재 6개) — `{테마명: {desc, chain: [{name, stocks:[...]}, ...]}}`. chain = 단계별 파생섹터.
- `auto_trader.py` — 지표 엔진. `add_indicators(df)`가 bollinger(bb_upper/mid/lower/pct), rsi, ma_short/long, macd, vol_ma 생성. (analyze/make_chart가 사용)
- `secrets_loader.py` — Alpaca 키 로더: ① st.secrets ② 환경변수 ③ 로컬 config.py 순. (이 파일엔 키 없음, 커밋 안전)
- `config.py` — **로컬 전용 키 파일. .gitignore로 제외. 절대 커밋 금지.**
- `requirements.txt`, `.gitignore`

## 키 / 시크릿 규칙
- 로컬: `config.py`에 `API_KEY`, `SECRET_KEY`.
- 배포: Streamlit Cloud Secrets에 `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (TOML).
- 새 API 키(뉴스/LLM)도 동일하게 secrets/환경변수로. **코드/깃에 키 하드코딩 금지.**
