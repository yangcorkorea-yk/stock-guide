"""
Alpaca API 키 로더 (이 파일은 GitHub에 올라가도 안전 — 키가 없음)
-------------------------------------------------
우선순위:
  ① Streamlit Cloud의 Secrets   (배포 환경)
  ② 환경변수                     (선택)
  ③ 로컬 config.py               (내 PC, GitHub엔 안 올림)
"""
import os


def _load():
    # ① Streamlit Cloud secrets
    try:
        import streamlit as st
        k = st.secrets.get("ALPACA_API_KEY")
        s = st.secrets.get("ALPACA_SECRET_KEY")
        if k and s:
            return k, s
    except Exception:
        pass

    # ② 환경변수
    k, s = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if k and s:
        return k, s

    # ③ 로컬 config.py
    try:
        from config import API_KEY, SECRET_KEY
        return API_KEY, SECRET_KEY
    except Exception:
        raise RuntimeError(
            "Alpaca API 키를 찾을 수 없어요.\n"
            "  · 로컬: config.py 에 키를 넣으세요\n"
            "  · 배포: Streamlit Cloud의 Secrets 에 ALPACA_API_KEY / ALPACA_SECRET_KEY 를 넣으세요"
        )


API_KEY, SECRET_KEY = _load()
