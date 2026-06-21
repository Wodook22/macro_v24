# data/fred.py — FRED 로더 (fredapi 1~2회 재시도 → CSV 3회 재시도 fallback)
import io
import os
import time
import requests
import pandas as pd
import streamlit as st

from core.config import FRED_SERIES
from core.utils import record, pct_change_by_calendar


def read_secret(name: str) -> str:
    try:
        v = st.secrets.get(name, "")
    except Exception:
        v = ""
    return v or os.getenv(name, "")


def _start_for(freq: str) -> str:
    return {"D": "2018-01-01", "W": "2015-01-01"}.get(freq, "1990-01-01")


def _via_api(sid: str, start: str, key: str) -> pd.Series:
    from fredapi import Fred
    s = Fred(api_key=key).get_series(sid, observation_start=start)
    time.sleep(0.4)
    s.index = pd.to_datetime(s.index)
    return pd.to_numeric(s, errors="coerce").dropna()


_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36")}


def _via_csv(sid: str, start: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    last = None
    for i in range(3):
        try:
            r = requests.get(url, timeout=20, headers=_UA)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = ["date", sid]
            df["date"] = pd.to_datetime(df["date"])
            s = pd.to_numeric(df.set_index("date")[sid], errors="coerce").dropna()
            return s[s.index >= start]
        except Exception as e:          # noqa: BLE001
            last = e
            time.sleep(0.7 * (i + 1))
    raise RuntimeError(f"FRED CSV 실패 {sid}: {last}")


@st.cache_data(ttl=3600, show_spinner=False)
def load_fred_series(sid: str) -> pd.Series | None:
    freq, div, _ = FRED_SERIES[sid]
    start = _start_for(freq)
    key = read_secret("FRED_API_KEY")
    s = None
    if key:
        for _ in range(2):                       # v18: fredapi 자체 재시도
            try:
                s = _via_api(sid, start, key)
                break
            except Exception:                    # noqa: BLE001
                time.sleep(1.0)
    if s is None or s.empty:
        try:
            s = _via_csv(sid, start)
        except Exception as e:                   # noqa: BLE001
            record(f"FRED:{sid}", False, str(e)[:80])
            return None                          # 호출부에서 결측 처리
    if div:
        s = s / div
    record(f"FRED:{sid}", True, f"{len(s)}건, 최신 {s.index[-1].date()}")
    return s


@st.cache_data(ttl=3600, show_spinner="FRED 매크로 데이터 로드 중...")
def build_macro() -> pd.DataFrame:
    """전 시리즈 로드 + 파생지표. 반환: 일간 union 인덱스 ffill DataFrame
    (유동성 계산은 engine/liquidity.py에서 W-WED 리샘플로 별도 수행)"""
    raw = {}
    for sid in FRED_SERIES:
        try:
            s = load_fred_series(sid)
            if s is not None and not s.empty:
                raw[sid] = s
        except Exception as e:                   # noqa: BLE001
            record(f"FRED:{sid}", False, str(e)[:120])
    df = pd.DataFrame(raw).sort_index().ffill()

    # TGA: 수요일 기준 우선, 없으면 주간 평균
    if "WDTGAL" in df:
        df["TGA"] = df["WDTGAL"].fillna(df.get("WTREGEN"))
    elif "WTREGEN" in df:
        df["TGA"] = df["WTREGEN"]

    if {"WALCL", "TGA", "RRPONTSYD"}.issubset(df.columns):
        df["Net_Liq"] = df["WALCL"] - df["TGA"] - df["RRPONTSYD"]

    if "M2SL" in df:
        df["M2_YoY"] = pct_change_by_calendar(df["M2SL"]).reindex(df.index).ffill()
    if "CPIAUCSL" in df:
        df["CPI_YoY"] = pct_change_by_calendar(df["CPIAUCSL"]).reindex(df.index).ffill()
    if "BAMLH0A0HYM2" in df:
        df["HY_1M_Chg"] = df["BAMLH0A0HYM2"].diff(21)
    if "DGS10" in df:
        df["DGS10_1M_Chg"] = df["DGS10"].diff(21)
    if "NFCI" in df:
        df["NFCI_1M_Chg"] = df["NFCI"].diff(21)   # ffill된 일간 기준 약 1개월
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def buffett_indicator() -> pd.DataFrame | None:
    """버핏지표 (분기). v18: 절대구간 대신 장기평균 Z-score 병기 (§1-5)"""
    try:
        cap = load_fred_series("NCBEILQ027S")
        gdp = load_fred_series("GDP")
    except Exception:                            # noqa: BLE001
        return None
    if cap is None or gdp is None:
        return None
    q = pd.DataFrame({"cap": cap, "gdp": gdp}).resample("QE").last().dropna()
    if q.empty:
        return None
    q["ratio"] = q["cap"] / q["gdp"]
    mu, sd = q["ratio"].mean(), q["ratio"].std()
    q["z"] = (q["ratio"] - mu) / sd if sd else float("nan")
    return q
