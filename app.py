from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import List

import pandas as pd
import streamlit as st

from financial_statements import build_financial_statements
from statement_parser import ParseResult, parse_statement
from workpaper_export import build_workpaper


st.set_page_config(
    page_title="Statement Workpaper Parser",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1.2rem;
    }
    .hero {
        border: 1px solid #E5E7EB;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        background: linear-gradient(120deg, #F8FAFC 0%, #EEF2FF 100%);
        margin-bottom: 1rem;
    }
    .guide {
        border: 1px solid #D1D5DB;
        border-radius: 12px;
        padding: 0.75rem 0.85rem;
        background: #F9FAFB;
        margin: 0.6rem 0;
    }
    .section-card {
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 0.75rem 0.9rem;
        background: #FFFFFF;
    }
    .subtle-note {
        color: #6B7280;
        font-size: 0.88rem;
        margin-top: 0.15rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h2 style="margin:0; color:#111827;">Bank Statement to Forensic Workpaper</h2>
        <p style="margin:0.4rem 0 0 0; color:#374151;">
            Upload one or more bank statement PDFs, review plain-language dashboards,
            then export a formatted Excel workpaper for forensic analysis.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


def _display_category_name(cat: str) -> str:
    labels = {
        "deposit": "Deposit / Credit",
        "check": "Check",
        "atm_withdrawal": "ATM Withdrawal",
        "card_purchase": "Card Purchase",
        "fee_charge": "Fee / Service Charge",
        "ach_transfer": "ACH / Transfer",
        "loan_payment": "Loan Payment",
        "other_credit": "Other Credit",
        "other_debit": "Other Debit",
    }
    return labels.get(cat, cat.replace("_", " ").title())


def _risk_badge(level: str) -> str:
    lookup = {
        "high": "🔴 High",
        "medium": "🟠 Medium",
        "low": "🟢 Low",
    }
    return lookup.get(str(level).lower(), "⚪ Unknown")


def _severity_badge(level: str) -> str:
    lookup = {
        "high": "🔴 High",
        "medium": "🟠 Medium",
        "low": "🟢 Low",
    }
    return lookup.get(str(level).lower(), "⚪ Unrated")


def _build_reconciliation_table(transactions: pd.DataFrame) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(
            columns=[
                "statement_id",
                "beginning_balance",
                "total_credits",
                "total_debits",
                "expected_ending_balance",
                "ending_balance",
                "reconciliation_difference",
                "status",
                "notes",
            ]
        )

    rec_rows = []
    grouped = transactions.groupby("statement_id", dropna=False)
    for statement_id, grp in grouped:
        ordered = grp.sort_values(["txn_date", "source_page", "source_line"]).copy()
        credits = float(pd.to_numeric(ordered["credit"], errors="coerce").fillna(0).sum())
        debits = float(pd.to_numeric(ordered["debit"], errors="coerce").fillna(0).sum())
        running = pd.to_numeric(ordered.get("running_balance"), errors="coerce").dropna()

        beginning_balance = None
        ending_balance = None
        expected_ending = None
        difference = None
        status = "Needs Review"
        notes = "No running balance found on parsed rows; manual reconciliation required."

        if not running.empty:
            first_idx = running.index[0]
            last_idx = running.index[-1]
            first_row = ordered.loc[first_idx]
            last_row = ordered.loc[last_idx]
            first_balance = float(running.iloc[0])
            ending_balance = float(running.iloc[-1])

            first_credit_raw = pd.to_numeric(first_row.get("credit"), errors="coerce")
            first_debit_raw = pd.to_numeric(first_row.get("debit"), errors="coerce")
            first_credit = float(0.0 if pd.isna(first_credit_raw) else first_credit_raw)
            first_debit = float(0.0 if pd.isna(first_debit_raw) else first_debit_raw)
            beginning_balance = first_balance - first_credit + first_debit
            expected_ending = beginning_balance + credits - debits
            difference = ending_balance - expected_ending

            if abs(difference) <= 0.01:
                status = "Reconciled"
                notes = "Calculated ending balance agrees to statement running balance."
            else:
                status = "Variance"
                notes = "Calculated ending balance differs from statement running balance."

        rec_rows.append(
            {
                "statement_id": statement_id,
                "beginning_balance": beginning_balance,
                "total_credits": credits,
                "total_debits": debits,
                "expected_ending_balance": expected_ending,
                "ending_balance": ending_balance,
                "reconciliation_difference": difference,
                "status": status,
                "notes": notes,
            }
        )

    return pd.DataFrame(rec_rows).sort_values("statement_id").reset_index(drop=True)


with st.sidebar:
    st.subheader("Guided Workflow")
    st.markdown('<div class="guide">1) Upload PDFs<br>2) Review dashboard<br>3) Export workpaper</div>', unsafe_allow_html=True)
    st.caption("Use the tabs in the main panel for an easy review flow.")

    include_raw_text = st.checkbox("Include raw extracted text tab", value=True)
    large_txn_threshold = st.number_input(
        "Large transaction threshold ($)",
        min_value=100.0,
        value=1000.0,
        step=100.0,
        help="Used by risk scoring and large transaction flags.",
    )

uploads = st.file_uploader(
    "Upload statement PDF files",
    type=["pdf"],
    accept_multiple_files=True,
    help="You can upload multiple statements for one combined workpaper.",
)

if not uploads:
    st.info("Upload at least one PDF statement to begin.")
    st.stop()

results: List[ParseResult] = []
parse_errors: List[str] = []

for uploaded_file in uploads:
    try:
        file_bytes = uploaded_file.getvalue()
        result = parse_statement(uploaded_file.name, file_bytes, large_txn_threshold)
        results.append(result)
    except Exception as exc:  # pragma: no cover - defensive for UI
        parse_errors.append(f"{uploaded_file.name}: {exc}")

if parse_errors:
    st.error("Some files could not be parsed:")
    for err in parse_errors:
        st.write(f"- {err}")

if not results:
    st.warning("No statements were parsed successfully.")
    st.stop()

all_transactions = pd.concat([r.transactions for r in results], ignore_index=True)
all_flags = pd.concat([r.flags for r in results], ignore_index=True)
all_raw = pd.concat([r.raw_text for r in results], ignore_index=True)

total_debits = float(all_transactions["debit"].fillna(0).sum())
total_credits = float(all_transactions["credit"].fillna(0).sum())
net_flow = total_credits - total_debits
statement_count = len(results)
tx_count = int(len(all_transactions))
high_risk_count = int((all_transactions["risk_level"] == "high").sum())
medium_risk_count = int((all_transactions["risk_level"] == "medium").sum())
avg_risk_score = float(all_transactions["risk_score"].fillna(0).mean()) if not all_transactions.empty else 0.0
flag_count = int(len(all_flags))

reconciliation_df = _build_reconciliation_table(all_transactions)
reconciled_count = int((reconciliation_df["status"] == "Reconciled").sum()) if not reconciliation_df.empty else 0
variance_count = int((reconciliation_df["status"] == "Variance").sum()) if not reconciliation_df.empty else 0

overview_tab, transactions_tab, risk_tab, reconciliation_tab, export_tab = st.tabs(
    ["Overview", "Transactions", "Risk and Flags", "Reconciliation", "Export Files"]
)

with overview_tab:
    st.markdown("#### Snapshot")
    k1, k2, k3 = st.columns(3)
    k1.metric("Statements", statement_count)
    k2.metric("Transactions", tx_count)
    k3.metric("Total Debits", f"${total_debits:,.2f}")
    k4, k5, k6 = st.columns(3)
    k4.metric("Total Credits", f"${total_credits:,.2f}")
    k5.metric("Net Flow", f"${net_flow:,.2f}")
    k6.metric("Avg Risk Score", f"{avg_risk_score:.1f}/100")

    if high_risk_count > 0 or avg_risk_score >= 45:
        overall_signal = "Elevated"
        signal_icon = "🔴"
    elif medium_risk_count > 0 or avg_risk_score >= 25:
        overall_signal = "Moderate"
        signal_icon = "🟠"
    else:
        overall_signal = "Low"
        signal_icon = "🟢"

    largest_txn = float(all_transactions["amount"].fillna(0).max()) if not all_transactions.empty else 0.0
    top_category_raw = (
        all_transactions["txn_category"].value_counts().index[0] if not all_transactions.empty else "other_debit"
    )
    top_category = _display_category_name(str(top_category_raw))
    high_risk_share = (high_risk_count / tx_count * 100.0) if tx_count else 0.0

    st.markdown("#### Executive Summary")
    st.markdown(
        f"""
        <div class="section-card">
            <p style="margin:0 0 0.45rem 0;"><strong>{signal_icon} Overall Risk Signal:</strong> {overall_signal}</p>
            <p style="margin:0 0 0.45rem 0;"><strong>Key points for leadership:</strong></p>
            <ul style="margin:0.2rem 0 0.1rem 1.1rem; padding:0;">
                <li>{tx_count} transactions parsed across {statement_count} statement(s).</li>
                <li>{high_risk_count} high-risk item(s) ({high_risk_share:.1f}% of total transactions).</li>
                <li>Largest single transaction observed: ${largest_txn:,.2f}.</li>
                <li>Most common transaction class: {top_category}.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="subtle-note">Tip: Use the Transactions tab filters to narrow the list by statement, risk level, or keywords.</div>',
        unsafe_allow_html=True,
    )

    st.markdown("")
    chart_left, chart_right = st.columns([1, 1])
    with chart_left:
        st.markdown("#### Transaction Categories")
        category_chart = (
            all_transactions["txn_category"]
            .value_counts()
            .rename_axis("category")
            .reset_index(name="count")
        )
        category_chart["category"] = category_chart["category"].map(_display_category_name)
        st.bar_chart(category_chart.set_index("category"))

    with chart_right:
        st.markdown("#### Risk Levels")
        risk_chart = (
            all_transactions["risk_level"]
            .value_counts()
            .reindex(["high", "medium", "low"], fill_value=0)
            .rename_axis("risk_level")
            .reset_index(name="count")
        )
        st.bar_chart(risk_chart.set_index("risk_level"))

    st.markdown("#### Cash Flow Trend")
    trend_df = all_transactions.copy()
    trend_df["txn_date"] = pd.to_datetime(trend_df["txn_date"], errors="coerce")
    trend_df = trend_df.dropna(subset=["txn_date"])
    if trend_df.empty:
        st.info("No valid transaction dates available to plot a timeline.")
    else:
        trend_df["debit"] = trend_df["debit"].fillna(0.0)
        trend_df["credit"] = trend_df["credit"].fillna(0.0)
        trend_grouped = trend_df.groupby("txn_date", as_index=False)[["debit", "credit"]].sum()
        st.line_chart(trend_grouped.set_index("txn_date"))

with transactions_tab:
    st.markdown("#### Review and Filter Transactions")
    f1, f2, f3 = st.columns([1.2, 1.1, 1.3])
    statement_options = sorted(all_transactions["statement_id"].dropna().unique().tolist())
    with f1:
        selected_statements = st.multiselect("Statement", statement_options, default=statement_options)
    with f2:
        selected_risks = st.multiselect("Risk Level", ["high", "medium", "low"], default=["high", "medium", "low"])
    with f3:
        search_term = st.text_input("Search description", placeholder="e.g., ATM, CHECK, DEPOSIT")
    show_advanced = st.toggle("Show advanced columns (check number, running balance)", value=False)

    filtered = all_transactions.copy()
    if selected_statements:
        filtered = filtered[filtered["statement_id"].isin(selected_statements)]
    if selected_risks:
        filtered = filtered[filtered["risk_level"].isin(selected_risks)]
    if search_term:
        filtered = filtered[filtered["description"].str.contains(search_term, case=False, na=False)]

    display_cols = [
        "txn_date",
        "statement_id",
        "description",
        "txn_category",
        "debit",
        "credit",
        "risk_score",
        "risk_level",
        "check_number",
        "running_balance",
    ]
    filtered = filtered[display_cols].sort_values(["risk_score", "txn_date"], ascending=[False, True])
    filtered["txn_category"] = filtered["txn_category"].map(_display_category_name)
    filtered["risk_badge"] = filtered["risk_level"].map(_risk_badge)
    base_columns = [
        "txn_date",
        "statement_id",
        "description",
        "txn_category",
        "debit",
        "credit",
        "risk_score",
        "risk_badge",
    ]
    advanced_columns = ["check_number", "running_balance"]
    final_columns = base_columns + advanced_columns if show_advanced else base_columns
    filtered = filtered[final_columns]
    st.caption(f"Showing {len(filtered)} transaction(s)")
    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        height=460,
        column_config={
            "txn_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "statement_id": st.column_config.TextColumn("Statement", width="small"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "txn_category": st.column_config.TextColumn("Category", width="medium"),
            "debit": st.column_config.NumberColumn("Debit", format="$%,.2f"),
            "credit": st.column_config.NumberColumn("Credit", format="$%,.2f"),
            "running_balance": st.column_config.NumberColumn("Balance", format="$%,.2f"),
            "risk_score": st.column_config.ProgressColumn("Risk Score", min_value=0, max_value=100),
            "risk_badge": st.column_config.TextColumn("Risk Level"),
        },
    )

with risk_tab:
    r1, r2, r3 = st.columns(3)
    r1.metric("High Risk", high_risk_count)
    r2.metric("Medium Risk", medium_risk_count)
    r3.metric("Total Flags", flag_count)

    st.markdown("#### Highest Risk Transactions")
    high_risk_view = all_transactions[all_transactions["risk_level"].isin(["high", "medium"])].copy()
    if high_risk_view.empty:
        st.success("No medium/high risk items detected by the model.")
    else:
        high_risk_view = high_risk_view.sort_values("risk_score", ascending=False).head(40)
        high_risk_view["txn_category"] = high_risk_view["txn_category"].map(_display_category_name)
        high_risk_view["risk_badge"] = high_risk_view["risk_level"].map(_risk_badge)
        st.dataframe(
            high_risk_view[
                [
                    "txn_date",
                    "description",
                    "txn_category",
                    "amount",
                    "risk_score",
                    "risk_badge",
                    "risk_reasons",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            height=360,
            column_config={
                "txn_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                "description": st.column_config.TextColumn("Description", width="large"),
                "txn_category": st.column_config.TextColumn("Category", width="medium"),
                "amount": st.column_config.NumberColumn("Amount", format="$%,.2f"),
                "risk_score": st.column_config.ProgressColumn("Risk Score", min_value=0, max_value=100),
                "risk_badge": st.column_config.TextColumn("Risk Level"),
            },
        )

    st.markdown("#### Automated Review Flags")
    if all_flags.empty:
        st.success("No automated flags raised.")
    else:
        flags_view = all_flags[["flag_type", "severity", "message", "txn_date", "amount"]].sort_values("severity")
        flags_view["severity_badge"] = flags_view["severity"].map(_severity_badge)
        flags_view = flags_view[["flag_type", "severity_badge", "message", "txn_date", "amount"]]
        st.dataframe(
            flags_view,
            use_container_width=True,
            hide_index=True,
            height=300,
            column_config={
                "flag_type": st.column_config.TextColumn("Flag Type", width="medium"),
                "message": st.column_config.TextColumn("Message", width="large"),
                "amount": st.column_config.NumberColumn("Amount", format="$%,.2f"),
                "severity_badge": st.column_config.TextColumn("Severity"),
            },
        )

with reconciliation_tab:
    st.markdown("#### Statement Reconciliation")
    c1, c2, c3 = st.columns(3)
    c1.metric("Statements Reconciled", reconciled_count)
    c2.metric("Statements with Variance", variance_count)
    c3.metric("Total Statements", int(len(reconciliation_df)))

    st.markdown(
        '<div class="section-card">This reconciliation compares expected ending balance (beginning + credits - debits) to statement running balance when available.</div>',
        unsafe_allow_html=True,
    )

    if reconciliation_df.empty:
        st.info("No reconciliation data available.")
    else:
        rec_display = reconciliation_df.copy()
        rec_display["status_badge"] = rec_display["status"].map(
            lambda s: "🟢 Reconciled" if s == "Reconciled" else ("🔴 Variance" if s == "Variance" else "🟠 Needs Review")
        )
        rec_display = rec_display[
            [
                "statement_id",
                "beginning_balance",
                "total_credits",
                "total_debits",
                "expected_ending_balance",
                "ending_balance",
                "reconciliation_difference",
                "status_badge",
                "notes",
            ]
        ]
        st.dataframe(
            rec_display,
            use_container_width=True,
            hide_index=True,
            height=360,
            column_config={
                "statement_id": st.column_config.TextColumn("Statement", width="medium"),
                "beginning_balance": st.column_config.NumberColumn("Beginning", format="$%,.2f"),
                "total_credits": st.column_config.NumberColumn("Credits", format="$%,.2f"),
                "total_debits": st.column_config.NumberColumn("Debits", format="$%,.2f"),
                "expected_ending_balance": st.column_config.NumberColumn("Expected Ending", format="$%,.2f"),
                "ending_balance": st.column_config.NumberColumn("Statement Ending", format="$%,.2f"),
                "reconciliation_difference": st.column_config.NumberColumn("Difference", format="$%,.2f"),
                "status_badge": st.column_config.TextColumn("Status", width="small"),
                "notes": st.column_config.TextColumn("Notes", width="large"),
            },
        )

workpaper_bytes = build_workpaper(
    transactions=all_transactions,
    flags=all_flags,
    raw_text=all_raw if include_raw_text else pd.DataFrame(),
    parsed_at=datetime.now(),
)
financial_statements_bytes = build_financial_statements(
    transactions=all_transactions,
    reconciliation=reconciliation_df,
    parsed_at=datetime.now(),
)

with export_tab:
    st.markdown("#### Export Files")
    st.markdown(
        '<div class="section-card">Download your forensic workpaper and a separate management financial statements workbook.</div>',
        unsafe_allow_html=True,
    )
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            label="Download Forensic Workpaper (.xlsx)",
            data=BytesIO(workpaper_bytes).getvalue(),
            file_name=f"forensic_workpaper_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    with d2:
        st.download_button(
            label="Download Financial Statements (.xlsx)",
            data=BytesIO(financial_statements_bytes).getvalue(),
            file_name=f"financial_statements_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
