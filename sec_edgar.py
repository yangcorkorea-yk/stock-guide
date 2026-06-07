"""
SEC EDGAR 공시 클라이언트 — 무료, API 키 불필요.

설계:
- SEC 규정상 User-Agent에 실제 이메일 필요. SEC_USER_AGENT 환경변수로 설정 가능.
- Form 4 (내부자 거래): code 'P' (open market purchase) 만 강한 신호로 취급.
  코드 'S' (sale), 'M' (option exercise), 'F' (tax withholding) 등은 노이즈 많음.
- 8-K (중요 사건): 최근 N일 건수 + 항목(item) 코드.

학계 근거:
- Lakonishok & Lee (2001), Seyhun (1998) 등 — 내부자 '매수' 약한 강세 신호
- 매도는 옵션 행사·다각화·세금 등 노이즈 많아 해석 어려움

레이트 리밋: SEC 권고 10 req/s. functools.lru_cache로 회사 메타데이터 캐싱.
"""
from __future__ import annotations

import functools
import os
from datetime import date, timedelta
from typing import Optional
from xml.etree import ElementTree as ET

import requests

UA = (os.getenv("SEC_USER_AGENT")
      or "stock-guide research alexko3836@gmail.com")
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
TIMEOUT = 10


@functools.lru_cache(maxsize=1)
def _ticker_to_cik() -> dict:
    """SEC 공식 ticker→CIK 매핑 (프로세스당 1회 다운로드, lru_cache)."""
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return {}
        data = r.json() or {}
        return {item["ticker"].upper(): str(item["cik_str"]).zfill(10)
                for item in data.values()
                if isinstance(item, dict) and item.get("ticker")}
    except Exception:
        return {}


def get_cik(ticker: str) -> Optional[str]:
    """Ticker → 10자리 zero-padded CIK 문자열."""
    return _ticker_to_cik().get(ticker.upper())


def _recent_filings(cik: str, form: str, days: int, limit: int) -> list[dict]:
    """공통 헬퍼 — submissions.json 에서 폼 타입·기간 필터."""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        recent = (r.json() or {}).get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accs = recent.get("accessionNumber", [])
        primaries = recent.get("primaryDocument", [])
        items_arr = recent.get("items", [])
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        out = []
        for i, f in enumerate(forms):
            if f != form:
                continue
            d = dates[i] if i < len(dates) else ""
            if d < cutoff:
                continue
            acc = accs[i] if i < len(accs) else ""
            pri = primaries[i] if i < len(primaries) else ""
            acc_clean = acc.replace("-", "")
            cik_int = int(cik)
            out.append({
                "form": f,
                "filing_date": d,
                "accession": acc,
                "primary_doc": pri,
                "primary_url": (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik_int}/{acc_clean}/{pri}"
                ),
                "items": items_arr[i] if i < len(items_arr) else "",
                "index_url": (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"
                ),
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def get_recent_form4_list(ticker: str, days: int = 30, limit: int = 15) -> list[dict]:
    """내부자 거래 신고서(Form 4) 최근 목록."""
    cik = get_cik(ticker)
    if not cik:
        return []
    return _recent_filings(cik, "4", days=days, limit=limit)


def get_recent_8k_list(ticker: str, days: int = 14, limit: int = 20) -> list[dict]:
    """8-K (중요 사건) 최근 목록."""
    cik = get_cik(ticker)
    if not cik:
        return []
    return _recent_filings(cik, "8-K", days=days, limit=limit)


def _parse_form4_xml(text: str) -> Optional[dict]:
    """Form 4 XML 파싱. 실패 시 None."""
    try:
        root = ET.fromstring(text)
    except Exception:
        return None

    def _text(path, default=""):
        el = root.find(path)
        return (el.text or default) if el is not None else default

    owner = _text(".//reportingOwnerId/rptOwnerName", "")
    title = _text(".//reportingOwnerRelationship/officerTitle", "")
    is_officer = _text(".//reportingOwnerRelationship/isOfficer", "0") in ("1", "true")
    is_director = _text(".//reportingOwnerRelationship/isDirector", "0") in ("1", "true")
    is_ten_percent = _text(".//reportingOwnerRelationship/isTenPercentOwner", "0") in ("1", "true")

    purchases_shares = 0.0
    purchases_value = 0.0
    sales_shares = 0.0
    sales_value = 0.0
    other_count = 0

    for txn in root.findall(".//nonDerivativeTransaction"):
        code_el = txn.find(".//transactionCoding/transactionCode")
        if code_el is None:
            continue
        code = (code_el.text or "").strip()
        shares_el = txn.find(".//transactionAmounts/transactionShares/value")
        price_el = txn.find(".//transactionAmounts/transactionPricePerShare/value")
        try:
            shares = float(shares_el.text) if shares_el is not None else 0
            price = float(price_el.text) if price_el is not None else 0
        except Exception:
            continue
        value = shares * price
        if code == "P":          # 오픈 마켓 매수
            purchases_shares += shares
            purchases_value += value
        elif code == "S":        # 오픈 마켓 매도
            sales_shares += shares
            sales_value += value
        else:                    # M/A/F/G 등은 노이즈
            other_count += 1

    return {
        "owner": owner,
        "title": title,
        "is_officer": is_officer,
        "is_director": is_director,
        "is_ten_percent": is_ten_percent,
        "purchases_shares": int(purchases_shares),
        "purchases_value": purchases_value,
        "sales_shares": int(sales_shares),
        "sales_value": sales_value,
        "other_count": other_count,
    }


import re


def _form4_xml_candidates(filing: dict) -> list[str]:
    """
    Form 4 raw XML URL 후보들 — primaryDocument가 xslF345X03/* 경로면
    부모(=실제 XML)로도 시도해본다.
    """
    url = filing.get("primary_url") or ""
    primary_doc = filing.get("primary_doc") or ""
    candidates = []
    if url:
        candidates.append(url)
    # /xslXXX/foo.xml → /foo.xml 로 변환
    clean = re.sub(r"/xsl[^/]+/", "/", url)
    if clean and clean != url:
        candidates.append(clean)
    # primaryDocument 자체가 'xsl.../foo.xml' 형태면 부모 폴더에서 'foo.xml' 직접 시도
    if "/" in primary_doc and primary_doc.lower().startswith("xsl"):
        base = url.rsplit("/", 1)[0]
        # 'xsl.../foo.xml' 에서 'foo.xml' 추출
        last_part = primary_doc.split("/", 1)[1]
        candidates.append(f"{base.rsplit('/', 1)[0]}/{last_part}")
    # 중복 제거 유지
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def fetch_form4_detail(filing: dict) -> Optional[dict]:
    """
    Form 4 한 건의 거래 상세.
    여러 URL 후보를 순차 시도 — SEC가 'primaryDocument'로 xsl 래퍼(HTML)를
    주기 때문에 그 경로에선 XML 파싱이 실패함. 부모 경로의 raw XML 도 같이 시도.
    """
    candidates = _form4_xml_candidates(filing)
    if not candidates:
        return None
    for url in candidates:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            text = r.text
            if "<ownershipDocument" not in text and not text.lstrip().startswith("<?xml"):
                continue
            parsed = _parse_form4_xml(text)
            if parsed is not None:
                return parsed
        except Exception:
            continue
    return None


def summarize_insider_activity(ticker: str, days: int = 30,
                                max_parse: int = 10) -> dict:
    """
    종목 상세용 요약. max_parse 만큼만 XML 파싱 (레이트 리밋 보호).

    반환:
      {
        "filings_count": int,
        "buys": [{owner, title, shares, value, date}, ...],   # P only
        "sells": [{owner, title, shares, value, date}, ...],  # S only
        "buy_total_value": float,
        "sell_total_value": float,
        "parsed_count": int,
        "filings_url": str,  # SEC 페이지 링크
      }
    """
    filings = get_recent_form4_list(ticker, days=days)
    buys, sells = [], []
    buy_total = 0.0
    sell_total = 0.0
    parsed = 0
    for f in filings[:max_parse]:
        d = fetch_form4_detail(f)
        if not d:
            continue
        parsed += 1
        if d["purchases_shares"] > 0:
            buys.append({
                "owner": d["owner"],
                "title": d["title"] or _role_label(d),
                "shares": d["purchases_shares"],
                "value": d["purchases_value"],
                "date": f["filing_date"],
            })
            buy_total += d["purchases_value"]
        if d["sales_shares"] > 0:
            sells.append({
                "owner": d["owner"],
                "title": d["title"] or _role_label(d),
                "shares": d["sales_shares"],
                "value": d["sales_value"],
                "date": f["filing_date"],
            })
            sell_total += d["sales_value"]

    cik = get_cik(ticker) or ""
    filings_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik}&type=4&dateb=&owner=include&count=40"
        if cik else ""
    )
    return {
        "filings_count": len(filings),
        "buys": sorted(buys, key=lambda x: -x["value"]),
        "sells": sorted(sells, key=lambda x: -x["value"]),
        "buy_total_value": buy_total,
        "sell_total_value": sell_total,
        "parsed_count": parsed,
        "filings_url": filings_url,
    }


def _role_label(d: dict) -> str:
    parts = []
    if d.get("is_officer"):
        parts.append("임원")
    if d.get("is_director"):
        parts.append("이사")
    if d.get("is_ten_percent"):
        parts.append("10%+ 주주")
    return " · ".join(parts) or "신고자"


# ──────────────────────────────────────────────
# 8-K (중요 사건 공시) 요약
# ──────────────────────────────────────────────

# 8-K Item 번호 → 한국어 의미 (대표적인 것만)
ITEM_LABELS = {
    "1.01": "중요 계약 체결",
    "1.02": "중요 계약 종료",
    "1.03": "파산·법정관리",
    "2.01": "자산 인수·매각 완료",
    "2.02": "실적 발표",
    "2.05": "구조조정 비용",
    "2.06": "자산 손상차손",
    "3.01": "상장 폐지 통보",
    "3.02": "신주 발행 (등록 면제)",
    "3.03": "주주 권리 변경",
    "4.01": "회계법인 변경",
    "4.02": "재무제표 수정·재공시",
    "5.01": "지배구조 변경",
    "5.02": "임원·이사 변경",  # CEO 사임/선임 등
    "5.03": "정관 변경",
    "5.07": "주주총회 결과",
    "5.08": "주주총회 일정",
    "7.01": "Reg FD 공시 (보도자료)",
    "8.01": "기타 중요 사건",
}


def summarize_8k_activity(ticker: str, days: int = 14) -> dict:
    """
    최근 8-K 공시 요약. 빈도가 평소보다 높으면 위기/변화 신호.
    반환:
      {
        "count": int,
        "filings": [{date, items: [str], items_decoded: [str]}, ...],
        "filings_url": str,
      }
    """
    filings = get_recent_8k_list(ticker, days=days, limit=20)
    items_decoded_list = []
    for f in filings:
        raw = f.get("items") or ""
        codes = [c.strip() for c in raw.split(",") if c.strip()]
        decoded = [ITEM_LABELS.get(c, f"Item {c}") for c in codes]
        items_decoded_list.append({
            "date": f["filing_date"],
            "items": codes,
            "items_decoded": decoded,
            "url": f["primary_url"],
        })
    cik = get_cik(ticker) or ""
    filings_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik}&type=8-K&dateb=&owner=include&count=20"
        if cik else ""
    )
    return {
        "count": len(filings),
        "filings": items_decoded_list,
        "filings_url": filings_url,
    }
