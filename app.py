from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import List

import pandas as pd
import streamlit as st

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
        padding-top: 1.5rem;
        padding-bottom: 1.25rem;
    }
    .hero {
        border: 1px solid #E5E7EB;
        border-radius: 14px;
        padding: 1rem 1.25rem;
        background: linear-gradient(120deg, #F8FAFC 0%, #EEF2FF 100%);
        margin-bottom: 1rem;
    }
    .kpi {
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        background: #FFFFFF;
        padding: 0.85rem 0.9rem;
        min-height: 92px;
    }
    .kpi-title {
        color: #6B7280;
        font-size: 0.86rem;
        margin-bottom: 0.2rem;
    }
    .kpi-value {
        color: #111827;
        font-size: 1.4rem;
        font-weight: 700;
        line-height: 1.2;
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
            Upload one or more bank statement PDFs, parse transactions, and export a formatted
            Excel workpaper for forensic accounting review.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Workflow")
    st.markdown(
        "1. Upload statement PDFs\n"
        "2. Review parsed transactions\n"
        "3. Download Excel workpaper"
    )
    include_raw_text = st.checkbox("Include raw extracted text tab", value=True)
    large_txn_threshold = st.number_input(
        "Large transaction threshold ($)",
        min_value=100.0,
        value=1000.0,
        step=100.0,
    )

uploads = st.file_uploader(
    "Statement PDF files",
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
statement_count = len(results)
tx_count = int(len(all_transactions))
high_risk_count = int((all_transactions["risk_level"] == "high").sum())
avg_risk_score = float(all_transactions["risk_score"].fillna(0).mean()) if not all_transactions.empty else 0.0

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-title">Statements Parsed</div>
            <div class="kpi-value">{statement_count}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-title">Transactions</div>
            <div class="kpi-value">{tx_count}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-title">Total Debits</div>
            <div class="kpi-value">${total_debits:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col4:
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-title">Total Credits</div>
            <div class="kpi-value">${total_credits:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col5:
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-title">High-Risk Transactions</div>
            <div class="kpi-value">{high_risk_count}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("")
left, right = st.columns([2, 1])

with left:
    st.subheader("Transaction Preview")
    preview_cols = [
        "statement_id",
        "bank_format",
        "txn_date",
        "description",
        "txn_category",
        "debit",
        "credit",
        "risk_score",
        "risk_level",
        "running_balance",
        "check_number",
    ]
    st.dataframe(
        all_transactions[preview_cols].sort_values(["risk_score", "txn_date"], ascending=[False, True]),
        use_container_width=True,
        hide_index=True,
    )

with right:
    st.subheader("Risk Profile")
    risk_dist = (
        all_transactions["risk_level"]
        .value_counts(dropna=False)
        .rename_axis("risk_level")
        .reset_index(name="count")
    )
    st.dataframe(risk_dist, use_container_width=True, hide_index=True)
    st.caption(f"Average risk score: **{avg_risk_score:.1f} / 100**")

    st.subheader("Top Categories")
    category_dist = (
        all_transactions["txn_category"]
        .value_counts(dropna=False)
        .rename_axis("txn_category")
        .reset_index(name="count")
        .head(8)
    )
    st.dataframe(category_dist, use_container_width=True, hide_index=True)

    st.subheader("Review Flags")
    if all_flags.empty:
        st.success("No automated flags raised.")
    else:
        st.dataframe(
            all_flags[["flag_type", "severity", "message", "txn_date", "amount"]].head(25),
            use_container_width=True,
            hide_index=True,
        )

workpaper_bytes = build_workpaper(
    transactions=all_transactions,
    flags=all_flags,
    raw_text=all_raw if include_raw_text else pd.DataFrame(),
    parsed_at=datetime.now(),
)

st.download_button(
    label="Download Formatted Workpaper (.xlsx)",
    data=BytesIO(workpaper_bytes).getvalue(),
    file_name=f"forensic_workpaper_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
