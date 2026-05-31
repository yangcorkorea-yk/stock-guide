"""
종목 길잡이 - 모바일 화면 (Streamlit)
-------------------------------------------------
  탭1 종목 검색 : 티커 1개 → 차트 + 현재 상태 + 쉬운 설명
  탭2 섹터 탐색 : 섹터 선택 → 종목 표 → 선택 시 상세
  탭3 테마 탐색 : 테마 선택 → 쉬운 설명 + 파생 섹터 흐름 + 대표 종목

⚠️ config.py, auto_trader.py, analysis.py 와 같은 폴더에 두세요.
설치:  pip install streamlit plotly alpaca-py pandas numpy
실행:  python -m streamlit run app.py
"""

import pandas as pd
import streamlit as st
from analysis import (get_bars, analyze, explain, make_chart, resample_bars,
                      RSI_HELP, BB_HELP, SECTORS, THEMES, company_brief)

st.set_page_config(page_title="종목 길잡이", page_icon="📈", layout="centered")
st.session_state.setdefault("sector_rows", None)
st.session_state.setdefault("theme_name", None)
st.session_state.setdefault("search_symbol", None)


@st.cache_data(ttl=600, show_spinner=False)
def cached_bars(symbol):
    return get_bars(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_bars_long(symbol):
    return get_bars(symbol, days=1800)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_brief(symbol):
    return company_brief(symbol)


def badge(status):
    if status == "과열":
        return "🔴 과열"
    if status.startswith("눌림"):
        return "🔵 눌림"
    return "⚪ 중립"


def analyze_tickers(tickers):
    rows = []
    for t in tickers:
        try:
            df = cached_bars(t)
            if df is None or len(df) < 30:
                continue
            info = analyze(df)
            rows.append(dict(sym=t, price=info['close'],
                             chg=info['change'], status=info['status']))
        except Exception:
            continue
    return rows


def show_detail(symbol, df, context=None):
    info = analyze(df)
    c1, c2 = st.columns(2)
    c1.metric("현재가", f"${info['close']:.2f}", f"{info['change']:+.2f}%")
    c2.metric("상태", info['status'])

    st.subheader("📈 차트")
    tf = st.pills("기간", ["일봉", "주봉", "월봉"], default="일봉",
                  selection_mode="single", label_visibility="collapsed",
                  key=f"tf_{symbol}") or "일봉"
    if tf == "일봉":
        chart_df = df
    else:
        long_df = cached_bars_long(symbol)
        chart_df = resample_bars(long_df, "W" if tf == "주봉" else "M")
    st.caption(f"{tf} · 위: 가격(캔들) + 볼린저밴드  /  아래: RSI · 빨강=상승, 파랑=하락")
    st.plotly_chart(make_chart(chart_df), use_container_width=True)

    brief = cached_brief(symbol)

    st.subheader("🏢 회사 한눈에")
    bits = []
    if brief["sector"]:
        s = brief["sector"] + (f" · {brief['industry']}" if brief["industry"] else "")
        bits.append(f"**업종** {s}")
    if brief["cap"]:
        bits.append(f"**시총** {brief['cap']}")
    if brief["pe"]:
        bits.append(f"**PER** {brief['pe']}")
    bits.append(f"**52주 고점 대비** {info['high_52w_pct']:+.0f}%")
    st.write("　·　".join(bits))
    st.caption("52주 고점 대비가 0%에 가까울수록 장기 강세 영역, 많이 마이너스면 고점에서 내려온 상태예요.")

    st.subheader("💡 왜 이 종목?")
    why = []
    if context:
        line = f"- 🏷️ **'{context}'** 흐름에 속해요"
        if brief["industry"]:
            line += f" — {brief['industry']} 업종이라서요"
        why.append(line)
    elif brief["industry"]:
        why.append(f"- 🏷️ **업종**: {brief['industry']}")
    if brief["news"]:
        why.append("- 📰 **최근 뉴스**")
        for t in brief["news"]:
            why.append(f"    - {t}")
    if why:
        st.markdown("\n".join(why))
    else:
        st.caption("연결 근거 정보를 불러오지 못했어요. (회사정보 일시 오류일 수 있어요)")

    st.subheader("📊 현재 기술적 상태")
    st.caption("아래 수치는 일봉 기준 현재 상태예요 (차트 기간과 무관).")
    st.write(f"- **RSI (과열도)**: {info['rsi']:.0f}  _(70↑ 과열 / 35↓ 과매도)_")
    st.write(f"- **볼린저밴드 위치 (변동폭)**: {info['bb']:.2f}  _(1.0↑ 상단돌파 / 0.15↓ 하단근처)_")
    if info.get('rvol') is not None:
        rv = info['rvol']
        tag = "평소보다 많음 🔥" if rv >= 1.5 else ("평소보다 적음 💤" if rv < 0.7 else "보통")
        st.write(f"- **거래량 (거래쏠림)**: 평균의 {rv:.1f}배 — {tag}")
    st.write(f"- **추세**: {info['trend']}")
    st.caption(f"기준일: {info['date']}")

    st.subheader("🗣️ 쉬운 설명")
    st.markdown(explain(symbol, info))
    with st.expander("❓ RSI(과열도)가 뭔가요?"):
        st.markdown(RSI_HELP)
    with st.expander("❓ 볼린저밴드(변동폭)가 뭔가요?"):
        st.markdown(BB_HELP)


def render_stock_table(rows, key, context=None):
    """종목 표 + 선택 시 상세 펼침 (섹터/테마 공용)"""
    if not rows:
        st.error("데이터를 불러오지 못했어요.")
        return
    st.caption("👇 종목을 선택하면(왼쪽 선택칸 클릭) 아래에 상세가 펼쳐져요")
    table = pd.DataFrame([{
        "종목": r['sym'],
        "시세": f"${r['price']:.2f}  {r['chg']:+.1f}%",
        "상태": badge(r['status']),
    } for r in rows])
    event = st.dataframe(table, hide_index=True, use_container_width=True,
                         on_select="rerun", selection_mode="single-row", key=f"tbl_{key}")
    sel = event.selection.rows
    if sel:
        picked = table.iloc[sel[0]]["종목"]
        st.divider()
        st.markdown(f"### 🔎 {picked} 자세히 보기")
        try:
            ddf = cached_bars(picked)
            if ddf is None or len(ddf) < 30:
                st.error("데이터를 받지 못했어요.")
            else:
                show_detail(picked, ddf, context=context)
        except Exception as e:
            st.error(f"오류가 났어요: {e}")


st.title("📈 종목 길잡이")
st.caption("미국주식 초보자를 위한 '지금 이 종목, 어떤 상태?' 도구")

tab1, tab2, tab3 = st.tabs(["🔍 종목 검색", "📂 섹터 탐색", "🔥 테마 탐색"])

# ── 탭 1: 종목 검색 ──────────────────────────────
with tab1:
    symbol = st.text_input("종목 티커 (예: AAPL, TSLA, NVDA)", "AAPL").strip().upper()
    if st.button("분석하기", use_container_width=True, type="primary", key="search_btn"):
        st.session_state.search_symbol = symbol if symbol else None
        if not symbol:
            st.warning("티커를 입력해 주세요.")

    if st.session_state.search_symbol:
        sym = st.session_state.search_symbol
        with st.spinner(f"{sym} 분석 중..."):
            try:
                df = cached_bars(sym)
                if df is None or len(df) < 30:
                    st.error("데이터를 받지 못했어요. 티커가 맞는지 확인해 주세요.")
                else:
                    show_detail(sym, df)
            except Exception as e:
                st.error(f"오류가 났어요: {e}")

# ── 탭 2: 섹터 탐색 ──────────────────────────────
with tab2:
    st.write("관심 있는 **섹터**를 고르면, 그 안 대표 종목들의 현재 상태가 한눈에 보여요.")
    sector = st.selectbox("섹터 선택", list(SECTORS.keys()), key="sector_sel")
    if st.button("이 섹터 종목 보기", use_container_width=True, type="primary", key="sector_btn"):
        with st.spinner(f"{sector} 종목들 분석 중..."):
            st.session_state.sector_rows = analyze_tickers(SECTORS[sector])
            st.session_state.sector_name = sector
    if st.session_state.sector_rows is not None:
        name = st.session_state.sector_name
        st.write(f"**{name}** 대표 종목 현재 상태")
        render_stock_table(st.session_state.sector_rows, f"sector_{name}", context=name)

# ── 탭 3: 테마 탐색 ──────────────────────────────
with tab3:
    st.write("지금 시장이 주목하는 **테마**들이에요. 고르면 흐름(단계)과 그 단계의 종목을 볼 수 있어요.")
    st.caption("※ '지금 주목받는 흐름'을 정리한 것이지, 오른다는 예측이 아닙니다.")
    theme = st.selectbox("테마 선택", list(THEMES.keys()), key="theme_sel")
    if st.button("이 테마 살펴보기", use_container_width=True, type="primary", key="theme_btn"):
        st.session_state.theme_name = theme

    if st.session_state.theme_name:
        tname = st.session_state.theme_name
        tinfo = THEMES[tname]
        seg_names = [s["name"] for s in tinfo["chain"]]

        st.markdown(f"#### {tname}")
        st.write(tinfo["desc"])
        st.info("💡 파생 섹터 흐름:  " + "  →  ".join(seg_names))

        st.caption("👇 흐름의 단계를 누르면 그 단계의 종목이 나와요")
        pick_seg = st.pills("단계 선택", seg_names, selection_mode="single",
                            default=seg_names[0], label_visibility="collapsed",
                            key=f"seg_{tname}")
        if pick_seg:
            seg = next(s for s in tinfo["chain"] if s["name"] == pick_seg)
            st.write(f"**{pick_seg}** 단계 종목")
            rows = analyze_tickers(seg["stocks"])
            render_stock_table(rows, f"theme_{tname}_{pick_seg}", context=f"{tname} · {pick_seg}")

st.divider()
st.caption("⚠️ 이 앱은 투자조언이 아니며 정보·교육 목적입니다. "
           "모든 투자 판단과 책임은 본인에게 있습니다.")
