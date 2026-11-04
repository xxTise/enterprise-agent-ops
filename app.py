"""Dashboard: Kanban board (left) + Live Agent Feed terminal (right), driven by the Orchestrator."""

import html
import json
import time
from datetime import datetime

import streamlit as st

from agents import orchestrator
from agents.approvals import list_approvals, resolve_approval
from tools.finance_tools import BUDGET_FILE

st.set_page_config(page_title="Enterprise Ops Orchestrator", layout="wide")

STAGES = ["Backlog", "In Progress", "Awaiting Approval", "Done"]
DEMO_START_SPEND = 420000
THINK_SECONDS = 0.5

# Agent name from orchestrator.run() logs -> label shown in the feed (also its CSS class).
SPEAKER_LABELS = {
    orchestrator.orchestrator_agent.name: "ORCH",
    orchestrator.it_agent.name: "IT",
    orchestrator.finance_agent.name: "FINANCE",
}


def now():
    return datetime.now().strftime("%H:%M:%S")


def load_budget():
    return json.loads(BUDGET_FILE.read_text())


def reset_budget():
    budget = load_budget()
    budget["current_spend"] = DEMO_START_SPEND
    BUDGET_FILE.write_text(json.dumps(budget, indent=2) + "\n")


def reset_approvals():
    from agents.approvals import APPROVALS_FILE
    APPROVALS_FILE.write_text("[]\n")


if "tasks" not in st.session_state:
    st.session_state.tasks = [
        {"title": "Onboard 12 sales hires (Chicago)", "owner": "IT Agent", "stage": "Backlog"},
        {"title": "Provision laptops: Eng team", "owner": "IT Agent", "stage": "In Progress"},
        {"title": "Q4 hardware invoice review", "owner": "Finance Agent", "stage": "Awaiting Approval"},
        {"title": "Support desk refresh (5 units)", "owner": "Finance Agent", "stage": "Done"},
    ]
if "feed" not in st.session_state:
    st.session_state.feed = [
        (now(), "SYSTEM", "Orchestrator online. Agents registered: orchestrator_agent, it_agent, finance_agent"),
        (now(), "IT", "Standing by for hardware requests."),
        (now(), "FINANCE", "Budget cap loaded: $500,000."),
    ]

st.markdown(
    """
    <style>
    .terminal {background:#0d1117; color:#c9d1d9; font-family:ui-monospace,Menlo,monospace;
               font-size:13px; padding:14px; border-radius:8px; height:460px; overflow-y:auto;
               display:flex; flex-direction:column-reverse;}
    .terminal .ts {color:#6e7681;} .terminal .IT {color:#58a6ff;}
    .terminal .FINANCE {color:#3fb950;} .terminal .SYSTEM {color:#d29922;}
    .terminal .ORCH {color:#bc8cff;} .terminal .USER {color:#e6edf3; font-weight:600;}
    .terminal .BLOCKED {color:#f85149;} .terminal .HUMAN {color:#f0a500; font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)


def render_feed(placeholder):
    lines = []
    for ts, who, msg in st.session_state.feed:
        lowered = msg.lower()
        cls = "BLOCKED" if ("blocked" in lowered or "result: error" in lowered) else who
        lines.append(
            f'<span class="ts">[{ts}]</span> <span class="{cls}">{who}</span> &gt; {html.escape(msg).replace("$", "&#36;")}'
        )
    # column-reverse keeps the scroll pinned to the newest line; the inner div keeps line order.
    placeholder.markdown(f'<div class="terminal"><div>{"<br>".join(lines)}</div></div>',
                         unsafe_allow_html=True)


budget = load_budget()
title_col, reset_col = st.columns([5, 1], vertical_alignment="bottom")
with title_col:
    st.title("Enterprise Expansion & Ops Orchestrator")
    # "\$" stops Streamlit markdown from treating paired dollar signs as LaTeX.
    st.caption(
        f"Agents built on IBM watsonx Orchestrate ADK · Budget: "
        f"\\${budget['current_spend']:,} of \\${budget['total_cap']:,} spent "
        f"(\\${budget['total_cap'] - budget['current_spend']:,} remaining)"
    )
with reset_col:
    if st.button("Reset Demo Budget", use_container_width=True):
        reset_budget()
        reset_approvals()
        st.session_state.feed.append((now(), "SYSTEM", f"Demo budget reset: current_spend = ${DEMO_START_SPEND:,}"))
        st.rerun()

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Task Board")

    # ── Pending approvals panel ───────────────────────────────────────────────
    pending = list_approvals(status="pending")
    if pending:
        st.markdown("**Awaiting Human Approval**")
        for appr in pending:
            inv = appr["invoice"]
            total = inv["total_invoice"]
            budget_now = load_budget()
            over = total - (budget_now["total_cap"] - budget_now["current_spend"])
            with st.container(border=True):
                st.markdown(
                    f"**{inv['quantity']}× {inv['model']}**  \n"
                    f"Total: **${total:,}** &nbsp;|&nbsp; "
                    f"<span style='color:#f85149'>Over cap by ${max(over,0):,.2f}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Approval ID: `{appr['id']}` · Prompt: _{appr['prompt']}_")
                col_a, col_r = st.columns(2)
                with col_a:
                    if st.button("✅ Approve", key=f"approve_{appr['id']}", use_container_width=True):
                        resolve_approval(appr["id"], "approved", "dashboard_user")
                        st.session_state.feed.append(
                            (now(), "HUMAN",
                             f"APPROVED override: {inv['quantity']}× {inv['model']} (${total:,}) — "
                             f"Approval {appr['id']}")
                        )
                        # Move the matching Awaiting Approval task card to Done
                        for t in st.session_state.tasks:
                            if (t["stage"] == "Awaiting Approval"
                                    and inv["model"] in t["title"]
                                    and str(inv["quantity"]) in t["title"]):
                                t["stage"] = "Done"
                                break
                        st.rerun()
                with col_r:
                    if st.button("❌ Reject", key=f"reject_{appr['id']}", use_container_width=True):
                        resolve_approval(appr["id"], "rejected", "dashboard_user")
                        st.session_state.feed.append(
                            (now(), "HUMAN",
                             f"REJECTED: {inv['quantity']}× {inv['model']} (${total:,}) — "
                             f"Approval {appr['id']}")
                        )
                        st.rerun()

        st.divider()

    # ── Kanban board ──────────────────────────────────────────────────────────
    for col, stage in zip(st.columns(len(STAGES)), STAGES):
        with col:
            items = [t for t in st.session_state.tasks if t["stage"] == stage]
            st.markdown(f"**{stage}** · {len(items)}")
            for t in items:
                with st.container(border=True):
                    st.markdown(f"**{t['title']}**")
                    st.caption(t["owner"])

    # Show resolved (non-pending) approvals in a collapsed section
    resolved = list_approvals()
    resolved = [a for a in resolved if a["status"] != "pending"]
    if resolved:
        with st.expander(f"Resolved Approvals ({len(resolved)})"):
            for appr in resolved:
                inv = appr["invoice"]
                badge = "✅" if appr["status"] == "approved" else "❌"
                st.markdown(
                    f"{badge} **{inv['quantity']}× {inv['model']}** — ${inv['total_invoice']:,} "
                    f"· _{appr['status'].upper()}_ by `{appr.get('approver','?')}` "
                    f"· ID `{appr['id']}`"
                )

with right:
    st.subheader("Live Agent Feed")
    feed_box = st.empty()
    render_feed(feed_box)

    with st.form("simulate", clear_on_submit=True):
        st.markdown("**Send a request to the Orchestrator**")
        prompt = st.text_input("Request", placeholder="Order 10 ThinkPads", label_visibility="collapsed")
        submitted = st.form_submit_button("Run")

    if submitted:
        if not prompt.strip():
            st.warning("Type a request first, e.g. \"Order 10 ThinkPads\".")
        else:
            st.session_state.feed.append((now(), "USER", prompt))
            render_feed(feed_box)
            result = orchestrator.run(prompt)
            for entry in result["logs"]:
                time.sleep(THINK_SECONDS)
                label = SPEAKER_LABELS.get(entry["speaker"], "SYSTEM")
                st.session_state.feed.append((now(), label, entry["message"]))
                render_feed(feed_box)

            if result["invoice"]:
                invoice = result["invoice"]
                st.session_state.tasks.append({
                    "title": f"{invoice['quantity']}× {invoice['model']}",
                    "owner": "Orchestrator",
                    "stage": "Done" if result["status"] == "approved" else "Awaiting Approval",
                })

            if result.get("approval_id"):
                st.session_state.feed.append(
                    (now(), "SYSTEM",
                     f"Approval request {result['approval_id']} opened for human review.")
                )

            # Rerun so the Kanban board and budget caption pick up the new state.
            st.rerun()
