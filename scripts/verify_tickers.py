"""
SECTORS / THEMES 의 모든 티커가 실재하는 미국 상장 티커인지 검증.

검증 우선순위:
  ① Alpaca Trading API의 /v2/assets (키 있으면 가장 빠르고 정확)
  ② yfinance (키 없을 때 폴백)

응답 없거나 비활성/비상장이면 ❌ 로 출력 → 코드에서 교체할 것.

실행:
    python scripts/verify_tickers.py
"""
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# analysis.py 는 import 시 Alpaca 키를 로드함 — 검증 스크립트엔
# 키 없어도 동작하도록 더미 키로 채워서 import 통과시킨다.
os.environ.setdefault("ALPACA_API_KEY", "dummy-for-verify")
os.environ.setdefault("ALPACA_SECRET_KEY", "dummy-for-verify")

from analysis import SECTORS, THEMES


def collect_tickers():
    seen = {}
    for name, syms in SECTORS.items():
        for s in syms:
            seen.setdefault(s, []).append(f"SECTOR/{name}")
    for tname, info in THEMES.items():
        for seg in info["chain"]:
            for s in seg["stocks"]:
                seen.setdefault(s, []).append(f"THEME/{tname}·{seg['name']}")
    return seen


def verify_with_alpaca(symbols):
    """Alpaca Trading API의 /v2/assets로 active US equity 여부 확인."""
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass, AssetStatus
    except Exception as e:
        print(f"alpaca-py import 실패: {e}")
        return None, None

    key = os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or key.startswith("dummy"):
        return None, None
    try:
        client = TradingClient(key, sec, paper=True)
        req = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
        assets = client.get_all_assets(req)
        active = {a.symbol for a in assets if a.tradable}
    except Exception as e:
        print(f"Alpaca 조회 실패: {e}")
        return None, None

    valid, invalid = set(), []
    for s in symbols:
        if s in active:
            valid.add(s)
        else:
            invalid.append((s, "Alpaca에서 active+tradable 아님"))
    return valid, invalid


def verify_with_yfinance(symbols):
    """yfinance batch download. 휴장일/네트워크 문제 시 재시도."""
    try:
        import yfinance as yf
    except Exception as e:
        print(f"yfinance import 실패: {e}")
        return None, None

    valid = set()
    invalid = []
    BATCH = 25
    syms = sorted(symbols)
    for i in range(0, len(syms), BATCH):
        chunk = syms[i:i + BATCH]
        try:
            data = yf.download(
                tickers=" ".join(chunk), period="5d", interval="1d",
                group_by="ticker", progress=False, threads=True, auto_adjust=True,
            )
        except Exception as e:
            print(f"  batch error ({chunk}): {e}")
            for s in chunk:
                invalid.append((s, "download error"))
            continue

        for s in chunk:
            try:
                sub = data if len(chunk) == 1 else (
                    data[s] if s in data.columns.get_level_values(0) else None)
                if sub is None or sub.empty or sub["Close"].dropna().empty:
                    invalid.append((s, "empty"))
                else:
                    valid.add(s)
            except (KeyError, ValueError, AttributeError):
                invalid.append((s, "missing"))
        time.sleep(0.3)
    return valid, invalid


def main():
    catalog = collect_tickers()
    syms = list(catalog.keys())
    print(f"총 고유 티커: {len(syms)}개\n")

    print("① Alpaca로 시도...")
    valid, invalid = verify_with_alpaca(syms)
    if valid is None:
        print("   → Alpaca 키 없음/실패. yfinance로 폴백.\n")
        print("② yfinance로 시도...")
        valid, invalid = verify_with_yfinance(syms)

    if valid is None:
        print("\n⚠️ 어떤 데이터 소스에도 접근할 수 없어요.")
        print("   네트워크가 차단된 환경(예: 일부 샌드박스)에선 검증을 건너뛰세요.")
        print("   로컬 PC나 Streamlit Cloud에서 실행하면 정상 동작합니다.")
        sys.exit(2)

    print(f"\n✅ 통과: {len(valid)}개")
    print(f"❌ 실패: {len(invalid)}개\n")

    if invalid:
        print("--- 실패 티커 (교체 필요) ---")
        for s, why in sorted(invalid):
            where = ", ".join(catalog[s][:3])
            print(f"  ❌ {s:6s}  ({why})  ← {where}")
        sys.exit(1)
    print("모든 티커 검증 완료.")


if __name__ == "__main__":
    main()
