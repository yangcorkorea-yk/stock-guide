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

import json
from pathlib import Path

import pandas as pd
import streamlit as st
from analysis import (get_bars, analyze, explain, make_chart, resample_bars,
                      RSI_HELP, BB_HELP, SECTORS, THEMES, company_brief,
                      reference_levels)
from news_client import fetch_news
from llm_client import summarize_news_ko

st.set_page_config(page_title="종목 길잡이", page_icon="📈", layout="centered")
st.session_state.setdefault("sector_rows", None)
st.session_state.setdefault("theme_name", None)
st.session_state.setdefault("search_symbol", None)

HOT_THEMES_PATH = Path(__file__).resolve().parent / "data" / "hot_themes.json"


@st.cache_data(ttl=1800, show_spinner=False)
def load_hot_themes():
    """data/hot_themes.json 을 읽어옴. 파일 없거나 파싱 실패 시 None."""
    try:
        return json.loads(HOT_THEMES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def cached_bars(symbol):
    return get_bars(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_bars_long(symbol):
    return get_bars(symbol, days=1800)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_brief(symbol):
    return company_brief(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_news(symbol, days=5, limit=20):
    """Alpaca 뉴스 호출 결과 캐시 (1시간). 실패 시 빈 리스트."""
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return fetch_news(symbols=[symbol], start=start, end=end,
                      limit=limit, max_pages=1)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_news_summary(symbol, sector, headlines_tuple):
    """LLM 요약 캐시 (1시간). headlines를 튜플로 받아 캐시 키 안정화."""
    return summarize_news_ko(symbol, sector, list(headlines_tuple))


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

    # 일봉일 때만 참고 가격대(진입/매도/손절) 수평선 표시
    fig = make_chart(chart_df)
    levels = None
    if tf == "일봉":
        try:
            levels = reference_levels(df)
            fig.add_hline(y=levels['entry'][0]['price'], line=dict(color="#1c7ed6", dash="dot", width=1),
                          row=1, col=1, annotation_text="진입 참고", annotation_position="left")
            fig.add_hline(y=levels['exit'][0]['price'], line=dict(color="#e03131", dash="dot", width=1),
                          row=1, col=1, annotation_text="매도 참고", annotation_position="left")
            fig.add_hline(y=levels['stop'][0]['price'], line=dict(color="#868e96", dash="dash", width=1),
                          row=1, col=1, annotation_text="손절 참고", annotation_position="left")
        except Exception:
            levels = None
    st.plotly_chart(fig, use_container_width=True)

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
    if why:
        st.markdown("\n".join(why))

    # 📰 최근 뉴스 (Alpaca News + LLM 한국어 요약 + 원문 링크)
    st.subheader("📰 최근 뉴스")
    news_items = cached_news(symbol)
    if not news_items:
        # 폴백: yfinance 헤드라인 (요약/링크 없음)
        if brief["news"]:
            for t in brief["news"]:
                st.markdown(f"- {t}")
            st.caption("※ Alpaca 뉴스 응답이 없어 회사정보 기반으로 표시 중이에요.")
        else:
            st.caption("최근 뉴스를 불러오지 못했어요.")
    else:
        headlines = tuple(n.get("headline") or "" for n in news_items if n.get("headline"))
        summary = cached_news_summary(symbol, brief.get("sector"), headlines) if headlines else None
        if summary:
            st.markdown(summary)
            st.caption("⚠️ AI가 헤드라인만 보고 요약한 거예요. 정확한 내용은 원문을 확인해 주세요.")
        elif headlines:
            st.caption("(AI 요약 미사용 — 키가 없거나 호출 실패. 원문 링크만 표시해요.)")

        st.markdown("**🔗 원문 링크**")
        for n in news_items[:6]:
            title = (n.get("headline") or "").strip()
            url = n.get("url") or ""
            src = n.get("source") or ""
            if not title:
                continue
            if url:
                st.markdown(f"- [{title}]({url})  _·  {src}_")
            else:
                st.markdown(f"- {title}  _·  {src}_")

    st.subheader("📊 현재 기술적 상태")
    st.caption("아래 수치는 일봉 기준 현재 상태예요 (차트 기간과 무관).")
    st.write(f"- **RSI (과열도)**: {info['rsi']:.0f}  _(70↑ 과열 / 35↓ 과매도)_")
    st.write(f"- **볼린저밴드 위치 (변동폭)**: {info['bb']:.2f}  _(1.0↑ 상단돌파 / 0.15↓ 하단근처)_")
    if info.get('rvol') is not None:
        rv = info['rvol']
        tag = "평소보다 많음 🔥" if rv >= 1.5 else ("평소보다 적음 💤" if rv < 0.7 else "보통")
        st.write(f"- **거래량 (거래쏠림)**: 평균의 {rv:.1f}배 — {tag}")
        st.caption("※ 거래량은 무료 IEX 피드 기준이라 실제 전체 거래량보다 작게 표시돼요 (절대값보다 '평소 대비' 상대 비교용).")
    st.write(f"- **추세**: {info['trend']}")
    st.caption(f"기준일: {info['date']}")

    # 📍 참고 가격대 (규칙 기반 — 예측·추천 아님)
    if levels is None:
        # 사용자가 주봉/월봉 차트를 본 경우에도 참고값은 일봉 기준으로 계산
        try:
            levels = reference_levels(df)
        except Exception:
            levels = None
    if levels is not None:
        st.subheader("📍 참고 가격대  _(규칙 계산값 · 예측 아님)_")
        st.caption(
            "아래는 **사용자가 직접 판단할 때 참고하라고** 규칙으로 계산한 가격대예요. "
            "예측·매수/매도 권유 아닙니다."
        )
        with st.expander("⚠️ 한계 — 이런 기계적 규칙의 진실"):
            st.markdown(
                "- 이런 진입/매도/손절 규칙들은 **과거 백테스트에서 단순 보유를 못 이긴 경우가 많아요**.\n"
                "- '평소 다니던 길'을 가정한 규칙이라, 큰 뉴스/사건엔 쉽게 깨져요.\n"
                "- 그래도 '지금 어디쯤이지?'를 가늠하는 **눈금자** 정도로는 쓸모 있어요."
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**🔵 진입 참고**")
            for it in levels['entry']:
                pct = (it['price'] / levels['close'] - 1) * 100
                st.write(f"- ${it['price']:.2f}  _({pct:+.1f}%)_  · {it['label']}")
                st.caption(it['rule'])
        with c2:
            st.markdown("**🔴 매도 참고**")
            for it in levels['exit']:
                pct = (it['price'] / levels['close'] - 1) * 100
                st.write(f"- ${it['price']:.2f}  _({pct:+.1f}%)_  · {it['label']}")
                st.caption(it['rule'])
        with c3:
            st.markdown("**⚫ 손절 라인**")
            for it in levels['stop']:
                pct = (it['price'] / levels['close'] - 1) * 100
                st.write(f"- ${it['price']:.2f}  _({pct:+.1f}%)_  · {it['label']}")
                st.caption(it['rule'])
        st.caption(f"기준일 종가 ${levels['close']:.2f} · ATR(14) ${levels['atr14']:.2f}")

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


def render_theme_detail(tname):
    """선택한 테마의 설명·체인·단계별 종목 표 렌더링 (탭 3·4 공용)."""
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
        render_stock_table(rows, f"theme_{tname}_{pick_seg}",
                           context=f"{tname} · {pick_seg}")


st.title("📈 종목 길잡이")
st.caption("미국주식 초보자를 위한 '지금 이 종목, 어떤 상태?' 도구")

tab1, tab2, tab3, tab4 = st.tabs(
    ["🔍 종목 검색", "📂 섹터 탐색", "📂 테마 탐색", "🔥 뜨는 테마"]
)

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
    st.caption("👇 섹터를 톡 누르면 선택돼요 (키보드 안 뜨게 버튼식이에요)")
    sector = st.pills("섹터 선택", list(SECTORS.keys()), selection_mode="single",
                      default=list(SECTORS.keys())[0], label_visibility="collapsed",
                      key="sector_sel")
    if st.button("이 섹터 종목 보기", use_container_width=True, type="primary", key="sector_btn"):
        if not sector:
            st.warning("먼저 섹터를 선택해 주세요.")
        else:
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
    st.caption("👇 테마를 톡 누르면 선택돼요 (키보드 안 뜨게 버튼식이에요)")
    theme = st.pills("테마 선택", list(THEMES.keys()), selection_mode="single",
                     default=list(THEMES.keys())[0], label_visibility="collapsed",
                     key="theme_sel")
    if st.button("이 테마 살펴보기", use_container_width=True, type="primary", key="theme_btn"):
        if not theme:
            st.warning("먼저 테마를 선택해 주세요.")
        else:
            st.session_state.theme_name = theme

    if st.session_state.theme_name:
        render_theme_detail(st.session_state.theme_name)

# ── 탭 4: 뜨는 테마 ──────────────────────────────
with tab4:
    st.write("최근 **뉴스에 가장 많이 언급된 테마**를 순위로 보여줘요.")
    st.caption("※ 언급량은 '관심도'의 한 단서일 뿐, 오른다는 예측이 아닙니다. "
               "(키워드 매칭 기반 — 같은 단어를 다른 맥락으로 쓴 기사도 섞일 수 있어요)")

    hot = load_hot_themes()
    if not hot or not hot.get("themes"):
        st.info("아직 집계 전이에요. "
                "(GitHub Actions가 매일 자동으로 `data/hot_themes.json` 을 갱신해요.)")
    else:
        st.caption(
            f"기준: 최근 {hot.get('window_days', 3)}일 · "
            f"표본 {hot.get('sample_size', '?')}건 · "
            f"갱신 {hot.get('updated_at', '?')}"
        )

        rows = [
            {"순위": i, "테마": t["name"], "언급": t["count"],
             "한줄 설명": (t.get("desc") or "").split(".")[0][:60]}
            for i, t in enumerate(hot["themes"], 1) if t["count"] > 0
        ]
        if not rows:
            st.info("아직 매칭된 뉴스가 없어요. 내일 다시 확인해 주세요.")
        else:
            table = pd.DataFrame(rows)
            st.caption("👇 테마를 선택하면 아래에 상세가 펼쳐져요")
            event = st.dataframe(
                table, hide_index=True, use_container_width=True,
                on_select="rerun", selection_mode="single-row", key="tbl_hot",
            )
            sel = event.selection.rows
            if sel:
                picked = table.iloc[sel[0]]["테마"]
                st.divider()
                if picked in THEMES:
                    render_theme_detail(picked)
                else:
                    st.error("이 테마가 현재 카탈로그에 없어요 (데이터가 더 오래되었을 수 있어요).")

st.divider()
st.caption("⚠️ 이 앱은 투자조언이 아니며 정보·교육 목적입니다. "
           "모든 투자 판단과 책임은 본인에게 있습니다.")
