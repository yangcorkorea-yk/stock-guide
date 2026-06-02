"""
공식 출처(Fed/BLS/BEA) HTML을 가져와 Anthropic Claude로 일정을 JSON으로 추출,
data/macro_events.json 의 큐레이션 섹션을 자동 갱신.

월 1회 GH Actions cron이 실행. 페이지 구조 변경에도 LLM이 적응함.

환경변수:
  ANTHROPIC_API_KEY (필수)
  ANTHROPIC_MODEL   (옵션, 기본 claude-haiku-4-5)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "macro_events.json"

SOURCES = [
    {
        "key": "FOMC",
        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "tag": "🏦 FOMC",
        "what": "Fed FOMC 정례회의 발표일 (보통 2일간 회의의 두 번째 날 = 결정·기자회견 일)",
    },
    {
        "key": "CPI",
        "url": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "tag": "📊 CPI",
        "what": "월별 소비자물가지수(CPI) 발표일",
    },
    {
        "key": "PPI",
        "url": "https://www.bls.gov/schedule/news_release/ppi.htm",
        "tag": "📈 PPI",
        "what": "월별 생산자물가지수(PPI) 발표일 (BLS, 보통 CPI 다음날)",
    },
    {
        "key": "PCE",
        "url": "https://www.bea.gov/news/schedule",
        "tag": "💵 PCE",
        "what": "월별 PCE 물가지수(개인소비지출) 발표일",
    },
    {
        "key": "GDP",
        "url": "https://www.bea.gov/news/schedule",
        "tag": "📈 GDP",
        "what": "분기별 GDP 속보치(Advance Estimate) 발표일",
    },
]

PROMPT = """\
다음은 미국 공식 기관 발표 일정 페이지에서 추출한 텍스트예요.
이 페이지에서 **앞으로 12개월 이내**의 {what} 만 골라 JSON 배열로 주세요.

각 항목 스키마:
  {{"date": "YYYY-MM-DD", "name": "한국어 이벤트 이름", "desc": "한 줄 한국어 설명"}}

규칙:
- 과거 일정 제외 (today={today} 기준 오늘 포함 미래만)
- 이벤트 이름: 한국어 (예: "5월 CPI 발표", "FOMC 정례회의", "1Q GDP 속보치")
- desc: 1줄. 한국어. 빈 문자열도 허용
- 정확한 날짜를 모르는 항목은 제외
- **JSON 배열만** 출력. 다른 설명·마크다운·코드펜스 금지.

페이지 텍스트:
{text}
"""


def fetch_html(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (github-actions/stock-guide-refresh)"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def html_to_text(html: str, max_chars: int = 80000) -> str:
    """HTML → 텍스트. bs4 있으면 사용, 없으면 단순 태그 제거."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for s in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            s.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
    # 빈 줄 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


def extract_events(source: dict) -> list[dict]:
    """소스 페이지에서 LLM으로 이벤트 추출."""
    from anthropic import Anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수 필요")
    client = Anthropic(api_key=api_key)
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

    html = fetch_html(source["url"])
    text = html_to_text(html)

    resp = client.messages.create(
        model=model,
        max_tokens=2500,
        messages=[{"role": "user", "content": PROMPT.format(
            what=source["what"],
            today=date.today().isoformat(),
            text=text,
        )}],
    )
    raw = "".join(b.text if hasattr(b, "text") else "" for b in resp.content).strip()

    # JSON 배열만 추출
    m = re.search(r"\[\s*(?:\{.*?\}\s*,?\s*)*\]", raw, re.S)
    if not m:
        print(f"  [{source['key']}] JSON 추출 실패 — raw 200자: {raw[:200]!r}")
        return []
    try:
        items = json.loads(m.group(0))
    except Exception as e:
        print(f"  [{source['key']}] JSON 파싱 실패: {e}")
        return []

    today_s = date.today().isoformat()
    out = []
    for it in items:
        try:
            d = date.fromisoformat(it["date"])
            if d.isoformat() < today_s:
                continue
            out.append({
                "date": it["date"],
                "name": it.get("name") or "",
                "tag": source["tag"],
                "desc": it.get("desc") or "",
            })
        except Exception:
            continue
    return out


def main():
    today_s = date.today().isoformat()
    print(f"실행 시점: {today_s}")

    new_events: list[dict] = []
    failures: list[str] = []
    for src in SOURCES:
        print(f"\n→ {src['key']}  ({src['url']})")
        try:
            evs = extract_events(src)
            print(f"  {len(evs)}건 추출")
            new_events.extend(evs)
        except Exception as e:
            print(f"  ❌ 실패: {e}")
            failures.append(src["key"])

    if not new_events:
        print("\n⚠️ 추출 0건. 기존 JSON 유지하고 종료.")
        sys.exit(0)

    # 기존 JSON 로드
    try:
        existing = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        existing = {"events": []}

    # 갱신 정책:
    # · 새 추출과 같은 (date, tag) 키는 새 값으로 덮어씀
    # · 추출 실패한 소스(failures)의 기존 이벤트는 그대로 유지
    # · 그 외 미래 이벤트 중 새 키와 겹치지 않는 건 유지
    new_keys = {(e["date"], e["tag"]) for e in new_events}
    failed_tags = set()
    for f in failures:
        for src in SOURCES:
            if src["key"] == f:
                failed_tags.add(src["tag"])

    kept = []
    for e in existing.get("events", []):
        if e.get("date", "") < today_s:
            continue  # 과거 정리
        if (e.get("date"), e.get("tag", "")) in new_keys:
            continue  # 새 값으로 대체
        if e.get("tag") in failed_tags or e.get("tag") not in {s["tag"] for s in SOURCES}:
            kept.append(e)  # 실패한 소스 또는 외부 소스(자동 계산 외) 유지

    merged = sorted(kept + new_events, key=lambda x: x["date"])

    payload = {
        "notes": "미국 거시지표 발표 일정 — Fed/BLS/BEA 공식 페이지에서 자동 추출 (월 1회 GH Actions).",
        "source_links": {
            "FOMC": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "BLS": "https://www.bls.gov/schedule/news_release/",
            "BEA": "https://www.bea.gov/news/schedule",
        },
        "last_refresh": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refresh_failures": failures,
        "events": merged,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 저장: {OUT} ({len(merged)}건, 실패 소스: {failures or '없음'})")


if __name__ == "__main__":
    main()
