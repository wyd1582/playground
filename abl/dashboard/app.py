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
from dashboard import control  # noqa: E402
from dashboard.alarms import compute_alarms, notify  # noqa: E402
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


@st.fragment(run_every=REFRESH)
def feed_panel() -> None:
    feed = _feed()
    feed.poll()
    # gates record outcomes in SQL only, so their failures/promotions are merged in from the registry
    gate_evs = _gate_feed(FEED_ROWS)
    events = sorted(feed.snapshot()[-3 * FEED_ROWS:] + gate_evs, key=lambda e: str(e.get("ts") or ""))
    st.subheader("Live narrative feed")
    only = st.toggle("Only Critic returns, gate failures, promotions and policy flags", key="feed_only")
    shown = 0
    with st.container(height=520):
        if not events:
            st.caption(f"No events yet in `{feed.path}`.")
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
    st.caption(f"{feed.total} events read from events.jsonl + {len(gate_evs)} recent gate outcomes from the "
               f"registry · newest first · showing {shown}")


@st.fragment(run_every=REFRESH)
def mechanism_panel(campaign: str | None) -> None:
    st.subheader("Mechanism map")
    mm = _q("mechanism_map", campaign)
    if mm.empty:
        st.info("No proposals in the registry yet.")
        return
    top = mm.head(15)
    chart = top.set_index("mechanism_cluster")[["promoted", "rejected", "in_progress"]]
    st.bar_chart(chart, horizontal=True, stack=True, sort=False, color=list(SERIES.values()),
                 x_label="proposals", y_label="mechanism cluster",
                 height=max(160, 34 * len(top) + 60))
    with st.expander("Table view"):
        st.dataframe(mm, hide_index=True,
                     column_config={"share": st.column_config.NumberColumn("share", format="percent")})


@st.fragment(run_every=REFRESH)
def funnel_panel(campaign: str | None) -> None:
    st.subheader("Funnel — today vs campaign-to-date")
    fc = _q("funnel_compare", campaign)
    top = int(fc["campaign_to_date"].max() or 0) if len(fc) else 0
    st.dataframe(
        fc, hide_index=True,
        column_config={
            "stage": st.column_config.TextColumn("stage"),
            "today": st.column_config.NumberColumn("today (UTC)", format="%d"),
            "campaign_to_date": st.column_config.ProgressColumn("campaign-to-date", format="%d",
                                                                min_value=0, max_value=max(top, 1)),
            "pct_of_proposals": st.column_config.NumberColumn("% of proposals", format="%.1f%%"),
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
    tabs = st.tabs(["Thesis", "DSL", "Data declaration", "Tests", "Provenance", "Evaluation"])
    with tabs[0]:
        st.markdown(f"**Mechanism** — {_md(th.get('mechanism', '—'))}")
        st.markdown(f"**Direction** — {_md(th.get('direction', '—'))}")
        st.markdown(f"**Cluster** — `{th.get('mechanism_cluster', '—')}`")
        st.markdown("**Falsifiers**")
        for f in th.get("falsifiers") or ["—"]:
            st.markdown(f"- {_md(f)}")
        st.markdown("**Expected gain**")
        st.json(th.get("expected_gain") or {}, expanded=True)
        if th.get("source_refs"):
            st.caption("Sources: " + ", ".join(map(str, th["source_refs"])))
    with tabs[1]:
        st.code(dsl.get("text", ""), language="text")
        st.caption(f"semantic hash `{dsl.get('semantic_hash', '—')}` · operators: "
                   f"{', '.join(map(str, dsl.get('operators') or [])) or '—'}")
    with tabs[2]:
        fields = data.get("fields") or []
        if fields:
            st.dataframe(_table(fields) if isinstance(fields[0], dict) else _table({"field": fields}), hide_index=True)
        st.caption(f"snapshot `{data.get('snapshot_id', '—')}` · hash `{data.get('hash', '—')}`")
        if data.get("versions"):
            st.json(data["versions"], expanded=False)
    with tabs[3]:
        if tests:
            st.dataframe(_table(tests), hide_index=True)
        else:
            st.caption("No tests recorded.")
    with tabs[4]:
        st.json(prov, expanded=True)
    with tabs[5]:
        gates = ev.get("gates") or []
        if gates:
            st.dataframe(_table(gates), hide_index=True)
        st.markdown(f"**Disposition** — {_md(ev.get('disposition', '—'))}")
        for key, title in (("analyst_summary", "Analyst summary"), ("diagnosis", "Diagnosis"),
                           ("next_experiment", "Next experiment")):
            if ev.get(key):
                val = ev[key]
                st.markdown(f"**{title}** — {_md(val) if isinstance(val, str) else ''}")
                if not isinstance(val, str):
                    st.json(val, expanded=False)


@st.fragment(run_every=REFRESH)
def explain_panel(campaign: str | None) -> None:
    st.subheader("Explain this candidate")
    cands = _q("candidates", campaign)
    if cands.empty:
        st.info("No candidates in the registry yet.")
        return
    meta = {r["candidate_id"]: r for r in cands.to_dict("records")}
    cid = st.selectbox("candidate_id", list(meta), key="explain_cid",
                       format_func=lambda c: f"{c} · {meta[c]['state']} · {meta[c]['mechanism_cluster']}")
    if not cid:
        return
    row = meta[cid]
    st.caption(f"state **{row['state']}** · retries {row['retry_count']} · proposal `{row['proposal_id']}` · "
               f"campaign `{row['campaign_id']}`")
    pkg = load_package(cid)
    if pkg:
        _render_package(pkg)
    else:
        st.caption(f"No BreedingPackage at registry/packages/{cid}.json yet.")
    st.markdown("**Gate results (registry, with thresholds)**")
    gr = _q("gate_results_for", cid)
    if gr.empty:
        st.caption("No gate results recorded.")
    else:
        gr = gr.assign(passed=gr["passed"].map(lambda v: "PASS" if int(v or 0) else "FAIL"))
        st.dataframe(gr, hide_index=True)
    with st.expander("Critic reviews and state history"):
        st.dataframe(_q("critic_reviews", None, cid), hide_index=True)
        st.dataframe(_q("transitions", cid), hide_index=True)


# --------------------------------------------------------------------------------------------
# RIGHT — Guardian
# --------------------------------------------------------------------------------------------
@st.fragment(run_every=REFRESH)
def budget_panel(campaign: str | None) -> None:
    st.subheader("Budget")
    b = _q("budget", campaign)
    if b.empty:
        st.info("No campaign in the registry yet.")
        return
    rows = b.to_dict("records")
    shown = [r for r in rows if r["active"]] or rows[:1]
    for r in shown:
        st.markdown(f"**{r['campaign_id']}**" + ("" if r["active"] else " · ended"))
        c1, c2 = st.columns(2)
        tu, tc = int(r["tokens_used"] or 0), int(r["budget_tokens"] or 0)
        eu, ec = int(r["evals_used"] or 0), int(r["budget_full_evals"] or 0)
        c1.metric("Tokens used / cap", f"{tu:,} / {tc:,}")
        c1.progress(min(tu / tc, 1.0) if tc else 0.0)
        c2.metric("Full evaluations / cap", f"{eu} / {ec}")
        c2.progress(min(eu / ec, 1.0) if ec else 0.0)
        st.caption(f"Burn over the last {r['window_hours']} h: {float(r['tokens_per_hour']):,.0f} tokens/h · "
                   f"{float(r['evals_per_hour']):.2f} evals/h · tokens run out: {r['tokens_exhaust_at'] or '—'} · "
                   f"evals run out: {r['evals_exhaust_at'] or '—'} · spend ${float(r['cost_usd']):.4f}")


@st.fragment(run_every=REFRESH)
def alarms_panel() -> None:
    st.subheader("Policy alarms")
    feed = _feed()
    feed.poll()
    alarms = compute_alarms(feed.alarm_events(), _CachedReader(), utcnow())
    notify(alarms)
    if alarms:
        for a in alarms:
            st.error(f"**{a.kind}** — {_md(a.message)}", icon=":material/warning:")
    else:
        st.success("No policy alarms.", icon=":material/verified_user:")
    ts = _q("threshold_status")
    if not ts.empty:
        with st.expander("Threshold file hash (campaign start vs now)"):
            st.dataframe(ts[["campaign_id", "start_hash", "current_hash", "changed", "active"]], hide_index=True)


@st.fragment(run_every=REFRESH)
def control_panel() -> None:
    st.subheader("Controls")
    s = control.control_state()
    if s["paused"]:
        st.warning("PAUSED — control/PAUSE exists; the Orchestrator stops before its next step.",
                   icon=":material/pause_circle:")
    elif s["run"]:
        st.success("RUNNING — control/RUN present, no PAUSE.", icon=":material/play_circle:")
    else:
        st.info("IDLE — control/RUN is missing.", icon=":material/stop_circle:")
    c1, c2 = st.columns(2)
    # callbacks run before the rerun, so the state box above already shows the new state
    c1.button("PAUSE", type="primary", disabled=s["paused"], key="btn_pause", width="stretch",
              on_click=control.pause)
    c2.button("RESUME", disabled=not s["paused"], key="btn_resume", width="stretch", on_click=control.resume)
    st.caption(f"`{control.pause_file()}`")


@st.fragment(run_every=REFRESH)
def reliability_panel(campaign: str | None) -> None:
    st.subheader("Agent reliability")
    nc = _q("negative_control_reviews", campaign)
    fp = _q("false_promotions", campaign)
    n = len(nc)
    ok = int(pd.to_numeric(nc["correct"]).sum()) if n else 0
    c1, c2 = st.columns(2)
    c1.metric("Negative controls rejected by Critic", f"{ok} / {n}")
    c2.metric("False promotions", len(fp))
    if len(fp):
        st.error("Negative-control candidate(s) promoted: " + ", ".join(map(str, fp["candidate_id"])),
                 icon=":material/gpp_bad:")
    if n and ok < n:
        st.warning(f"The Critic did not REJECT {n - ok} negative-control review(s).", icon=":material/rule:")
    if n:
        st.dataframe(nc[["candidate_id", "mechanism_cluster", "verdict", "expected", "created_at"]], hide_index=True)
    cq = _q("critic_quality")
    if not cq.empty:
        with st.expander("Critic quality by arm (v_critic_quality)"):
            st.dataframe(cq, hide_index=True)


# --------------------------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="ABL Guardian & Learning", layout="wide")
    camps = _q("campaigns")
    ids = list(camps["campaign_id"]) if not camps.empty else []
    active = [c for c, a in zip(ids, camps["active"]) if a] if ids else []
    options = ["(all campaigns)"] + ids
    default = options.index(active[0]) if active else 0
    with st.sidebar:
        choice = st.selectbox("Campaign", options, index=default, key="campaign")
        st.caption(f"ABL_ROOT `{paths.root()}`")
        st.caption(f"registry `{paths.registry_db()}`" + ("" if paths.registry_db().exists() else " (missing)"))
        err = _reader().last_error
        if err and paths.registry_db().exists():
            st.caption(f"last registry read skipped: {err}")
        st.caption("Read-only · polls every 5 s · writes only dashboard/state.json, registry/alarms.log "
                   "and control/PAUSE")
    campaign = None if choice == options[0] else choice

    st.title("ABL — Guardian & Learning")
    left, right = st.columns(2, gap="large")
    with left:
        st.header("Learning")
        feed_panel()
        mechanism_panel(campaign)
        funnel_panel(campaign)
        explain_panel(campaign)
    with right:
        st.header("Guardian")
        alarms_panel()
        budget_panel(campaign)
        control_panel()
        reliability_panel(campaign)


main()
