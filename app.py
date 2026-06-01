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
import re
from pathlib import Path

import pandas as pd
import streamlit as st

# 티커 형식: 영문 대문자 1~5자 (+ ".A" 같은 클래스 접미사 선택)
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


def _looks_like_ticker(s: str) -> bool:
    return bool(s and _TICKER_RE.match(s.upper()))
from analysis import (get_bars, analyze, explain, make_chart, resample_bars,
                      RSI_HELP, BB_HELP, SECTORS, THEMES, company_brief,
                      reference_levels, FUNDAMENTALS_HELP, make_comparison_chart,
                      find_peer_group)
from news_client import fetch_news
from llm_client import summarize_news_ko
from ticker_names import search_tickers, display_name, TICKER_NAMES
from macro_calendar import upcoming_events, get_meta as get_macro_meta

st.set_page_config(page_title="종목 길잡이", page_icon="📈", layout="centered")
st.session_state.setdefault("sector_rows", None)
st.session_state.setdefault("theme_name", None)
st.session_state.setdefault("search_symbol", None)

# ── URL 공유: ?symbol=NVDA 진입 + 종목 변경 시 URL 동기화 ──────
# 첫 로드 때만 URL → 세션 (이후 사용자 액션이 우선)
_url_symbol = st.query_params.get("symbol")
if _url_symbol and st.session_state.get("search_symbol") is None:
    _sym = _url_symbol.upper().strip()
    if _sym:
        st.session_state.search_symbol = _sym
        st.session_state["search_query_text"] = _sym

# 세션 → URL 동기화 (rerun 무한 루프 방지: 값이 다를 때만 갱신)
_cur = st.session_state.get("search_symbol")
if _cur:
    if st.query_params.get("symbol") != _cur:
        st.query_params["symbol"] = _cur
elif "symbol" in st.query_params:
    del st.query_params["symbol"]

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


def _range_bar_52w(df):
    """52주 레인지에서 현재가 위치를 막대로 시각화."""
    closes = df['close'].tail(252).dropna()
    if len(closes) < 20:
        return
    lo, hi, cur = float(closes.min()), float(closes.max()), float(closes.iloc[-1])
    if hi <= lo:
        return
    pos = max(0.0, min(1.0, (cur - lo) / (hi - lo)))
    st.progress(pos, text=f"52주 위치 {pos*100:.0f}%　·　최저 ${lo:,.0f} ~ 최고 ${hi:,.0f}")


def show_detail(symbol, df, context=None):
    info = analyze(df)
    brief = cached_brief(symbol)

    # ── 핵심 요약 ─────────────────────────────
    c1, c2 = st.columns(2)
    c1.metric("현재가", f"${info['close']:.2f}", f"{info['change']:+.2f}%")
    c2.metric("상태", info['status'])
    _range_bar_52w(df)

    # ── 차트 ─────────────────────────────────
    st.subheader("📈 차트")
    tf = st.pills("기간", ["일봉", "주봉", "월봉"], default="일봉",
                  selection_mode="single", label_visibility="collapsed",
                  key=f"tf_{symbol}") or "일봉"
    if tf == "일봉":
        chart_df = df
    else:
        long_df = cached_bars_long(symbol)
        chart_df = resample_bars(long_df, "W" if tf == "주봉" else "M")

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
    st.caption(f"{tf} 기준 · 캔들 빨강=상승, 파랑=하락 · 아래 칸은 RSI(과열도)")

    # ── 회사 ─────────────────────────────────
    st.subheader("🏢 이 회사는")
    parts = []
    if brief["sector"]:
        s = brief["sector"] + (f" · {brief['industry']}" if brief["industry"] else "")
        parts.append(f"**업종** {s}")
    if brief["cap"]:
        parts.append(f"**시총** {brief['cap']}")
    if brief.get("beta"):
        parts.append(f"**베타** {brief['beta']}")
    if parts:
        st.markdown("　·　".join(parts))
    if context:
        st.caption(f"🏷️ '{context}' 흐름에 속한 종목이에요.")

    # 같은 그룹 안에서의 위치 + 비교
    if context:
        group_name = context
        group_peers = _resolve_context_peers(context)
    else:
        group_name, group_peers = find_peer_group(
            symbol, brief.get("industry"), brief.get("sector"))
    if group_name and group_peers:
        render_peer_summary(symbol, group_name, group_peers)
        if len(group_peers) >= 3:
            with st.expander(f"📊 '{group_name}' 그룹과 수익률 비교하기"):
                render_comparison(group_peers, key=f"detail_{symbol}")

    # 다음 실적 발표
    edate = brief.get("earnings_date")
    if edate:
        days = brief.get("earnings_days")
        eps_part = f" · 추정 EPS {brief['earnings_eps_est']}" if brief.get("earnings_eps_est") else ""
        if days is None:
            st.info(f"📅 다음 실적 발표 **{edate}**{eps_part}")
        elif days < 0:
            st.caption(f"📅 직전 실적 발표 {edate} ({-days}일 전)")
        elif days == 0:
            st.warning(f"📅 **오늘 실적 발표**{eps_part} — 변동성이 클 수 있어요.")
        elif days <= 7:
            st.warning(f"📅 **실적 발표 D-{days}** ({edate}){eps_part} — 발표 전후 변동성에 유의하세요.")
        else:
            st.info(f"📅 다음 실적 발표 **{edate}** (D-{days}){eps_part}")

    # 재무 지표 (접이식)
    fund_fields = ["pe", "psr", "div_yield", "op_margin", "rev_growth", "roe"]
    if any(brief.get(k) for k in fund_fields):
        with st.expander("💎 재무 지표 자세히 (PER·PSR·배당·성장률)"):
            st.caption("회사의 '몸값'과 '돈 버는 힘'이에요. 같은 업종끼리 비교해야 의미 있어요.")
            cols = st.columns(3)
            cols[0].metric("PER", brief.get("pe") or "—",
                           help="주가 ÷ 1주당 순이익. 적자면 표시 안 돼요.")
            cols[1].metric("PSR", brief.get("psr") or "—",
                           help="주가 ÷ 1주당 매출. 적자·성장주에 유용해요.")
            cols[2].metric("배당수익률", brief.get("div_yield") or "—",
                           help="연 배당금 ÷ 주가.")
            cols2 = st.columns(3)
            cols2[0].metric("영업이익률", brief.get("op_margin") or "—",
                            help="매출 100원 중 본업으로 남긴 이익.")
            cols2[1].metric("매출성장", brief.get("rev_growth") or "—",
                            help="작년 같은 분기 대비 매출 증감.")
            cols2[2].metric("ROE", brief.get("roe") or "—",
                            help="자기자본 대비 이익률. 15%↑면 보통 우량.")
            st.markdown(FUNDAMENTALS_HELP)

    # ── 뉴스 ─────────────────────────────────
    st.subheader("📰 최근 뉴스")
    news_items = cached_news(symbol)
    headlines = tuple(
        (n.get("headline") or "").strip()
        for n in news_items if n.get("headline"))
    fallback_used = False
    if not headlines and brief.get("news"):
        headlines = tuple(brief["news"])
        fallback_used = True

    if headlines:
        summary = cached_news_summary(symbol, brief.get("sector"), headlines)
        if summary:
            st.markdown(summary)
            st.caption("AI가 헤드라인을 요약한 거예요. 자세한 내용은 원문을 확인해 주세요.")
        else:
            st.caption("AI 요약은 잠시 쉬어가요 (키 미설정 또는 호출 실패). 헤드라인만 보여드려요.")
    elif not news_items:
        st.caption("최근 뉴스를 불러오지 못했어요.")

    if news_items:
        st.markdown("**🔗 원문 링크**")
        for n in news_items[:6]:
            title = (n.get("headline") or "").strip()
            url = n.get("url") or ""
            src = n.get("source") or ""
            if not title:
                continue
            st.markdown(f"- [{title}]({url})　_{src}_" if url else f"- {title}　_{src}_")
    elif fallback_used:
        for t in headlines:
            st.markdown(f"- {t}")

    # ── 기술적 상태 ───────────────────────────
    st.subheader("📊 기술적 상태")
    st.caption("일봉 기준 현재 수치예요 (차트에서 고른 기간과는 별개).")
    st.markdown(f"- **RSI (과열도)** {info['rsi']:.0f}　_(70↑ 과열 / 35↓ 과매도)_")
    st.markdown(f"- **볼린저밴드 위치 (변동폭)** {info['bb']:.2f}　_(1.0↑ 상단돌파 / 0.15↓ 하단근처)_")
    if info.get('rvol') is not None:
        rv = info['rvol']
        tag = "평소보다 많아요 🔥" if rv >= 1.5 else ("평소보다 적어요 💤" if rv < 0.7 else "보통이에요")
        st.markdown(f"- **거래량 (거래쏠림)** 평균의 {rv:.1f}배 — {tag}")
    st.markdown(f"- **추세** {info['trend']}")
    st.caption(f"기준일 {info['date']}　·　거래량은 무료 IEX 피드라 실제보다 작게 나와요 (절대값 말고 '평소 대비'로만 보세요).")

    # ── 참고 가격대 ───────────────────────────
    if levels is None:
        try:
            levels = reference_levels(df)
        except Exception:
            levels = None
    if levels is not None:
        st.subheader("📍 참고 가격대")
        st.caption("규칙으로 계산한 참고값이에요. 예측·매수·매도 권유가 아닙니다.")
        c1, c2, c3 = st.columns(3)
        for col, key, head in ((c1, 'entry', '🔵 진입 참고'),
                               (c2, 'exit', '🔴 매도 참고'),
                               (c3, 'stop', '⚫ 손절 라인')):
            with col:
                st.markdown(f"**{head}**")
                for it in levels[key]:
                    pct = (it['price'] / levels['close'] - 1) * 100
                    st.markdown(f"${it['price']:.2f}　_{pct:+.1f}%_")
                    st.caption(f"{it['label']} — {it['rule']}")
        st.caption(f"기준 종가 ${levels['close']:.2f}　·　ATR(14) ${levels['atr14']:.2f}")
        with st.expander("⚠️ 이 값의 한계 (꼭 읽어보세요)"):
            st.markdown(
                "- 이런 진입·매도·손절 규칙은 **과거 검증에서 단순 보유를 못 이긴 경우가 많아요**.\n"
                "- '평소 다니던 길'을 가정한 거라 큰 뉴스·사건엔 쉽게 빗나가요.\n"
                "- '지금 가격이 어디쯤인지' 가늠하는 **눈금자** 정도로만 참고하세요."
            )

    # ── 한 줄 정리 ────────────────────────────
    st.subheader("🗣️ 한 줄 정리")
    st.markdown(explain(symbol, info))
    with st.expander("❓ RSI(과열도)·볼린저밴드(변동폭)가 뭔가요?"):
        st.markdown(RSI_HELP)
        st.divider()
        st.markdown(BB_HELP)



def render_stock_table(rows, key, context=None):
    """종목 표 + 선택 시 상세 펼침 (섹터/테마 공용)"""
    if not rows:
        st.error("데이터를 불러오지 못했어요.")
        return
    st.caption("👇 종목을 선택하면(왼쪽 선택칸 클릭) 아래에 상세가 펼쳐져요")
    table = pd.DataFrame([{
        "종목": display_name(r['sym']),
        "시세": f"${r['price']:.2f}  {r['chg']:+.1f}%",
        "상태": badge(r['status']),
    } for r in rows])
    event = st.dataframe(table, hide_index=True, use_container_width=True,
                         on_select="rerun", selection_mode="single-row", key=f"tbl_{key}")
    sel = event.selection.rows
    if sel:
        # rows 원본에서 ticker 추출 (table의 종목 컬럼은 한국어로 바뀌었으니)
        picked_sym = rows[sel[0]]['sym']
        st.divider()
        st.markdown(f"### 🔎 {display_name(picked_sym)} 자세히 보기")
        try:
            ddf = cached_bars(picked_sym)
            if ddf is None or len(ddf) < 30:
                st.error("데이터를 받지 못했어요.")
            else:
                show_detail(picked_sym, ddf, context=context)
        except Exception as e:
            st.error(f"오류가 났어요: {e}")


def render_comparison(symbols, key, default_period="6개월"):
    """주어진 심볼들의 수익률 비교 차트 + 기간 pills + 순위 요약."""
    periods = {"1개월": 21, "3개월": 63, "6개월": 126, "1년": 252}
    period = st.pills("기간", list(periods.keys()), default=default_period,
                      selection_mode="single", label_visibility="collapsed",
                      key=f"cmp_p_{key}") or default_period
    days = periods[period]

    with st.spinner(f"{len(symbols)}개 종목 시세 모으는 중..."):
        dfs = {s: cached_bars(s) for s in symbols}
    if not any(v is not None and not v.empty for v in dfs.values()):
        st.warning("시세 데이터를 받지 못했어요.")
        return

    fig, ranking = make_comparison_chart(dfs, lookback_days=days)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("※ 모든 종목을 시작점=100으로 맞춰 겹친 거예요. "
               "선이 위로 갈수록 그 기간 더 올랐다는 뜻이에요.")

    if ranking:
        top = ranking[:3]
        bot = ranking[-3:][::-1]
        st.markdown(
            f"**🚀 상위** {' · '.join(f'{s} ({v:.0f})' for s, v in top)}  　"
            f"**🐢 하위** {' · '.join(f'{s} ({v:.0f})' for s, v in bot)}"
        )


def _resolve_context_peers(context):
    """context 문자열을 peer 리스트로 풀어낸다.
    · 섹터명 → SECTORS[name]
    · '테마명 · 단계명' → 그 단계의 stocks (없으면 테마 전체)
    """
    if not context:
        return None
    if context in SECTORS:
        return list(SECTORS[context])
    if " · " in context:
        tname, _, seg_name = context.partition(" · ")
        if tname in THEMES:
            for seg in THEMES[tname]["chain"]:
                if seg["name"] == seg_name:
                    return list(seg["stocks"])
            return sorted({s for seg in THEMES[tname]["chain"] for s in seg["stocks"]})
    return None


def render_peer_summary(symbol, group_name, peers):
    """현재 종목이 동료 그룹에서 3개월 수익률 기준 어디쯤인지 한 줄 요약."""
    if not peers or symbol not in peers or len(peers) < 3:
        return

    days = 63  # 약 3개월
    rets = {}
    for s in peers:
        df = cached_bars(s)
        if df is None or len(df) < 5:
            continue
        c = df['close'].tail(days + 1).dropna()
        if len(c) < 2:
            continue
        rets[s] = (c.iloc[-1] / c.iloc[0] - 1) * 100
    if symbol not in rets or len(rets) < 3:
        return

    ranked = sorted(rets.items(), key=lambda x: -x[1])
    rank = next(i for i, (s, _) in enumerate(ranked, 1) if s == symbol)
    avg = sum(rets.values()) / len(rets)
    my = rets[symbol]
    rel = my - avg

    arrow = "🟢 평균보다 강함" if rel > 1 else ("🔴 평균보다 약함" if rel < -1 else "⚪ 평균 수준")
    st.markdown(
        f"📍 **'{group_name}'** 내 **{rank}/{len(rets)}위**  ·  "
        f"3개월 **{my:+.1f}%** (그룹 평균 {avg:+.1f}%, {arrow})"
    )


def render_theme_detail(tname):
    """선택한 테마의 설명·체인·단계별 종목 표 렌더링 (탭 3·4 공용)."""
    tinfo = THEMES[tname]
    seg_names = [s["name"] for s in tinfo["chain"]]

    st.markdown(f"#### {tname}")
    st.write(tinfo["desc"])
    st.info("💡 파생 섹터 흐름:  " + "  →  ".join(seg_names))

    # 📊 테마 전체 종목 수익률 비교
    all_stocks = sorted({s for seg in tinfo["chain"] for s in seg["stocks"]})
    with st.expander(f"📊 테마 종목 수익률 비교 ({len(all_stocks)}개 겹쳐 보기)"):
        render_comparison(all_stocks, key=f"theme_{tname}")

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


# ── 거시 이벤트 캘린더 (모든 탭 위 상단에 노출) ─────────
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_macro(days):
    return upcoming_events(days=days)


_events = _cached_macro(30)
if _events:
    nearest = _events[0]
    d_until = nearest.get("days_until")
    if d_until is not None and d_until == 0:
        d_str = "오늘"
    elif d_until is not None and d_until <= 7:
        d_str = f"D-{d_until}"
    else:
        d_str = f"D-{d_until}" if d_until is not None else ""
    label = f"📅 다가오는 시장 이벤트 — {nearest['tag']} {nearest['name']} ({d_str})"
    with st.expander(label):
        for e in _events:
            d = e.get("days_until")
            if d is None:
                d_label = "?"
            elif d == 0:
                d_label = "**오늘**"
            elif d < 0:
                d_label = f"{-d}일 전"
            else:
                d_label = f"D-{d}"
            st.markdown(f"- **{e['date']}** ({d_label})  ·  {e['tag']}  **{e['name']}**")
            if e.get("desc"):
                st.caption(f"　　{e['desc']}")
        meta = get_macro_meta()
        last = meta.get("last_refresh")
        fails = meta.get("refresh_failures") or []
        if last:
            tag = f"자동 갱신: {last[:10]}"
            if fails:
                tag += f"  ·  ⚠️ 일부 소스 추출 실패: {', '.join(fails)}"
            st.caption(tag + "  ·  출처: "
                       "[Fed](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · "
                       "[BLS](https://www.bls.gov/schedule/news_release/) · "
                       "[BEA](https://www.bea.gov/news/schedule)")
        else:
            st.caption("⚠️ 일정은 패턴 기반 추정치예요. 실제 발표일은 "
                       "[Fed](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · "
                       "[BLS](https://www.bls.gov/schedule/news_release/) · "
                       "[BEA](https://www.bea.gov/news/schedule) 공식 캘린더에서 확인하세요.")


tab1, tab2, tab3, tab4 = st.tabs(
    ["🔍 종목 검색", "📂 섹터 탐색", "📂 테마 탐색", "🔥 뜨는 테마"]
)

# ── 탭 1: 종목 검색 ──────────────────────────────
with tab1:
    st.session_state.setdefault("search_query_text", "")

    with st.form("ticker_search_form", clear_on_submit=False):
        typed = st.text_input(
            "회사명(한국어/영문) 또는 티커",
            value=st.session_state.get("search_query_text", ""),
            placeholder="예: 엔비디아, NVDA, 애플, 테슬라",
            key="search_typed",
        )
        submitted = st.form_submit_button("🔍 검색", use_container_width=True, type="primary")

    if submitted:
        s = (typed or "").strip()
        st.session_state.search_query_text = s
        qu_now = s.upper()
        # 검색 동작:
        #  ① 카탈로그 정확 티커(NVDA 등) → 즉시 분석
        #  ② 카탈로그에 매칭 후보 있으면 → 사용자 선택용 후보 표시 (아래에서)
        #  ③ 후보 0개 + 티커처럼 생긴 입력(FIG 등) → 카탈로그 외라도 그대로 시도
        if qu_now and qu_now in TICKER_NAMES:
            st.session_state.search_symbol = qu_now
        elif s and _looks_like_ticker(qu_now) and not search_tickers(s, limit=1):
            st.session_state.search_symbol = qu_now

    query = st.session_state.get("search_query_text", "")
    qu = query.upper()

    # 후보 표시: 카탈로그에 부분 매칭이 있는 경우 (예: '엔비', 'apple')
    if query and qu not in TICKER_NAMES:
        candidates = search_tickers(query, limit=8)
        if candidates:
            st.caption(f"'{query}' 와 비슷한 종목 — 톡 누르면 분석돼요")
            labels = [f"{name.split()[0]} ({tk})" for tk, name in candidates]
            picked = st.pills("후보 종목", labels, selection_mode="single",
                              label_visibility="collapsed", key="search_pick")
            if picked:
                idx = labels.index(picked)
                st.session_state.search_symbol = candidates[idx][0]
        elif not _looks_like_ticker(qu):
            st.info(f"'{query}' 와 비슷한 종목을 못 찾았어요. 회사명(한국어/영문) 또는 티커로 다시 시도해 주세요.")

    if st.session_state.search_symbol:
        sym = st.session_state.search_symbol
        st.caption(f"분석 중인 종목: **{display_name(sym)}**  ·  "
                   f"🔗 공유: 주소창 URL을 카톡으로 보내면 친구도 같은 화면을 볼 수 있어요. "
                   f"(`?symbol={sym}`)")
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
        with st.expander(f"📊 섹터 종목 수익률 비교 ({len(SECTORS[name])}개 겹쳐 보기)"):
            render_comparison(SECTORS[name], key=f"sector_{name}")

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
