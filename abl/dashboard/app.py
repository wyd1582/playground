"""Guardian & Learning dashboard — `make watch` (``streamlit run dashboard/app.py``).

A separate, read-only process (OPS.md D.1/D.3): it tails registry/events.jsonl, reads the
registry through ``registry.db.connect_readonly`` and never imports agent/engine/gate code.
Writes: dashboard/state.json + registry/alarms.log (via ``notify``) and control/PAUSE (buttons).

Live panels are ``@st.fragment(run_every="5s")`` — no sleep/rerun loop — and registry reads
are cached for 5 s (``st.cache_data(ttl=5)``), so an idle tab costs almost no CPU. A locked
registry returns the previous snapshot for that tick instead of blocking.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
if str(_PROJECT) not in sys.path:          # `streamlit run dashboard/app.py` puts dashboard/ on the path
    sys.path.insert(0, str(_PROJECT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from common import paths  # noqa: E402
from dashboard import control, i18n  # noqa: E402
from dashboard.alarms import compute_alarms, notify  # noqa: E402
from dashboard.i18n import t  # noqa: E402
from dashboard.narrative import narrate  # noqa: E402
from dashboard.reader import (EventFeed, RegistryReader, load_package, parse_ts,  # noqa: E402
                              registry_gate_events, utcnow)

REFRESH = "5s"
FEED_ROWS = 60
# categorical slots 1-3 of the dataviz reference palette (validated all-pairs, light mode)
SERIES = {"promoted": "#2a78d6", "rejected": "#eb6834", "in_progress": "#1baf7a"}
LEVEL_STYLE = {"fail": (":material/error:", "red"), "warn": (":material/undo:", "orange"),
               "promote": (":material/star:", "green"), "info": (":material/info:", None)}
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+!|~$:])")
LANG_KEY = "abl_lang"                     # session_state key of the 中文 / English switch
ALL_CAMPAIGNS = ""                        # sentinel option: label comes from t() at render time


# --------------------------------------------------------------------------------------------
# shared, cached data access
# --------------------------------------------------------------------------------------------
@st.cache_resource
def _feed() -> EventFeed:
    return EventFeed(maxlen=5000)


@st.cache_resource
def _reader() -> RegistryReader:
    return RegistryReader(keep_last=True)


@st.cache_data(ttl=5, max_entries=512, show_spinner=False)
def _q(method: str, *args, **kwargs):
    return getattr(_reader(), method)(*args, **kwargs)


class _CachedReader:
    """RegistryReader facade whose every method goes through the 5 s cache (used by alarms)."""

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: _q(name, *args, **kwargs)


def _apply_lang() -> None:
    """Point the i18n override at this session's choice. Called at the top of main() AND of every
    fragment, because a fragment rerun does not re-execute main()."""
    if LANG_KEY not in st.session_state:
        st.session_state[LANG_KEY] = i18n.current_lang()          # honours ABL_LANG
    lang = st.session_state[LANG_KEY]
    i18n.set_lang(lang if lang in i18n.LANGS else i18n.DEFAULT_LANG)


def _when(v) -> str:
    return t("exhausted") if v == "exhausted" else (v or "—")


def _md(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def _hhmm(ts) -> str:
    t = parse_ts(ts)
    return t.strftime("%m-%d %H:%M:%S") if t else "--:--:--"


# --------------------------------------------------------------------------------------------
# LEFT — Learning
# --------------------------------------------------------------------------------------------
@st.cache_data(ttl=5, max_entries=4, show_spinner=False)
def _gate_feed(limit: int) -> list[dict]:
    return registry_gate_events(_reader(), None, limit)


# full-width buttons: `width="stretch"` (1.46+) or the older `use_container_width=True`
_FULL_WIDTH = ({"width": "stretch"} if "width" in __import__("inspect").signature(st.button).parameters
               else {"use_container_width": True})


def _bar_chart(data, **kwargs) -> None:
    """st.bar_chart with only the keyword arguments this Streamlit release supports
    (horizontal/stack/sort/x_label/y_label arrived between 1.36 and 1.41)."""
    import inspect
    allowed = set(inspect.signature(st.bar_chart).parameters)
    st.bar_chart(data, **{k: v for k, v in kwargs.items() if k in allowed})


@st.fragment(run_every=REFRESH)
def feed_panel() -> None:
    _apply_lang()
    feed = _feed()
    feed.poll()
    # gates record outcomes in SQL only, so their failures/promotions are merged in from the registry
    gate_evs = _gate_feed(FEED_ROWS)
    events = sorted(feed.snapshot()[-3 * FEED_ROWS:] + gate_evs, key=lambda e: str(e.get("ts") or ""))
    st.subheader(t("app_feed_title"))
    only = st.toggle(t("app_feed_only"), key="feed_only")
    shown = 0
    with st.container(height=520):
        if not events:
            st.caption(t("app_feed_empty", path=feed.path))
        for ev in reversed(events):
            text, level = narrate(ev)
            if only and level == "info":
                continue
            icon, color = LEVEL_STYLE.get(level, LEVEL_STYLE["info"])
            label = f"{_hhmm(ev.get('ts'))} · {_md(text)}"
            if color:
                label = f":{color}[{label}]"
            with st.expander(label, icon=icon):
                st.json(ev, expanded=True)
            shown += 1
            if shown >= FEED_ROWS:
                break
    st.caption(t("app_feed_caption", total=feed.total, gates=len(gate_evs), shown=shown))


@st.fragment(run_every=REFRESH)
def mechanism_panel(campaign: str | None) -> None:
    _apply_lang()
    st.subheader(t("app_mech_title"))
    mm = _q("mechanism_map", campaign)
    if mm.empty:
        st.info(t("app_no_proposals"))
        return
    top = mm.head(15)
    legend = {"promoted": t("app_series_promoted"), "rejected": t("app_series_rejected"),
              "in_progress": t("app_series_in_progress")}
    chart = top.set_index("mechanism_cluster")[list(SERIES)].rename(columns=legend)
    _bar_chart(chart, horizontal=True, stack=True, sort=False, color=list(SERIES.values()),
               x_label=t("app_axis_proposals"), y_label=t("app_axis_cluster"),
               height=max(160, 34 * len(top) + 60))
    with st.expander(t("app_table_view")):
        st.dataframe(mm, hide_index=True,
                     column_config={"share": st.column_config.NumberColumn(t("app_col_share"), format="percent")})


@st.fragment(run_every=REFRESH)
def funnel_panel(campaign: str | None) -> None:
    _apply_lang()
    st.subheader(t("app_funnel_title"))
    fc = _q("funnel_compare", campaign)
    top = int(fc["campaign_to_date"].max() or 0) if len(fc) else 0
    stages = {"proposals": t("stage_proposals"), "reviewed": t("stage_reviewed"),
              "implemented": t("stage_implemented"), "validated": t("stage_validated"),
              "evaluated": t("stage_evaluated"), "promoted": t("stage_promoted")}
    if len(fc):
        fc = fc.assign(stage=fc["stage"].map(lambda s: stages.get(s, s)))
    st.dataframe(
        fc, hide_index=True,
        column_config={
            "stage": st.column_config.TextColumn(t("app_col_stage")),
            "today": st.column_config.NumberColumn(t("app_col_today"), format="%d"),
            "campaign_to_date": st.column_config.ProgressColumn(t("app_col_ctd"), format="%d",
                                                                min_value=0, max_value=max(top, 1)),
            "pct_of_proposals": st.column_config.NumberColumn(t("app_col_pct"), format="%.1f%%"),
        })


def _table(records) -> pd.DataFrame:
    """Package JSON -> display frame; mixed-type columns become text so Arrow never has to guess."""
    df = pd.DataFrame(records)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: "" if v is None else v if isinstance(v, str) else str(v))
    return df


def _render_package(pkg: dict) -> None:
    th, dsl = pkg.get("thesis") or {}, pkg.get("dsl") or {}
    data, tests = pkg.get("data_declaration") or {}, pkg.get("tests") or []
    prov, ev = pkg.get("provenance") or {}, pkg.get("evaluation") or {}
    tabs = st.tabs([t("app_tab_thesis"), t("app_tab_dsl"), t("app_tab_data"), t("app_tab_tests"),
                    t("app_tab_provenance"), t("app_tab_evaluation")])
    with tabs[0]:
        st.markdown(t("app_pkg_mechanism", v=_md(th.get("mechanism", "—"))))
        st.markdown(t("app_pkg_direction", v=_md(th.get("direction", "—"))))
        st.markdown(t("app_pkg_cluster", v=th.get("mechanism_cluster", "—")))
        st.markdown(t("app_pkg_falsifiers"))
        for f in th.get("falsifiers") or ["—"]:
            st.markdown(f"- {_md(f)}")
        st.markdown(t("app_pkg_expected_gain"))
        st.json(th.get("expected_gain") or {}, expanded=True)
        if th.get("source_refs"):
            st.caption(t("app_pkg_sources", refs=", ".join(map(str, th["source_refs"]))))
    with tabs[1]:
        st.code(dsl.get("text", ""), language="text")
        st.caption(t("app_pkg_dsl_caption", h=dsl.get("semantic_hash", "—"),
                     ops=", ".join(map(str, dsl.get("operators") or [])) or "—"))
    with tabs[2]:
        fields = data.get("fields") or []
        if fields:
            st.dataframe(_table(fields) if isinstance(fields[0], dict) else _table({"field": fields}), hide_index=True)
        st.caption(t("app_pkg_snapshot", snap=data.get("snapshot_id", "—"), h=data.get("hash", "—")))
        if data.get("versions"):
            st.json(data["versions"], expanded=False)
    with tabs[3]:
        if tests:
            st.dataframe(_table(tests), hide_index=True)
        else:
            st.caption(t("app_pkg_no_tests"))
    with tabs[4]:
        st.json(prov, expanded=True)
    with tabs[5]:
        gates = ev.get("gates") or []
        if gates:
            st.dataframe(_table(gates), hide_index=True)
        st.markdown(t("app_pkg_disposition", v=_md(ev.get("disposition", "—"))))
        for key, title in (("analyst_summary", t("app_pkg_analyst_summary")), ("diagnosis", t("app_pkg_diagnosis")),
                           ("next_experiment", t("app_pkg_next_experiment"))):
            if ev.get(key):
                val = ev[key]
                st.markdown(f"**{title}** — {_md(val) if isinstance(val, str) else ''}")
                if not isinstance(val, str):
                    st.json(val, expanded=False)


@st.fragment(run_every=REFRESH)
def explain_panel(campaign: str | None) -> None:
    _apply_lang()
    st.subheader(t("app_explain_title"))
    cands = _q("candidates", campaign)
    if cands.empty:
        st.info(t("app_no_candidates"))
        return
    meta = {r["candidate_id"]: r for r in cands.to_dict("records")}
    # candidates that have a BreedingPackage (full evaluation + Analyst) come first, promoted before rejected
    has_pkg = {c for c in meta if (paths.registry_dir() / "packages" / f"{c}.json").exists()}
    order = sorted(meta, key=lambda c: (c not in has_pkg, meta[c]["state"] != "promoted", c))
    cid = st.selectbox(t("app_candidate_select"), order, key="explain_cid",
                       format_func=lambda c: f"{c} · {meta[c]['state']} · {meta[c]['mechanism_cluster']}")
    if not cid:
        return
    row = meta[cid]
    st.caption(t("app_cand_caption", state=row["state"], retries=row["retry_count"], pid=row["proposal_id"],
                 cid=row["campaign_id"]))
    pkg = load_package(cid)
    if pkg:
        _render_package(pkg)
    else:
        st.caption(t("app_no_package", cid=cid))
    st.markdown(t("app_gate_results_title"))
    gr = _q("gate_results_for", cid)
    if gr.empty:
        st.caption(t("app_no_gate_results"))
    else:
        gr = gr.assign(passed=gr["passed"].map(lambda v: "PASS" if int(v or 0) else "FAIL"))
        st.dataframe(gr, hide_index=True)
    with st.expander(t("app_reviews_history")):
        st.dataframe(_q("critic_reviews", None, cid), hide_index=True)
        st.dataframe(_q("transitions", cid), hide_index=True)


# --------------------------------------------------------------------------------------------
# RIGHT — Guardian
# --------------------------------------------------------------------------------------------
@st.fragment(run_every=REFRESH)
def budget_panel(campaign: str | None) -> None:
    _apply_lang()
    st.subheader(t("app_budget_title"))
    b = _q("budget", campaign)
    if b.empty:
        st.info(t("app_no_campaign"))
        return
    rows = b.to_dict("records")
    shown = [r for r in rows if r["active"]] or rows[:1]
    for r in shown:
        st.markdown(f"**{r['campaign_id']}**" + ("" if r["active"] else t("app_ended")))
        c1, c2 = st.columns(2)
        tu, tc = int(r["tokens_used"] or 0), int(r["budget_tokens"] or 0)
        eu, ec = int(r["evals_used"] or 0), int(r["budget_full_evals"] or 0)
        c1.metric(t("app_tokens_cap"), f"{tu:,} / {tc:,}")
        c1.progress(min(tu / tc, 1.0) if tc else 0.0)
        c2.metric(t("app_evals_cap"), f"{eu} / {ec}")
        c2.progress(min(eu / ec, 1.0) if ec else 0.0)
        st.caption(t("app_burn_caption", h=r["window_hours"], tph=f"{float(r['tokens_per_hour']):,.0f}",
                     eph=f"{float(r['evals_per_hour']):.2f}", tout=_when(r["tokens_exhaust_at"]),
                     eout=_when(r["evals_exhaust_at"]), cost=f"{float(r['cost_usd']):.4f}"))


@st.fragment(run_every=REFRESH)
def alarms_panel() -> None:
    _apply_lang()
    st.subheader(t("app_alarms_title"))
    feed = _feed()
    feed.poll()
    alarms = compute_alarms(feed.alarm_events(), _CachedReader(), utcnow())
    notify(alarms)
    if alarms:
        for a in alarms:
            st.error(f"**{a.kind}** — {_md(a.message)}", icon=":material/warning:")
    else:
        st.success(t("app_no_alarms"), icon=":material/verified_user:")
    ts = _q("threshold_status")
    if not ts.empty:
        with st.expander(t("app_threshold_hash")):
            st.dataframe(ts[["campaign_id", "start_hash", "current_hash", "changed", "active"]], hide_index=True)


@st.fragment(run_every=REFRESH)
def control_panel() -> None:
    _apply_lang()
    st.subheader(t("app_controls_title"))
    s = control.control_state()
    if s["paused"]:
        st.warning(t("app_paused"), icon=":material/pause_circle:")
    elif s["run"]:
        st.success(t("app_running"), icon=":material/play_circle:")
    else:
        st.info(t("app_idle"), icon=":material/stop_circle:")
    c1, c2 = st.columns(2)
    # callbacks run before the rerun, so the state box above already shows the new state
    c1.button(t("app_btn_pause"), type="primary", disabled=s["paused"], key="btn_pause", **_FULL_WIDTH,
              on_click=control.pause)
    c2.button(t("app_btn_resume"), disabled=not s["paused"], key="btn_resume", on_click=control.resume, **_FULL_WIDTH)
    st.caption(f"`{control.pause_file()}`")


@st.fragment(run_every=REFRESH)
def reliability_panel(campaign: str | None) -> None:
    _apply_lang()
    st.subheader(t("app_reliability_title"))
    nc = _q("negative_control_reviews", campaign)
    fp = _q("false_promotions", campaign)
    n = len(nc)
    ok = int(pd.to_numeric(nc["correct"]).sum()) if n else 0
    c1, c2 = st.columns(2)
    c1.metric(t("app_nc_rejected"), f"{ok} / {n}")
    c2.metric(t("app_false_promotions"), len(fp))
    if len(fp):
        st.error(t("app_nc_promoted", ids=", ".join(map(str, fp["candidate_id"]))), icon=":material/gpp_bad:")
    if n and ok < n:
        st.warning(t("app_nc_not_rejected", n=n - ok), icon=":material/rule:")
    if n:
        st.dataframe(nc[["candidate_id", "mechanism_cluster", "verdict", "expected", "created_at"]], hide_index=True)
    cq = _q("critic_quality")
    if not cq.empty:
        with st.expander(t("app_critic_quality")):
            st.dataframe(cq, hide_index=True)


# --------------------------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------------------------
def _lang_switch() -> None:
    """Sidebar 中文 / English switch; the value lives in st.session_state[LANG_KEY]."""
    label = t("app_lang_label")
    # st.radio exists on every Streamlit release; segmented_control's keyword set changed across
    # versions (e.g. 1.40 has no `required`), so the portable widget is used unconditionally.
    st.radio(label, list(i18n.LANGS), format_func=i18n.lang_label, horizontal=True, key=LANG_KEY)


def main() -> None:
    _apply_lang()                                  # before any text renders (page title included)
    st.set_page_config(page_title=t("app_page_title"), layout="wide")
    with st.sidebar:
        _lang_switch()
    _apply_lang()                                  # the switch may just have changed this run's language
    camps = _q("campaigns")
    ids = list(camps["campaign_id"]) if not camps.empty else []
    active = [c for c, a in zip(ids, camps["active"]) if a] if ids else []
    options = [ALL_CAMPAIGNS] + ids
    default = options.index(active[0]) if active else 0
    with st.sidebar:
        choice = st.selectbox(t("app_campaign"), options, index=default, key="campaign",
                              format_func=lambda c: t("app_all_campaigns") if c == ALL_CAMPAIGNS else c)
        st.caption(t("app_abl_root", root=paths.root()))
        st.caption(t("app_registry_path", path=paths.registry_db())
                   + ("" if paths.registry_db().exists() else t("app_registry_missing")))
        err = _reader().last_error
        if err and paths.registry_db().exists():
            st.caption(t("app_last_read_skipped", err=err))
        st.caption(t("app_readonly_note"))
    campaign = None if choice == ALL_CAMPAIGNS else choice

    st.title(t("app_title"))
    left, right = st.columns(2, gap="large")
    with left:
        st.header(t("app_learning"))
        feed_panel()
        mechanism_panel(campaign)
        funnel_panel(campaign)
        explain_panel(campaign)
    with right:
        st.header(t("app_guardian"))
        alarms_panel()
        budget_panel(campaign)
        control_panel()
        reliability_panel(campaign)


main()
