# agent/triggers.py — 알림/트리거 엔진 (§8-3, LLM 없이 동작)
# Streamlit Cloud는 백그라운드 스케줄러가 없으므로 "접속 시 평가" 방식


def evaluate_triggers(snap: dict) -> list[dict]:
    """snap 키: regime, prev_regime, vix, prev_vix, liq_z, hy_1m_chg,
    my_var95, max_asset, my_weights(dict)"""
    fired = []

    def add(name, msg, level="warn"):
        fired.append({"name": name, "msg": msg, "level": level})

    if snap.get("prev_regime") and snap.get("regime") \
            and snap["regime"] != snap["prev_regime"]:
        add("레짐 전환", f"{snap['prev_regime']} → {snap['regime']}", "alert")

    vix, pvix = snap.get("vix"), snap.get("prev_vix")
    if vix is not None and vix >= 25 and (pvix is None or pvix < 25):
        add("VIX 급등", f"VIX {vix:.1f} (25 상회)", "alert")

    liq_z = snap.get("liq_z")
    if liq_z is not None and liq_z < -1.5:
        add("순유동성 급감", f"1M 변화 z-score {liq_z:.2f}", "alert")

    hy = snap.get("hy_1m_chg")
    if hy is not None and hy > 0.5:
        add("HY 스프레드 급등", f"1개월 {hy:+.2f}%p — 신용 스트레스", "alert")

    var = snap.get("my_var95")
    if var is not None and var < -0.025:
        add("내 포트 VaR 초과", f"일간 VaR95 {var*100:.2f}% (-2.5% 한도)", "warn")

    mw, cap = snap.get("my_weights") or {}, snap.get("max_asset")
    if mw and cap:
        over = {a: w for a, w in mw.items() if a != "CASH" and w > cap}
        if over:
            worst = max(over.items(), key=lambda kv: kv[1])
            add("자산 상한 위반",
                f"{worst[0]} {worst[1]*100:.0f}% > 한도 {cap*100:.0f}% (총 {len(over)}건)",
                "warn")
    return fired
