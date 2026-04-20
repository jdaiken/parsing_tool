from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import List

import pandas as pd
import streamlit as st

from financial_statements import build_financial_statements
from statement_parser import ParseResult, parse_statement
from template_manager import delete_template, extract_preview_text, load_templates, save_template
from workpaper_export import build_workpaper

st.set_page_config(page_title="Statement Workpaper Parser", page_icon=":bar_chart:", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 1.2rem;}
    .hero {border: 1px solid #E5E7EB; border-radius: 14px; padding: 1rem 1.2rem;
           background: linear-gradient(120deg, #F8FAFC 0%, #EEF2FF 100%); margin-bottom: 1rem;}
    .guide {border: 1px solid #D1D5DB; border-radius: 12px; padding: 0.75rem 0.85rem;
            background: #F9FAFB; margin: 0.6rem 0;}
    .section-card {border: 1px solid #E5E7EB; border-radius: 12px; padding: 0.75rem 0.9rem; background: #FFFFFF;}
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div class="hero">
      <h2 style="margin:0; color:#111827;">Bank Statement to Forensic Workpaper</h2>
      <p style="margin:0.4rem 0 0 0; color:#374151;">
        Upload statements, review dashboards, reconcile balances, and export workpapers.
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
    return {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}.get(str(level).lower(), "⚪ Unknown")


def _severity_badge(level: str) -> str:
    return {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}.get(str(level).lower(), "⚪ Unrated")


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
    rows = []
    for statement_id, grp in transactions.groupby("statement_id", dropna=False):
        ordered = grp.sort_values(["txn_date", "source_page", "source_line"]).copy()
        credits = float(pd.to_numeric(ordered["credit"], errors="coerce").fillna(0).sum())
        debits = float(pd.to_numeric(ordered["debit"], errors="coerce").fillna(0).sum())
        running = pd.to_numeric(ordered.get("running_balance"), errors="coerce").dropna()
        beginning_balance = None
        ending_balance = None
        expected_ending = None
        difference = None
        status = "Needs Review"
        notes = "No running balance found; manual reconciliation required."
        if not running.empty:
            first_idx = running.index[0]
            first_row = ordered.loc[first_idx]
            first_credit_raw = pd.to_numeric(first_row.get("credit"), errors="coerce")
            first_debit_raw = pd.to_numeric(first_row.get("debit"), errors="coerce")
            first_credit = 0.0 if pd.isna(first_credit_raw) else float(first_credit_raw)
            first_debit = 0.0 if pd.isna(first_debit_raw) else float(first_debit_raw)
            beginning_balance = float(running.iloc[0]) - first_credit + first_debit
            ending_balance = float(running.iloc[-1])
            expected_ending = beginning_balance + credits - debits
            difference = ending_balance - expected_ending
            if abs(difference) <= 0.01:
                status = "Reconciled"
                notes = "Expected ending balance agrees to statement running balance."
            else:
                status = "Variance"
                notes = "Expected ending balance differs from statement running balance."
        rows.append(
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
    return pd.DataFrame(rows).sort_values("statement_id").reset_index(drop=True)


with st.sidebar:
    st.subheader("Guided Workflow")
    st.markdown('<div class="guide">1) Upload PDFs<br>2) Review dashboard<br>3) Export files</div>', unsafe_allow_html=True)
    include_raw_text = st.checkbox("Include raw extracted text tab", value=True)
    large_txn_threshold = st.number_input("Large transaction threshold ($)", min_value=100.0, value=1000.0, step=100.0)
    st.caption(f"Custom templates loaded: {len(load_templates())}")

uploads = st.file_uploader("Upload statement PDF files", type=["pdf"], accept_multiple_files=True)
has_uploads = bool(uploads)

tx_columns = [
    "statement_id",
    "bank_format",
    "account_number",
    "statement_date",
    "txn_date",
    "txn_date_raw",
    "description",
    "transaction_type",
    "direction",
    "amount",
    "debit",
    "credit",
    "running_balance",
    "check_number",
    "source_page",
    "source_line",
    "txn_category",
    "risk_score",
    "risk_level",
    "risk_reasons",
]
flag_columns = ["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"]

all_transactions = pd.DataFrame(columns=tx_columns)
all_flags = pd.DataFrame(columns=flag_columns)
all_raw = pd.DataFrame(columns=["statement_id", "page", "text"])
results: List[ParseResult] = []

if has_uploads:
    parse_errors: List[str] = []
    for uploaded_file in uploads:
        try:
            result = parse_statement(uploaded_file.name, uploaded_file.getvalue(), large_txn_threshold)
            results.append(result)
        except Exception as exc:  # pragma: no cover
            parse_errors.append(f"{uploaded_file.name}: {exc}")
    if parse_errors:
        st.error("Some files could not be parsed:")
        for err in parse_errors:
            st.write(f"- {err}")
    if results:
        all_transactions = pd.concat([r.transactions for r in results], ignore_index=True)
        all_flags = pd.concat([r.flags for r in results], ignore_index=True)
        all_raw = pd.concat([r.raw_text for r in results], ignore_index=True)

total_debits = float(pd.to_numeric(all_transactions.get("debit"), errors="coerce").fillna(0).sum()) if not all_transactions.empty else 0.0
total_credits = float(pd.to_numeric(all_transactions.get("credit"), errors="coerce").fillna(0).sum()) if not all_transactions.empty else 0.0
net_flow = total_credits - total_debits
statement_count = len(results)
tx_count = len(all_transactions)
high_risk_count = int((all_transactions.get("risk_level") == "high").sum()) if not all_transactions.empty else 0
medium_risk_count = int((all_transactions.get("risk_level") == "medium").sum()) if not all_transactions.empty else 0
avg_risk_score = float(pd.to_numeric(all_transactions.get("risk_score"), errors="coerce").fillna(0).mean()) if not all_transactions.empty else 0.0
flag_count = len(all_flags)
reconciliation_df = _build_reconciliation_table(all_transactions)

overview_tab, transactions_tab, risk_tab, reconciliation_tab, export_tab, template_tab = st.tabs(
    ["Overview", "Transactions", "Risk and Flags", "Reconciliation", "Export Files", "Template Manager"]
)

with overview_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload at least one statement to view dashboard metrics.")
    else:
        k1, k2, k3 = st.columns(3)
        k1.metric("Statements", statement_count)
        k2.metric("Transactions", tx_count)
        k3.metric("Avg Risk", f"{avg_risk_score:.1f}/100")
        k4, k5, k6 = st.columns(3)
        k4.metric("Total Debits", f"${total_debits:,.2f}")
        k5.metric("Total Credits", f"${total_credits:,.2f}")
        k6.metric("Net Flow", f"${net_flow:,.2f}")
        c1, c2 = st.columns(2)
        category_chart = all_transactions["txn_category"].value_counts().rename_axis("category").reset_index(name="count")
        category_chart["category"] = category_chart["category"].map(_display_category_name)
        c1.markdown("#### Categories")
        c1.bar_chart(category_chart.set_index("category"))
        risk_chart = all_transactions["risk_level"].value_counts().reindex(["high", "medium", "low"], fill_value=0).rename_axis("risk").to_frame("count")
        c2.markdown("#### Risk Levels")
        c2.bar_chart(risk_chart)

with transactions_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload statements to review transactions.")
    else:
        f1, f2, f3 = st.columns([1.2, 1.1, 1.3])
        statement_options = sorted(all_transactions["statement_id"].dropna().unique().tolist())
        selected_statements = f1.multiselect("Statement", statement_options, default=statement_options)
        selected_risks = f2.multiselect("Risk Level", ["high", "medium", "low"], default=["high", "medium", "low"])
        search_term = f3.text_input("Search description", placeholder="ATM, CHECK, DEPOSIT")
        filtered = all_transactions.copy()
        if selected_statements:
            filtered = filtered[filtered["statement_id"].isin(selected_statements)]
        if selected_risks:
            filtered = filtered[filtered["risk_level"].isin(selected_risks)]
        if search_term:
            filtered = filtered[filtered["description"].str.contains(search_term, case=False, na=False)]
        filtered = filtered.sort_values(["risk_score", "txn_date"], ascending=[False, True])
        filtered["txn_category"] = filtered["txn_category"].map(_display_category_name)
        filtered["risk_badge"] = filtered["risk_level"].map(_risk_badge)
        st.dataframe(
            filtered[["txn_date", "statement_id", "description", "txn_category", "debit", "credit", "risk_score", "risk_badge"]],
            use_container_width=True,
            hide_index=True,
            height=460,
        )

with risk_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload statements to view risk and flags.")
    else:
        r1, r2, r3 = st.columns(3)
        r1.metric("High Risk", high_risk_count)
        r2.metric("Medium Risk", medium_risk_count)
        r3.metric("Flags", flag_count)
        high_risk = all_transactions[all_transactions["risk_level"].isin(["high", "medium"])].copy()
        high_risk["risk_badge"] = high_risk["risk_level"].map(_risk_badge)
        st.dataframe(high_risk[["txn_date", "description", "amount", "risk_score", "risk_badge", "risk_reasons"]].head(50), use_container_width=True, hide_index=True)
        if not all_flags.empty:
            flags_view = all_flags.copy()
            flags_view["severity_badge"] = flags_view["severity"].map(_severity_badge)
            st.dataframe(flags_view[["flag_type", "severity_badge", "message", "txn_date", "amount"]], use_container_width=True, hide_index=True)

with reconciliation_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload statements to run reconciliation.")
    else:
        rec = reconciliation_df.copy()
        rec["status_badge"] = rec["status"].map(lambda s: "🟢 Reconciled" if s == "Reconciled" else ("🔴 Variance" if s == "Variance" else "🟠 Needs Review"))
        st.dataframe(
            rec[["statement_id", "beginning_balance", "total_credits", "total_debits", "expected_ending_balance", "ending_balance", "reconciliation_difference", "status_badge", "notes"]],
            use_container_width=True,
            hide_index=True,
            height=360,
        )

with export_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload statements to export workbooks.")
    else:
        workpaper_bytes = build_workpaper(all_transactions, all_flags, all_raw if include_raw_text else pd.DataFrame(), datetime.now())
        financial_bytes = build_financial_statements(all_transactions, reconciliation_df, datetime.now())
        d1, d2 = st.columns(2)
        d1.download_button("Download Forensic Workpaper (.xlsx)", data=BytesIO(workpaper_bytes).getvalue(), file_name=f"forensic_workpaper_{datetime.now():%Y%m%d_%H%M%S}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        d2.download_button("Download Financial Statements (.xlsx)", data=BytesIO(financial_bytes).getvalue(), file_name=f"financial_statements_{datetime.now():%Y%m%d_%H%M%S}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with template_tab:
    st.markdown("#### Hybrid System: Template Manager")
    st.markdown(
        '<div class="section-card">Nontechnical onboarding: add a new statement format by keywords + parser style. No code changes needed for most new formats.</div>',
        unsafe_allow_html=True,
    )
    templates = load_templates()
    if templates:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Template": t["template_name"],
                        "Parse Style": t["parse_style"],
                        "Default Direction": t["default_direction"],
                        "Detection Keywords": ", ".join(t["detection_keywords"]),
                    }
                    for t in templates
                ]
            ),
            use_container_width=True,
            hide_index=True,
            height=220,
        )
    else:
        st.info("No custom templates saved yet.")

    st.markdown("##### Add or Update Template")
    sample_upload = st.file_uploader("Optional: Upload sample statement for preview", type=["pdf"], key="template_sample_upload")
    if sample_upload is not None:
        st.text_area("Extracted preview text", value=extract_preview_text(sample_upload.getvalue()), height=180)

    with st.form("template_form", clear_on_submit=False):
        template_name = st.text_input("Template name", placeholder="Example: First National Monthly")
        detection_keywords_text = st.text_input("Detection keywords (comma-separated)", placeholder="first national, account summary")
        parse_style = st.selectbox(
            "Parse style",
            options=["slash_leading_amount_balance", "date_dash_last_amount"],
            help="Use slash style for lines beginning with MM/DD/YYYY. Use dash style for MM-DD dates inside lines.",
        )
        default_direction = st.selectbox("Default transaction direction", options=["debit", "credit"])
        credit_keywords_text = st.text_input("Credit keywords (comma-separated)", value="deposit,credit,refund,reversal")
        submitted = st.form_submit_button("Save template")
    if submitted:
        payload = {
            "template_name": template_name,
            "detection_keywords": [part.strip() for part in detection_keywords_text.split(",") if part.strip()],
            "parse_style": parse_style,
            "default_direction": default_direction,
            "credit_keywords": [part.strip() for part in credit_keywords_text.split(",") if part.strip()],
        }
        ok, msg = save_template(payload)
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

    if templates:
        st.markdown("##### Delete Template")
        delete_name = st.selectbox("Choose template to delete", [t["template_name"] for t in templates], key="delete_template")
        if st.button("Delete selected template"):
            ok, msg = delete_template(delete_name)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
