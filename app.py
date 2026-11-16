"""Enterprise Ops Orchestrator — IBM Carbon Design System UI."""

import csv
import html
import io
import json
import os
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from agents import orchestrator
from agents.finance_agent import finance_agent
from agents.it_agent import it_agent
from agents.approvals import list_approvals, resolve_approval, APPROVALS_FILE
from tools.finance_tools import BUDGET_FILE

st.set_page_config(
    page_title="Enterprise Ops Orchestrator",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Carbon palette ────────────────────────────────────────────────────────────
C = {
    "bg":        "#161616",
    "surface":   "#262626",
    "surface2":  "#393939",
    "border":    "#393939",
    "text":      "#f4f4f4",
    "muted":     "#8d8d8d",
    "primary":   "#0f62fe",
    "success":   "#24a148",
    "warning":   "#f1c21b",
    "error":     "#da1e28",
    "info":      "#4589ff",
}

DEMO_START_SPEND = 420000
THINK_SECONDS = 0.4
STAGES = ["Backlog", "In Progress", "Awaiting Approval", "Done"]

SPEAKER_LABELS = {
    orchestrator.orchestrator_agent.name: "ORCH",
    orchestrator.it_agent.name: "IT",
    orchestrator.finance_agent.name: "FINANCE",
}

# ── Global CSS (loaded from file to prevent Streamlit from rendering it as text) ──
_CSS_FILE = Path(__file__).resolve().parent / "static" / "carbon.css"
st.markdown(
    f"<style>{_CSS_FILE.read_text()}</style>",
    unsafe_allow_html=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def load_budget() -> dict:
    return json.loads(BUDGET_FILE.read_text())


def reset_budget() -> None:
    budget = load_budget()
    budget["current_spend"] = DEMO_START_SPEND
    BUDGET_FILE.write_text(json.dumps(budget, indent=2) + "\n")


def reset_approvals() -> None:
    APPROVALS_FILE.write_text("[]\n")


def runtime_badge() -> str:
    region = os.getenv("WATSONX_REGION") or os.getenv("ORCHESTRATE_REGION") or ""
    agents_count = 3  # orchestrator, it_agent, finance_agent
    if region:
        label = f"IBM watsonx Orchestrate · {region} · {agents_count} agents"
    else:
        label = f"Local simulation mode · {agents_count} agents"
    return f'<span class="runtime-badge">{label}</span>'


def _pct(spend: float, cap: float) -> float:
    return min(spend / cap * 100, 100) if cap else 0


def kpi_html(label: str, value: str, sub: str = "") -> str:
    return (
        f'<div class="kpi-tile">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div>'
        f'</div>'
    )


def budget_bar_html(spend: float, cap: float) -> str:
    pct = _pct(spend, cap)
    over = spend > cap
    cls = "over" if over else ""
    return (
        f'<div class="budget-bar-track">'
        f'<div class="budget-bar-fill {cls}" style="width:{pct:.1f}%"></div>'
        f'</div>'
    )


def render_feed(placeholder) -> None:
    lines = []
    for ts, who, msg in st.session_state.feed:
        lowered = msg.lower()
        cls = "BLOCKED" if ("blocked" in lowered or "result: error" in lowered) else who
        lines.append(
            f'<span class="ts">[{ts}]</span> '
            f'<span class="{cls}">{who}</span> &gt; '
            f'{html.escape(msg).replace("$", "&#36;")}'
        )
    placeholder.markdown(
        f'<div class="terminal"><div>{"<br>".join(lines)}</div></div>',
        unsafe_allow_html=True,
    )


def render_trace(trace: list) -> None:
    """Render a Decision trace expander from a result trace list."""
    if not trace:
        st.caption("No trace available.")
        return
    for step in trace:
        oc = step.get("outcome", "")
        inputs_str = ", ".join(f"{k}={v}" for k, v in step["inputs"].items())
        try:
            out = json.loads(step["output"])
            out_str = json.dumps(out, indent=2)
        except (json.JSONDecodeError, TypeError):
            out_str = str(step["output"])
        st.markdown(
            f'<div class="trace-step {oc}">'
            f'<strong>{step["agent"]}</strong> &rarr; <code>{step["tool"]}({inputs_str})</code><br>'
            f'outcome: <strong>{oc}</strong><br>'
            f'<pre style="margin:4px 0 0;font-size:11px;color:#8d8d8d">{html.escape(out_str)}</pre>'
            f'</div>',
            unsafe_allow_html=True,
        )


def build_audit_rows() -> list[dict]:
    """Combine approvals + session run history into audit rows."""
    rows = []
    for appr in list_approvals():
        inv = appr.get("invoice") or {}
        rows.append({
            "timestamp": appr.get("created_at", ""),
            "agent": "finance_agent",
            "tool": "check_budget",
            "amount": inv.get("total_invoice", ""),
            "outcome": appr["status"],
            "approver": appr.get("approver", ""),
            "approval_id": appr["id"],
            "model": inv.get("model", ""),
            "quantity": inv.get("quantity", ""),
        })
    for run in st.session_state.get("run_history", []):
        if run.get("status") == "approved" and run.get("invoice"):
            inv = run["invoice"]
            rows.append({
                "timestamp": run.get("ts", ""),
                "agent": "finance_agent",
                "tool": "check_budget",
                "amount": inv.get("total_invoice", ""),
                "outcome": "approved (auto)",
                "approver": "system",
                "approval_id": "",
                "model": inv.get("model", ""),
                "quantity": inv.get("quantity", ""),
            })
    return sorted(rows, key=lambda r: r["timestamp"], reverse=True)


def policy_rules() -> list[dict]:
    """Extract policy rules from agent instructions and tool bindings — not hard-coded text."""
    rules = []
    for agent in (orchestrator.orchestrator_agent, it_agent, finance_agent):
        tools_bound = list(agent.tools) if agent.tools else []
        rules.append({
            "agent": agent.name,
            "tools": tools_bound,
            "instructions": agent.instructions or "",
        })
    return rules


# ── Session state init ────────────────────────────────────────────────────────
if "tasks" not in st.session_state:
    st.session_state.tasks = [
        {"title": "Onboard 12 sales hires (Chicago)", "owner": "IT Agent",      "stage": "Backlog",           "trace": []},
        {"title": "Provision laptops: Eng team",       "owner": "IT Agent",      "stage": "In Progress",       "trace": []},
        {"title": "Q4 hardware invoice review",        "owner": "Finance Agent", "stage": "Awaiting Approval", "trace": []},
        {"title": "Support desk refresh (5 units)",    "owner": "Finance Agent", "stage": "Done",              "trace": []},
    ]
if "feed" not in st.session_state:
    st.session_state.feed = [
        (now(), "SYSTEM", "Orchestrator online. Agents: orchestrator_agent, it_agent, finance_agent"),
        (now(), "IT",     "Standing by for hardware requests."),
        (now(), "FINANCE","Budget cap loaded: $500,000."),
    ]
if "run_history" not in st.session_state:
    st.session_state.run_history = []
if "active_node" not in st.session_state:
    st.session_state.active_node = None
if "visited_edges" not in st.session_state:
    st.session_state.visited_edges = []


# ── Header ────────────────────────────────────────────────────────────────────
budget = load_budget()
hdr_col, reset_col = st.columns([6, 1], vertical_alignment="bottom")
with hdr_col:
    st.markdown(
        f'<h1 style="font-family:IBM Plex Sans,sans-serif;font-weight:600;font-size:24px;'
        f'margin-bottom:2px">Enterprise Expansion &amp; Ops Orchestrator'
        f'{runtime_badge()}</h1>',
        unsafe_allow_html=True,
    )
    remaining = budget["total_cap"] - budget["current_spend"]
    sign = "" if remaining >= 0 else "-"
    st.caption(
        f"IBM watsonx Orchestrate ADK · FY2026 · "
        f"Budget: \\${budget['current_spend']:,} of \\${budget['total_cap']:,} spent · "
        f"{'\\${:,} remaining'.format(abs(int(remaining))) if remaining >= 0 else '\\${:,} OVER CAP'.format(abs(int(remaining)))}"
    )
with reset_col:
    if st.button("Reset Demo", use_container_width=True):
        reset_budget()
        reset_approvals()
        st.session_state.run_history = []
        st.session_state.active_node = None
        st.session_state.visited_edges = []
        st.session_state.feed.append((now(), "SYSTEM", f"Demo reset: spend = ${DEMO_START_SPEND:,}, approvals cleared."))
        st.rerun()

st.markdown('<hr style="border:none;border-top:1px solid #393939;margin:8px 0 16px">', unsafe_allow_html=True)


# ── KPI row ───────────────────────────────────────────────────────────────────
all_runs = st.session_state.run_history
n_processed   = len(all_runs)
n_approved    = sum(1 for r in all_runs if r.get("status") == "approved")
n_escalated   = sum(1 for r in all_runs if r.get("status") == "blocked")
avg_ms        = (sum(r.get("elapsed_ms", 0) for r in all_runs) // n_processed) if n_processed else 0
cap           = budget["total_cap"]
spend         = budget["current_spend"]
remaining_val = cap - spend
pct_used      = _pct(spend, cap)

k1, k2, k3, k4 = st.columns(4, gap="small")
with k1:
    st.markdown(kpi_html("Orders Processed", str(n_processed),
                         f"{n_approved} auto-approved · {n_escalated} escalated"), unsafe_allow_html=True)
with k2:
    st.markdown(kpi_html("Auto-Approved", str(n_approved),
                         f"{n_escalated} required human review"), unsafe_allow_html=True)
with k3:
    rem_str = f"${abs(int(remaining_val)):,}" if remaining_val >= 0 else f"-${abs(int(remaining_val)):,}"
    sub_bar = f'<div class="kpi-sub">{pct_used:.1f}% of cap used</div>' + budget_bar_html(spend, cap)
    st.markdown(
        f'<div class="kpi-tile">'
        f'<div class="kpi-label">Budget Remaining</div>'
        f'<div class="kpi-value" style="color:{"#da1e28" if remaining_val < 0 else "#f4f4f4"}">{rem_str}</div>'
        f'{sub_bar}'
        f'</div>',
        unsafe_allow_html=True,
    )
with k4:
    st.markdown(kpi_html("Avg Decision Time", f"{avg_ms} ms" if n_processed else "--",
                         "per orchestrator run"), unsafe_allow_html=True)

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)


# ── Main layout: tabs ─────────────────────────────────────────────────────────
tab_board, tab_audit, tab_policy = st.tabs(["Task Board & Feed", "Audit Log", "Policy & Guardrails"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Task Board + Agent Feed
# ══════════════════════════════════════════════════════════════════════════════
with tab_board:
    board_col, feed_col = st.columns([3, 2], gap="large")

    with board_col:
        # ── Agent flow diagram ────────────────────────────────────────────────
        st.markdown('<div class="section-label">Agent Flow</div>', unsafe_allow_html=True)

        active = st.session_state.active_node
        visited = set(st.session_state.visited_edges)

        def node_color(name: str) -> str:
            if name == active:
                return C["primary"]
            if name == "finance_agent" and active == "BLOCKED":
                return C["error"]
            return C["surface2"]

        def edge_color(pair: str) -> str:
            return C["primary"] if pair in visited else C["border"]

        orch_c   = node_color("orchestrator_agent")
        it_c     = node_color("it_agent")
        fin_c    = node_color("finance_agent")
        human_c  = node_color("HUMAN")
        user_c   = node_color("USER")

        e_u_o  = edge_color("USER->orchestrator_agent")
        e_o_it = edge_color("orchestrator_agent->it_agent")
        e_o_fi = edge_color("orchestrator_agent->finance_agent")
        e_fi_h = edge_color("finance_agent->HUMAN")

        dot = f"""
digraph G {{
    graph [bgcolor="{C['bg']}" fontname="IBM Plex Sans" splines=ortho rankdir=LR]
    node  [fontname="IBM Plex Sans" fontsize=11 style=filled shape=box margin="0.2,0.1"]
    edge  [fontname="IBM Plex Sans" fontsize=9 arrowsize=0.7]

    User          [label="User"              fillcolor="{user_c}"  fontcolor="{C['text']}" color="{C['border']}"]
    orchestrator  [label="orchestrator_agent" fillcolor="{orch_c}" fontcolor="{C['text']}" color="{C['border']}"]
    it            [label="it_agent"           fillcolor="{it_c}"   fontcolor="{C['text']}" color="{C['border']}"]
    finance       [label="finance_agent"      fillcolor="{fin_c}"  fontcolor="{C['text']}" color="{C['border']}"]
    Human         [label="Human Approver"     fillcolor="{human_c}" fontcolor="{C['text']}" color="{C['border']}"]

    User         -> orchestrator [label="prompt"   color="{e_u_o}"  fontcolor="{C['muted']}"]
    orchestrator -> it           [label="order"     color="{e_o_it}" fontcolor="{C['muted']}"]
    orchestrator -> finance      [label="invoice"   color="{e_o_fi}" fontcolor="{C['muted']}"]
    finance      -> Human        [label="blocked"   color="{e_fi_h}" fontcolor="{C['muted']}"]
}}
"""
        st.graphviz_chart(dot, use_container_width=True)

        # ── Pending approvals ─────────────────────────────────────────────────
        pending = list_approvals(status="pending")
        if pending:
            st.markdown('<div class="section-label">Awaiting Human Approval</div>', unsafe_allow_html=True)
            for appr in pending:
                inv       = appr["invoice"]
                total     = inv["total_invoice"]
                b         = load_budget()
                remaining_b = b["total_cap"] - b["current_spend"]
                over      = total - remaining_b
                pct_cur   = _pct(b["current_spend"], b["total_cap"])
                pct_after = _pct(b["current_spend"] + total, b["total_cap"])

                with st.container():
                    st.markdown(
                        f'<div class="approval-card">'
                        f'<div class="amount">${total:,}</div>'
                        f'<div style="font-size:13px;margin:4px 0">{inv["quantity"]} x {inv["model"]}</div>'
                        f'<div class="over">Over cap by ${max(over,0):,.2f}</div>'
                        f'<div class="meta">ID: {appr["id"]} &nbsp;|&nbsp; {appr["prompt"]}</div>'
                        f'<div style="margin-top:10px">'
                        f'  <div style="font-size:11px;color:{C["muted"]};margin-bottom:3px">'
                        f'    Budget impact: current {pct_cur:.0f}% &rarr; after approval {pct_after:.0f}%'
                        f'  </div>'
                        f'  <div class="budget-bar-track" style="position:relative">'
                        f'    <div class="budget-bar-fill" style="width:{min(pct_cur,100):.1f}%"></div>'
                        f'  </div>'
                        f'  <div class="budget-bar-track" style="margin-top:2px">'
                        f'    <div class="budget-bar-fill over" style="width:{min(pct_after,100):.1f}%"></div>'
                        f'  </div>'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    col_a, col_r = st.columns(2)
                    with col_a:
                        if st.button("Approve", key=f"approve_{appr['id']}", use_container_width=True):
                            resolve_approval(appr["id"], "approved", "dashboard_user")
                            st.session_state.feed.append((
                                now(), "HUMAN",
                                f"APPROVED override: {inv['quantity']} x {inv['model']} (\\${total:,}) — ID {appr['id']}"
                            ))
                            for t in st.session_state.tasks:
                                if t.get("approval_id") == appr["id"]:
                                    t["stage"] = "Done"
                                    break
                            st.rerun()
                    with col_r:
                        if st.button("Reject", key=f"reject_{appr['id']}", use_container_width=True):
                            resolve_approval(appr["id"], "rejected", "dashboard_user")
                            st.session_state.feed.append((
                                now(), "HUMAN",
                                f"REJECTED: {inv['quantity']} x {inv['model']} (\\${total:,}) — ID {appr['id']}"
                            ))
                            st.rerun()

            st.markdown('<hr style="border:none;border-top:1px solid #393939;margin:12px 0">', unsafe_allow_html=True)

        # ── Kanban board ──────────────────────────────────────────────────────
        st.markdown('<div class="section-label">Task Board</div>', unsafe_allow_html=True)
        for col, stage in zip(st.columns(len(STAGES)), STAGES):
            with col:
                items = [t for t in st.session_state.tasks if t["stage"] == stage]
                st.markdown(f"**{stage}** &nbsp;<span style='color:{C['muted']};font-size:12px'>{len(items)}</span>",
                            unsafe_allow_html=True)
                for t in items:
                    card_cls = "blocked" if stage == "Awaiting Approval" else ("done" if stage == "Done" else "")
                    st.markdown(
                        f'<div class="kanban-card {card_cls}">'
                        f'<div class="card-title">{html.escape(t["title"])}</div>'
                        f'<div class="card-owner">{html.escape(t["owner"])}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if t.get("trace"):
                        with st.expander("Decision trace"):
                            render_trace(t["trace"])

        # Resolved approvals
        resolved = [a for a in list_approvals() if a["status"] != "pending"]
        if resolved:
            with st.expander(f"Resolved Approvals ({len(resolved)})"):
                for appr in resolved:
                    inv   = appr["invoice"]
                    badge = "APPROVED" if appr["status"] == "approved" else "REJECTED"
                    color = C["success"] if appr["status"] == "approved" else C["error"]
                    st.markdown(
                        f'<span style="color:{color};font-size:12px;font-weight:600">[{badge}]</span> '
                        f'**{inv["quantity"]} x {inv["model"]}** — ${inv["total_invoice"]:,} '
                        f'by `{appr.get("approver","?")}` · ID `{appr["id"]}`',
                        unsafe_allow_html=True,
                    )

    with feed_col:
        # ── Live Agent Feed ───────────────────────────────────────────────────
        st.markdown('<div class="section-label">Live Agent Feed</div>', unsafe_allow_html=True)
        feed_box = st.empty()
        render_feed(feed_box)

        # ── Request form ──────────────────────────────────────────────────────
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        with st.form("simulate", clear_on_submit=True):
            st.markdown('<div class="section-label">Send Request</div>', unsafe_allow_html=True)
            prompt = st.text_input(
                "Request", placeholder="Order 10 ThinkPads", label_visibility="collapsed"
            )
            submitted = st.form_submit_button("Run", use_container_width=True)

        if submitted:
            if not prompt.strip():
                st.warning("Type a request first.")
            else:
                # Highlight User -> Orchestrator edge while running
                st.session_state.active_node = "orchestrator_agent"
                st.session_state.visited_edges = ["USER->orchestrator_agent"]
                st.session_state.feed.append((now(), "USER", prompt))
                render_feed(feed_box)

                result = orchestrator.run(prompt)

                # Update visited edges based on what ran
                if result.get("invoice"):
                    st.session_state.visited_edges.append("orchestrator_agent->it_agent")
                if result.get("finance_decision") is not None:
                    st.session_state.visited_edges.append("orchestrator_agent->finance_agent")
                if result.get("status") == "blocked":
                    st.session_state.visited_edges.append("finance_agent->HUMAN")
                    st.session_state.active_node = "BLOCKED"
                elif result.get("status") == "approved":
                    st.session_state.active_node = None
                else:
                    st.session_state.active_node = None

                for entry in result["logs"]:
                    time.sleep(THINK_SECONDS)
                    label = SPEAKER_LABELS.get(entry["speaker"], "SYSTEM")
                    st.session_state.feed.append((now(), label, entry["message"]))
                    render_feed(feed_box)

                result["ts"] = now()
                st.session_state.run_history.append(result)

                if result.get("invoice"):
                    inv = result["invoice"]
                    st.session_state.tasks.append({
                        "title": f"{inv['quantity']} x {inv['model']}",
                        "owner": "Orchestrator",
                        "stage": "Done" if result["status"] == "approved" else "Awaiting Approval",
                        "trace": result.get("trace", []),
                        "approval_id": result.get("approval_id"),
                    })

                # The approval-request log line now comes from result["logs"] directly
                # (orchestrator.run() calls log() not logger.info()), so no workaround needed.

                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Audit Log
# ══════════════════════════════════════════════════════════════════════════════
with tab_audit:
    st.markdown('<div class="section-label">Audit Log</div>', unsafe_allow_html=True)
    rows = build_audit_rows()
    if not rows:
        st.info("No actions recorded yet. Run a request from the Task Board tab.")
    else:
        import pandas as pd
        df = pd.DataFrame(rows, columns=[
            "timestamp", "agent", "tool", "amount", "outcome",
            "approver", "approval_id", "model", "quantity",
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # CSV download
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=df.columns.tolist())
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            label="Download CSV",
            data=buf.getvalue(),
            file_name=f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=False,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Policy & Guardrails
# ══════════════════════════════════════════════════════════════════════════════
with tab_policy:
    st.markdown('<div class="section-label">Policy & Guardrails</div>', unsafe_allow_html=True)
    st.caption("Rules are derived directly from each agent's instructions and tool bindings — not hard-coded.")

    for rule in policy_rules():
        with st.expander(f"{rule['agent']}  —  tools: {', '.join(rule['tools']) or 'none'}"):
            # Split instruction sentences into bullet points for readability
            instructions = rule["instructions"]
            sentences = [s.strip() for s in instructions.replace("; ", ".\n").split("\n") if s.strip()]
            for sentence in sentences:
                st.markdown(
                    f'<div class="policy-rule">{html.escape(sentence)}</div>',
                    unsafe_allow_html=True,
                )
            if rule["tools"]:
                st.markdown(
                    f'<div class="policy-rule" style="border-left-color:{C["success"]}">'
                    f'Bound tools: {", ".join(rule["tools"])}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
