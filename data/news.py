# data/news.py v18.3 — GDELT 429 근본 해결
import time, random, urllib.parse
import requests, pandas as pd
import streamlit as st
from core.config import NEWS_CATEGORIES
from core.utils import record

_GDELT_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}
_SESS_KEY = "_gdelt_cache"


@st.cache_data(ttl=43200, show_spinner=False)
def _fetch_all_gdelt() -> dict:
    """4개 카테고리 순차+랜덤지연 호출 (동시 요청 차단 → 429 해결)"""
    results = {}
    cats = list(NEWS_CATEGORIES.keys())
    random.shuffle(cats)
    for i, cat in enumerate(cats):
        if i > 0:
            time.sleep(random.uniform(2.5, 5.0))
        kws = NEWS_CATEGORIES[cat]
        q = " OR ".join(f'"{k}"' if " " in k else k for k in kws)
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?"
               + urllib.parse.urlencode({"query": f"({q}) sourcelang:eng",
                                         "mode": "timelinevol",
                                         "timespan": "4months",
                                         "format": "json"}))
        res = None
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=30, headers=_GDELT_HEADERS)
                r.raise_for_status()
                tl = r.json().get("timeline", [])
                if not tl:
                    raise RuntimeError("timeline 없음")
                data = pd.DataFrame(tl[0]["data"])
                data["date"] = pd.to_datetime(data["date"].str[:8])
                s = data.set_index("date")["value"].astype(float).sort_index()
                recent = s.tail(7).mean()
                base = s.iloc[:-7].mean()
                ratio = recent / base if base else 1.0
                score = float(min(100, max(0, 50 * ratio)))
                res = {"score": round(score), "ratio": round(ratio, 2), "series": s}
                record(f"GDELT:{cat}", True)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(6 * (2 ** attempt) + random.uniform(0, 2))
                    continue
                record(f"GDELT:{cat}", False, str(e)[:80])
                break
        results[cat] = res
    return results


def gdelt_all() -> dict:
    """캐시 실패 시 session_state 마지막 성공값 반환"""
    try:
        fresh = _fetch_all_gdelt()
        prev = st.session_state.get(_SESS_KEY, {})
        merged = {**prev, **{k: v for k, v in fresh.items() if v is not None}}
        st.session_state[_SESS_KEY] = merged
        return fresh
    except Exception:
        return st.session_state.get(_SESS_KEY, {cat: None for cat in NEWS_CATEGORIES})


def gdelt_category_score(category: str) -> dict | None:
    return gdelt_all().get(category)


@st.cache_data(ttl=3600, show_spinner=False)
def rss_headlines(category: str, n: int = 6) -> list[dict]:
    import feedparser
    kws = NEWS_CATEGORIES[category]
    q = urllib.parse.quote(" OR ".join(f'"{k}"' for k in kws))
    feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    out = [{"title": e.get("title", ""), "link": e.get("link", ""),
            "published": e.get("published", "")} for e in feed.entries[:n]]
    record(f"RSS:{category}", bool(out), f"{len(out)}건")
    return out


def total_geo_score(cat_scores: dict) -> tuple:
    vals, wts = [], []
    for cat, sc in cat_scores.items():
        if sc is None:
            continue
        w = 1.5 if cat == "전쟁/분쟁" else 1.0
        vals.append(sc * w)
        wts.append(w)
    if not wts:
        return 50, "Medium"
    score = int(sum(vals) / sum(wts))
    return score, ("Low" if score < 45 else "Medium" if score < 65 else "High")
