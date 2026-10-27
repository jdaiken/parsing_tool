"""
Streamlit front-end for Bank Statement Analyzer.

Upload bank statement PDFs, parse transactions, review risk/reconciliation
dashboards, export Excel workpapers, and manage custom bank-format templates.
"""

from __future__ import annotations

import sys
from datetime import datetime
from io import BytesIO
from typing import List

import pandas as pd
import streamlit as st

from auto_parser import CREDIT_WORDS
from financial_statements import build_financial_statements
from statement_parser import BUILT_IN_FORMAT_NAMES, ParseResult, analyze_statement, parse_statement
from template_manager import delete_template, extract_preview_text, load_templates, save_template
from workpaper_export import build_workpaper

# --- Page setup and branding ---

# Change these to rebrand the app; the colors also live in .streamlit/config.toml and index.html.
APP_NAME = "Bank Statement Analyzer"
APP_TAGLINE = "Turn bank statement PDFs into forensic accounting workpapers in minutes."
ORG_NAME = "Justice for Fraud Victims Project"
NAVY = "#14284B"
GOLD = "#C9A227"

st.set_page_config(page_title=APP_NAME, page_icon=":material/account_balance:", layout="wide")

st.markdown(
    f"""
    <style>
    #MainMenu, [data-testid="stToolbar"], [data-testid="stDecoration"], footer {{visibility: hidden; height: 0;}}
    .block-container {{padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1200px;}}
    .brand-bar {{display: flex; align-items: center; gap: 0.9rem; background: {NAVY}; color: #FFFFFF;
                 border-radius: 12px; padding: 1.1rem 1.4rem; border-bottom: 4px solid {GOLD};}}
    .brand-mark {{width: 44px; height: 44px; flex: none; border-radius: 10px; background: {GOLD};
                  display: flex; align-items: center; justify-content: center;}}
    .brand-org {{font-size: 0.72rem; letter-spacing: 0.12em; text-transform: uppercase; color: #E8D9A8; margin: 0;}}
    .brand-name {{font-size: 1.55rem; font-weight: 700; margin: 0.1rem 0 0 0; color: #FFFFFF; line-height: 1.2;}}
    .brand-tagline {{font-size: 0.95rem; color: #D6DEEB; margin: 0.2rem 0 0 0;}}
    .privacy {{margin: 0.7rem 0 1.1rem 0; padding: 0.55rem 0.9rem; border-radius: 8px; font-size: 0.88rem;
               background: #EEF6F1; color: #1E5A3C; border: 1px solid #CFE6D8;}}
    .steps {{counter-reset: step; list-style: none; padding: 0; margin: 0.4rem 0 1rem 0;}}
    .steps li {{counter-increment: step; display: flex; gap: 0.6rem; align-items: baseline; margin: 0.45rem 0;
                font-size: 0.92rem; color: #1F2937;}}
    .steps li::before {{content: counter(step); flex: none; width: 1.45rem; height: 1.45rem; border-radius: 50%;
                        background: {NAVY}; color: #FFFFFF; font-size: 0.78rem; font-weight: 600;
                        display: inline-flex; align-items: center; justify-content: center;}}
    .section-card {{border: 1px solid #E3E7EE; border-left: 4px solid {GOLD}; border-radius: 8px;
                    padding: 0.8rem 1rem; background: #FFFFFF; color: #1F2937; margin-bottom: 0.8rem;}}
    .app-footer {{margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid #E3E7EE;
                  font-size: 0.8rem; color: #6B7280; text-align: center;}}
    div[data-testid="stMetric"] {{background: #F7F9FC; border: 1px solid #E3E7EE; border-radius: 10px; padding: 0.7rem 0.9rem;}}
    .stTabs [data-baseweb="tab-list"] {{gap: 0.25rem;}}
    .stTabs [data-baseweb="tab"] {{font-weight: 600;}}
    </style>
    """,
    unsafe_allow_html=True,
)

# Where the app is running decides what we can promise about the uploaded files.
privacy_note = ""
if sys.platform == "emscripten":
    privacy_note = "🔒 Private by design: this app runs inside your browser, so statements you upload never leave your computer."
elif st.context.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1"):
    privacy_note = "🔒 Private by design: this app is running on your own computer, so statements you upload stay here."

st.markdown(
    f"""
    <div class="brand-bar">
      <div class="brand-mark">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="{NAVY}" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 3v18M5 21h14M4 7h16M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0z"/>
        </svg>
      </div>
      <div>
        <div class="brand-org">{ORG_NAME}</div>
        <div class="brand-name">{APP_NAME}</div>
        <div class="brand-tagline">{APP_TAGLINE}</div>
      </div>
    </div>
    {f'<div class="privacy">{privacy_note}</div>' if privacy_note else '<div style="height:1rem"></div>'}
    """,
    unsafe_allow_html=True,
)


# --- Display helpers ---


def _display_category_name(cat: str) -> str:
    """Map internal category codes to human-readable labels for charts and tables."""
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
    """Return a colored emoji badge for transaction risk level."""
    return {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}.get(str(level).lower(), "⚪ Unknown")


def _severity_badge(level: str) -> str:
    """Return a colored emoji badge for flag severity (same scale as risk)."""
    return {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}.get(str(level).lower(), "⚪ Unrated")


def _build_reconciliation_table(transactions: pd.DataFrame) -> pd.DataFrame:
    """
    Build per-statement reconciliation rows.

    For each statement, sums credits/debits and compares the implied ending
    balance (beginning + credits - debits) to the last running balance on the
    statement. A difference within $0.01 is treated as reconciled.
    """
    if transactions.empty:
        return pd.DataFrame(
            columns=[
                "statement_id",
                "account_number",
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
    # One row per account: a single PDF can hold several accounts (e.g. checking plus a credit line).
    for (statement_id, account_number), grp in transactions.groupby(["statement_id", "account_number"], dropna=False):
        # Preserve statement order: date, then PDF page/line position.
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
            # Derive opening balance by reversing the first transaction from its running balance.
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
                "account_number": account_number,
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
    return pd.DataFrame(rows).sort_values(["statement_id", "account_number"]).reset_index(drop=True)


# --- Sidebar: global options that affect parsing and export ---

with st.sidebar:
    st.markdown("#### How it works")
    st.markdown(
        '<ol class="steps"><li>Upload bank statement PDFs</li><li>Review transactions, red flags and the bank reconciliation</li>'
        "<li>Download your Excel workpapers</li></ol>",
        unsafe_allow_html=True,
    )
    st.markdown("#### Settings")
    # Dollar amount above which transactions are flagged as "large" during parsing.
    large_txn_threshold = st.number_input("Flag transactions over ($)", min_value=100.0, value=1000.0, step=100.0)
    # Whether the exported workpaper includes a tab of raw PDF text per page.
    include_raw_text = st.checkbox("Include full statement text in the workpaper", value=False)
    st.caption(f"Banks you've added: {len(load_templates())}")

# --- File upload and parsing ---

uploads = st.file_uploader(
    "Upload bank statement PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="Use the PDF downloaded from online banking. Scanned paper statements can't be read.",
)
has_uploads = bool(uploads)

# Empty DataFrame schemas used before any files are parsed.
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
            # Parse each PDF into transactions, risk flags, and optional raw text.
            result = parse_statement(uploaded_file.name, uploaded_file.getvalue(), large_txn_threshold)
            results.append(result)
        except Exception as exc:  # pragma: no cover
            parse_errors.append(f"{uploaded_file.name}: {exc}")
    if parse_errors:
        st.error("Some files could not be parsed:")
        for err in parse_errors:
            st.write(f"- {err}")
    # Tell the user, file by file, how each statement was read.
    for uploaded_file, result in zip([u for u in uploads if not any(e.startswith(f"{u.name}:") for e in parse_errors)], results):
        if result.transactions.empty:
            if not "".join(result.raw_text.get("text", pd.Series(dtype=str)).fillna("")).strip():
                st.warning(f"{uploaded_file.name}: no readable text. It looks like a scanned image; use the bank's downloaded PDF instead.")
            else:
                st.warning(f"{uploaded_file.name}: no transactions found. Try it in the Template Manager tab to see what the app can read.")
        else:
            layout = str(result.transactions["bank_format"].iloc[0])
            layout = BUILT_IN_FORMAT_NAMES.get(layout, layout.replace("auto:", "auto-detected: ").replace("custom:", "template: "))
            st.caption(f"✅ {uploaded_file.name}: {len(result.transactions)} transactions ({layout})")
    if results:
        # Merge parsed output from all successfully processed statements.
        all_transactions = pd.concat([r.transactions for r in results], ignore_index=True)
        all_flags = pd.concat([r.flags for r in results], ignore_index=True)
        all_raw = pd.concat([r.raw_text for r in results], ignore_index=True)

# --- Aggregate metrics shared across dashboard tabs ---

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

# --- Main tabbed UI ---

overview_tab, transactions_tab, risk_tab, reconciliation_tab, export_tab, template_tab = st.tabs(
    ["Summary", "Transactions", "Red Flags", "Bank Reconciliation", "Download Workpapers", "Add a New Bank"]
)

with overview_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload at least one statement to view dashboard metrics.")
    else:
        # Summary KPI cards: volume, risk, and cash flow totals.
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
        c1.bar_chart(category_chart.set_index("category"), color=NAVY)
        # Fixed order so low/medium/high always appear even when a level has zero rows.
        risk_chart = all_transactions["risk_level"].value_counts().reindex(["high", "medium", "low"], fill_value=0).rename_axis("risk").to_frame("count")
        c2.markdown("#### Risk Levels")
        c2.bar_chart(risk_chart, color=GOLD)

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
        # Highest-risk transactions first, then chronological within risk tier.
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
            rec[["statement_id", "account_number", "beginning_balance", "total_credits", "total_debits", "expected_ending_balance", "ending_balance", "reconciliation_difference", "status_badge", "notes"]],
            use_container_width=True,
            hide_index=True,
            height=360,
        )

with export_tab:
    if not has_uploads or all_transactions.empty:
        st.info("Upload statements to export workbooks.")
    else:
        # Build Excel byte streams for forensic workpaper and summarized financial statements.
        workpaper_bytes = build_workpaper(all_transactions, all_flags, all_raw if include_raw_text else pd.DataFrame(), datetime.now())
        financial_bytes = build_financial_statements(all_transactions, reconciliation_df, datetime.now())
        d1, d2 = st.columns(2)
        d1.download_button("Download Forensic Workpaper (.xlsx)", data=BytesIO(workpaper_bytes).getvalue(), file_name=f"forensic_workpaper_{datetime.now():%Y%m%d_%H%M%S}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        d2.download_button("Download Financial Statements (.xlsx)", data=BytesIO(financial_bytes).getvalue(), file_name=f"financial_statements_{datetime.now():%Y%m%d_%H%M%S}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with template_tab:
    # One-click onboarding: upload a statement from a new bank, check what was read, save it.
    st.markdown("#### Add a new bank")
    st.markdown(
        '<div class="section-card">Most statements are read automatically, even from banks the app has never seen. '
        "To save a bank so it's always recognized, upload one of its statements, check the preview, and click "
        "<b>Save this bank</b>. No setup or typing needed.</div>",
        unsafe_allow_html=True,
    )
    sample_upload = st.file_uploader("Upload one statement from the bank", type=["pdf"], key="template_sample_upload")
    if sample_upload is not None:
        analysis = analyze_statement(sample_upload.name, sample_upload.getvalue())
        if not analysis.has_text:
            st.error("This PDF has no readable text. It looks like a scanned image; use the PDF downloaded from online banking instead.")
        elif analysis.preview.empty:
            st.warning("No transactions found automatically. Use 'Advanced: set up a bank by hand' below.")
        else:
            if analysis.built_in_format:
                st.success(f"Already supported: {analysis.built_in_format}. Nothing to set up: just upload it at the top of the page.")
            elif analysis.matched_template:
                st.success(f"Already saved as \"{analysis.matched_template}\".")
            confidence_text = {
                "high": "🟢 Looks right: every running balance checks out",
                "medium": "🟠 Probably right: spot-check the rows below",
                "low": "🔴 Check carefully: some rows may be misread",
            }.get(analysis.confidence, "⚪ Unknown")
            st.markdown(f"##### {analysis.bank_name or 'Bank name not found'}")
            m2, m3 = st.columns(2)
            m2.metric("Transactions found", len(analysis.preview))
            if analysis.has_balance_column:
                m3.metric(
                    "Balances that check out",
                    f"{analysis.balance_verified_rows} of {analysis.balance_rows}",
                    help="Each row's running balance should equal the previous balance plus or minus the amount.",
                )
            else:
                m3.metric("Balances that check out", "n/a", help="This statement has no running balance column.")
            st.markdown(f"**{confidence_text}**")
            st.dataframe(
                analysis.preview.head(15).rename(
                    columns={"txn_date": "Date", "description": "Description", "debit": "Debit", "credit": "Credit", "running_balance": "Balance"}
                ),
                use_container_width=True,
                hide_index=True,
            )

            if not analysis.built_in_format and not analysis.matched_template:
                with st.form("auto_template_form"):
                    auto_name = st.text_input("Bank name", value=analysis.bank_name or "")
                    save_clicked = st.form_submit_button("Save this bank", type="primary")
                keywords = analysis.detection_keywords or ([auto_name.strip().lower()] if auto_name.strip() else [])
                st.caption(f"Statements that contain: {', '.join(repr(k) for k in keywords) or '(nothing yet)'} will be recognized as this bank.")
                if save_clicked:
                    ok, msg = save_template(
                        {
                            "template_name": auto_name,
                            "detection_keywords": keywords,
                            "parse_style": "auto",
                            "default_direction": "debit",
                            "credit_keywords": list(CREDIT_WORDS),
                        }
                    )
                    if ok:
                        st.success("Saved. Statements from this bank will now be recognized automatically.")
                    else:
                        st.error(msg)

    templates = load_templates()
    st.markdown("##### Saved banks")
    if templates:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Bank": t["template_name"],
                        "Parse Style": "Automatic" if t["parse_style"] == "auto" else t["parse_style"],
                        "Default Direction": t["default_direction"],
                        "Detection Keywords": ", ".join(t["detection_keywords"]),
                    }
                    for t in templates
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        delete_name = st.selectbox("Remove a saved bank", [t["template_name"] for t in templates], key="delete_template")
        if st.button("Remove"):
            ok, msg = delete_template(delete_name)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    else:
        st.info("No banks saved yet. Built-in and auto-detected banks work without saving.")

    with st.expander("Advanced: set up a bank by hand"):
        if sample_upload is not None:
            # Show raw text extracted from the uploaded PDF to help pick keywords and parse style.
            st.text_area("Extracted preview text", value=extract_preview_text(sample_upload.getvalue()), height=180)
        with st.form("template_form", clear_on_submit=False):
            template_name = st.text_input("Template name", placeholder="Example: First National Monthly")
            detection_keywords_text = st.text_input("Detection keywords (comma-separated)", placeholder="first national, account summary")
            parse_style = st.selectbox(
                "Parse style",
                options=["auto", "slash_leading_amount_balance", "date_dash_last_amount"],
                format_func=lambda style: "Automatic (recommended)" if style == "auto" else style,
                help="Automatic reads most layouts. Use slash style for lines beginning with MM/DD/YYYY, dash style for MM-DD dates inside lines.",
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

st.markdown(
    f'<div class="app-footer">{APP_NAME} · {ORG_NAME} · Built for forensic accounting education</div>',
    unsafe_allow_html=True,
)
