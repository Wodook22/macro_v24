# data/market.py — yfinance / CNN Fear&Greed
import requests
import pandas as pd
import streamlit as st

from core.utils import record


@st.cache_data(ttl=900, show_spinner=False)
def fetch_prices(tickers: tuple, period: str = "2y") -> tuple[pd.DataFrame, pd.DataFrame]:
    """일괄 다운로드 → (close, volume). 실패 티커는 결측으로 두고 상태 기록"""
    import yfinance as yf
    tickers = list(dict.fromkeys(tickers))
    df = yf.download(tickers, period=period, auto_adjust=True,
                     progress=False, threads=True, group_by="column")
    if df is None or df.empty:
        record("yfinance", False, "다운로드 실패")
        return pd.DataFrame(), pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].copy()
        volume = df["Volume"].copy() if "Volume" in df.columns.get_level_values(0) else pd.DataFrame()
    else:  # 단일 티커
        close = df[["Close"]].rename(columns={"Close": tickers[0]})
        volume = df[["Volume"]].rename(columns={"Volume": tickers[0]}) if "Volume" in df else pd.DataFrame()
    def _naive(idx):
        idx = pd.to_datetime(idx)
        return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx

    close.index = _naive(close.index)
    if not volume.empty:
        volume.index = _naive(volume.index)
    bad = [t for t in tickers if t not in close.columns or close[t].dropna().empty]
    record("yfinance", True, f"{len(tickers)-len(bad)}/{len(tickers)} 성공"
           + (f", 실패: {','.join(bad[:5])}" if bad else ""))
    return close.dropna(how="all"), volume


@st.cache_data(ttl=600, show_spinner=False)
def fetch_fear_greed(vix: float | None = None,
                     vix_series=None) -> dict | None:
    """공포탐욕지수 — CNN → alternative.me → VIX 자체계산 3단 fallback"""
    # ── 1) CNN (브라우저 헤더)
    from datetime import date, timedelta
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://edition.cnn.com",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    }
    base = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    for url in (base, f"{base}/{(date.today()-timedelta(days=30)).isoformat()}"):
        try:
            r = requests.get(url, headers=headers, timeout=12)
            r.raise_for_status()
            d = r.json().get("fear_and_greed", {})
            if d:
                record("CNN F&G", True)
                return {"score": round(float(d.get("score", float("nan"))), 1),
                        "rating": d.get("rating", ""), "source": "CNN"}
        except Exception:                        # noqa: BLE001
            pass

    # ── 2) alternative.me (크립토 Fear & Greed, 주식 심리와 상관성 높음)
    try:
        r = requests.get("https://api.alternative.me/fng/",
                         params={"limit": 1, "format": "json"}, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [{}])[0]
        score = int(data.get("value", 0))
        label = data.get("value_classification", "")
        record("CNN F&G", True, "alternative.me")
        return {"score": score, "rating": label, "source": "alternative.me"}
    except Exception:                            # noqa: BLE001
        pass

    # ── 3) VIX 기반 자체 계산 (히스토리 있으면 퍼센타일, 없으면 구간 매핑)
    if vix is None:
        record("CNN F&G", False, "모든 소스 실패, VIX 없음")
        return None

    import numpy as np
    if vix_series is not None and hasattr(vix_series, "__len__") and len(vix_series) > 100:
        arr = vix_series.dropna().values
        pct = float((arr < vix).mean())
        score = int((1 - pct) * 100)
    else:
        score = (90 if vix <= 12 else 70 if vix <= 17 else 55 if vix <= 20
                 else 40 if vix <= 25 else 25 if vix <= 30 else 10)

    score = max(0, min(100, score))
    if score >= 75:   rating = "Extreme Greed"
    elif score >= 55: rating = "Greed"
    elif score >= 45: rating = "Neutral"
    elif score >= 25: rating = "Fear"
    else:             rating = "Extreme Fear"
    record("CNN F&G", True, f"VIX-based (VIX={vix:.1f})")
    return {"score": score, "rating": rating, "source": f"VIX-based ({vix:.1f})"}


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_etf_pe(etfs: tuple) -> dict:
    """ETF trailing PER — .info는 자주 깨지므로 전부 개별 try (§10-3)"""
    import yfinance as yf
    out, fail = {}, []
    for t in etfs:
        try:
            pe = yf.Ticker(t).info.get("trailingPE")
            out[t] = float(pe) if pe else None
        except Exception:                        # noqa: BLE001
            out[t] = None
            fail.append(t)
    record("yfinance:PER", len(fail) < len(etfs),
           f"실패 {len(fail)}/{len(etfs)}" if fail else "전체 성공")
    return out
