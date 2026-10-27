"""
Streamlit front-end for Bank Statement Analyzer.

Upload bank statement PDFs, parse transactions, review risk/reconciliation
dashboards, export Excel workpapers, and manage custom bank-format templates.
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List

import altair as alt
import pandas as pd
import streamlit as st

import dashboard
from auto_parser import CREDIT_WORDS
from bank_directory import BANKS, directory_table

BANK_NAMES = {bank["name"] for bank in BANKS}
# Shown on the welcome screen; the rest are behind "See all".
FEATURED_BANKS = [
    "Chase", "Bank of America", "Wells Fargo", "Citibank", "U.S. Bank", "PNC Bank", "Truist", "Capital One",
    "TD Bank", "Navy Federal Credit Union", "USAA", "American Express", "Discover",
]
from financial_statements import build_financial_statements
from statement_parser import BUILT_IN_FORMAT_NAMES, ParseResult, analyze_statement, parse_statement
from template_manager import delete_template, extract_preview_text, load_templates, save_template
from workpaper_export import build_workpaper

# --- Page setup and branding ---

# Change these to rebrand the app; the colors also live in .streamlit/config.toml and index.html.
# To show the organization's logo, save it as assets/logo.png (or .svg / .jpg).
APP_NAME = "Bank Statement Analyzer"
APP_TAGLINE = "Turn bank statement PDFs into forensic accounting workpapers in minutes."
ORG_NAME = "Justice for Fraud Victims Project"
# Justice for Fraud Victims Project palette (from justiceforfraudvictimsproject.org).
NAVY = "#1D2844"  # scales badge
BLUE = "#246094"  # "JFVP" lettering
TAUPE = "#918E81"  # quote panel
LIGHT = "#F3F3F3"  # header bar
RISK_COLORS = {"High": "#B42318", "Medium": "#D97706", "Low": "#15803D"}

APP_DIR = Path(__file__).resolve().parent
SAMPLE_FILES = ["Sample-Statement.pdf", "statement_sample1.pdf"]

st.set_page_config(page_title=APP_NAME, page_icon=":material/account_balance:", layout="wide")


def _logo_html() -> str:
    """The organization's logo if one was added to assets/, otherwise a scales-of-justice mark."""
    for name, mime in (("logo.svg", "image/svg+xml"), ("logo.png", "image/png"), ("logo.jpg", "image/jpeg")):
        path = APP_DIR / "assets" / name
        if path.exists():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f'<img class="brand-logo" src="data:{mime};base64,{encoded}" alt="{ORG_NAME} logo">'
    return (
        f'<div class="brand-mark"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M12 3v18M5 21h14M4 7h16M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0z"/></svg></div>'
    )


st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Jost:wght@300;400;500&family=Cormorant+Garamond:ital,wght@1,500;1,600&display=swap');
    .stApp, .stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea, .stApp li, .stApp h1, .stApp h2,
    .stApp h3, .stApp h4, .stApp h5, .stApp [data-baseweb="tab"] {{
        font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;}}
    .stApp a {{color: {BLUE};}}
    .stApp [data-testid="stIconMaterial"] {{font-family: 'Material Symbols Rounded' !important;}}
    #MainMenu, [data-testid="stToolbar"], [data-testid="stDecoration"], footer {{visibility: hidden; height: 0;}}
    /* Streamlit's (hidden) top bar still takes space; start the page below it so the logo is never cut off. */
    header[data-testid="stHeader"] {{background: transparent;}}
    .block-container {{padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1180px;}}
    h1, h2, h3, h4, h5 {{color: {NAVY}; letter-spacing: -0.01em;}}

    .brand {{border-radius: 14px; overflow: hidden; box-shadow: 0 8px 26px rgba(29, 40, 68, 0.14); border: 1px solid #E2E2E2;}}
    .brand-top {{display: flex; align-items: center; justify-content: space-between; gap: 1rem;
                 background: {LIGHT}; padding: 1.1rem 1.6rem; min-height: 92px;}}
    .brand-logo {{height: 64px; width: auto; flex: none; display: block; object-fit: contain;}}
    .brand-mark {{width: 52px; height: 52px; flex: none; border-radius: 50%; background: {NAVY};
                  display: flex; align-items: center; justify-content: center;}}
    .brand-nav {{font-family: 'Jost', system-ui, sans-serif; font-weight: 300; font-size: 1.05rem; color: #404040;
                 letter-spacing: 0.01em; text-align: right;}}
    .brand-band {{position: relative; overflow: hidden; background: linear-gradient(100deg, #8A877A 0%, {TAUPE} 55%, #9C998D 100%);
                  color: #FFFFFF; padding: 1.6rem 1.8rem 1.5rem 1.8rem;}}
    .brand-band::after {{content: ""; position: absolute; right: -40px; top: -60px; width: 260px; height: 260px;
                         border-radius: 50%; border: 1px solid rgba(255,255,255,0.18);}}
    .brand-name {{font-family: 'Cormorant Garamond', Georgia, serif; font-style: italic; font-weight: 600;
                  font-size: 2.6rem; line-height: 1.05; color: #FFFFFF;}}
    .brand-tagline {{font-family: 'Jost', system-ui, sans-serif; font-weight: 300; font-size: 1.08rem; color: #F4F2EC; margin-top: 0.45rem;}}
    .brand-privacy {{font-family: 'Jost', system-ui, sans-serif; font-weight: 400; font-size: 0.9rem; color: #FFFFFF; margin-top: 0.7rem;}}

    .section-title {{font-family: 'Jost', system-ui, sans-serif; font-size: 1.15rem; font-weight: 500; color: {NAVY}; margin: 1.6rem 0 0.2rem 0;}}
    .section-sub {{font-size: 0.9rem; color: #5B6575; margin-bottom: 0.6rem;}}
    [data-testid="stFileUploaderDropzone"] {{border: 2px dashed #C9D3E3; background: #F7F9FC; border-radius: 12px;}}

    .feature-grid {{display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.9rem; margin-top: 0.4rem;}}
    .feature {{background: #FFFFFF; border: 1px solid #E3E7EE; border-radius: 14px; padding: 1.1rem 1.15rem;
               box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);}}
    .feature-icon {{width: 38px; height: 38px; border-radius: 10px; background: #EEF2F8; display: flex;
                    align-items: center; justify-content: center; margin-bottom: 0.7rem;}}
    .feature h4 {{margin: 0 0 0.3rem 0; font-size: 0.98rem; color: {NAVY};}}
    .feature p {{margin: 0; font-size: 0.86rem; color: #5B6575; line-height: 1.45;}}
    .banks-panel {{background: #F7F9FC; border: 1px solid #E3E7EE; border-radius: 14px; padding: 1rem 1.15rem; margin-top: 0.9rem;}}
    .banks-panel h4 {{margin: 0 0 0.25rem 0; font-size: 0.98rem; color: {NAVY};}}
    .banks-panel p {{margin: 0 0 0.6rem 0; font-size: 0.86rem; color: #5B6575;}}
    .bank-chips {{display: flex; flex-wrap: wrap; gap: 0.4rem;}}
    .bank-chip {{font-size: 0.8rem; font-weight: 500; color: {NAVY}; background: #FFFFFF; border: 1px solid #D5DCE8;
                 border-radius: 999px; padding: 0.22rem 0.7rem;}}
    .bank-chip.more {{background: {NAVY}; color: #FFFFFF; border-color: {NAVY};}}

    .kpi-grid {{display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.8rem; margin: 0.6rem 0 1rem 0;}}
    .kpi {{background: #FFFFFF; border: 1px solid #E3E7EE; border-top: 3px solid {NAVY}; border-radius: 12px;
           padding: 0.85rem 1rem; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);}}
    .kpi.gold {{border-top-color: {TAUPE};}}
    .kpi.blue {{border-top-color: {BLUE};}}
    .kpi.red {{border-top-color: {RISK_COLORS['High']};}}
    .kpi.green {{border-top-color: {RISK_COLORS['Low']};}}
    .kpi-label {{font-size: 0.75rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: #6B7280;}}
    .kpi-value {{font-size: 1.55rem; font-weight: 700; color: #111827; margin-top: 0.2rem; font-variant-numeric: tabular-nums;}}
    .kpi-sub {{font-size: 0.8rem; color: #6B7280; margin-top: 0.1rem;}}

    .file-list {{display: flex; flex-direction: column; gap: 0.35rem; margin: 0.4rem 0 0.2rem 0;}}
    .file-row {{display: flex; align-items: center; gap: 0.6rem; font-size: 0.88rem; color: #1F2937;
                background: #F7F9FC; border: 1px solid #E3E7EE; border-radius: 10px; padding: 0.45rem 0.75rem;}}
    .file-row .meta {{color: #6B7280; margin-left: auto; font-size: 0.8rem;}}
    .status {{display: inline-block; font-size: 0.75rem; font-weight: 600; padding: 0.15rem 0.6rem; border-radius: 999px;}}
    .status.ok {{background: #E7F6EC; color: #15803D;}}
    .status.warn {{background: #FEF3E2; color: #B45309;}}
    .status.bad {{background: #FDECEA; color: #B42318;}}

    .recon-card {{background: #FFFFFF; border: 1px solid #E3E7EE; border-radius: 14px; padding: 1rem 1.15rem; margin-bottom: 0.8rem;}}
    .recon-head {{display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.6rem;}}
    .recon-head .title {{font-weight: 600; color: {NAVY};}}
    .recon-math {{display: grid; grid-template-columns: 1fr auto; row-gap: 0.25rem; max-width: 420px;
                  font-size: 0.9rem; color: #374151; font-variant-numeric: tabular-nums;}}
    .recon-math .total {{border-top: 1px solid #D1D5DB; padding-top: 0.25rem; font-weight: 600; color: #111827;}}
    .recon-note {{font-size: 0.82rem; color: #6B7280; margin-top: 0.5rem;}}

    .download-card {{background: #FFFFFF; border: 1px solid #E3E7EE; border-radius: 14px; padding: 1.1rem 1.15rem; min-height: 150px;}}
    .download-card h4 {{margin: 0 0 0.3rem 0; color: {NAVY}; font-size: 1rem;}}
    .download-card p {{margin: 0 0 0.6rem 0; font-size: 0.86rem; color: #5B6575;}}

    .steps {{counter-reset: step; list-style: none; padding: 0; margin: 0.4rem 0 1rem 0;}}
    .steps li {{counter-increment: step; display: flex; gap: 0.6rem; align-items: baseline; margin: 0.5rem 0;
                font-size: 0.9rem; color: #1F2937;}}
    .steps li::before {{content: counter(step); flex: none; width: 1.45rem; height: 1.45rem; border-radius: 50%;
                        background: {NAVY}; color: #FFFFFF; font-size: 0.75rem; font-weight: 600;
                        display: inline-flex; align-items: center; justify-content: center;}}
    .section-card {{border: 1px solid #E3E7EE; border-left: 4px solid {BLUE}; border-radius: 10px;
                    padding: 0.85rem 1rem; background: #FFFFFF; color: #1F2937; margin-bottom: 0.8rem;}}
    .stTabs [data-baseweb="tab-list"] {{gap: 0.3rem; border-bottom: 1px solid #E3E7EE;}}
    .stTabs [data-baseweb="tab"] {{font-family: 'Jost', system-ui, sans-serif; font-weight: 400; font-size: 1rem; padding: 0.55rem 0.9rem;}}
    .stTabs [aria-selected="true"] {{color: {NAVY};}}
    .stTabs [data-baseweb="tab-highlight"] {{background-color: {BLUE};}}
    div[data-testid="stMetric"] {{background: #FFFFFF; border: 1px solid #E3E7EE; border-radius: 12px; padding: 0.75rem 0.95rem;}}
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{border-radius: 10px; font-weight: 600;}}
    section[data-testid="stSidebar"] {{background: #F7F9FC; border-right: 1px solid #E3E7EE;}}
    .app-footer {{margin-top: 3rem; padding-top: 1.1rem; border-top: 1px solid #E3E7EE;
                  font-size: 0.8rem; color: #6B7280; text-align: center;}}
    </style>
    """,
    unsafe_allow_html=True,
)

# Where the app is running decides what we can promise about the uploaded files.
privacy_note = ""
if sys.platform == "emscripten":
    privacy_note = "Private: runs inside your browser"
elif st.context.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1"):
    privacy_note = "Private: runs on your computer"

st.markdown(
    f"""
    <div class="brand">
      <div class="brand-top">
        {_logo_html()}
        <div class="brand-nav">Forensic accounting education</div>
      </div>
      <div class="brand-band">
        <div class="brand-name">{APP_NAME}</div>
        <div class="brand-tagline">{APP_TAGLINE}</div>
        {f'<div class="brand-privacy">🔒 {privacy_note}</div>' if privacy_note else ''}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Display helpers ---


def _money(value) -> str:
    """Format a number as $1,234.56 (negative as -$1,234.56); blank when missing."""
    if value is None or pd.isna(value):
        return "—"
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def _kpis(items: List[tuple]) -> None:
    """Render a row of KPI cards from (label, value, note, accent) tuples."""
    cards = "".join(
        f'<div class="kpi {accent}"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{note}</div></div>'
        for label, value, note, accent in items
    )
    st.markdown(f'<div class="kpi-grid">{cards}</div>', unsafe_allow_html=True)


def _section(title: str, subtitle: str = "") -> None:
    sub = f'<div class="section-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="section-title">{title}</div>{sub}', unsafe_allow_html=True)


MONEY_COLUMN = {"format": "dollar"}
DATE_COLUMN = st.column_config.DateColumn("Date", format="MMM D, YYYY")


def _money_cells(frame: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """Show amounts as $1,234.56 text so blank debits/credits appear empty instead of "None"."""
    frame = frame.copy()
    for col in columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").map(lambda v: "" if pd.isna(v) else _money(v))
    return frame


def _money_text_column(label: str):
    return st.column_config.TextColumn(label, alignment="right")




def _templates_key() -> str:
    """Saved banks change how statements are read, so they are part of the cache key."""
    return json.dumps(load_templates(), sort_keys=True)


def _parse_with_progress(name: str, data: bytes, threshold: float) -> ParseResult:
    """
    Parse a statement, showing OCR progress. The slow part (reading scanned pages) is cached
    per file inside pdf_text, so later reruns re-parse in a fraction of a second.
    """
    progress = st.empty()

    def report(done: int, total: int) -> None:
        progress.progress(done / total, text=f"Reading scanned pages of {name}: page {done} of {total}")

    try:
        return parse_statement(name, data, threshold, progress=report)
    finally:
        progress.empty()


@st.cache_data(show_spinner=False, max_entries=20)
def _analyze_cached(name: str, data: bytes, templates_key: str):
    return analyze_statement(name, data)


@dataclass
class _BundledFile:
    """A sample PDF shipped with the app, shaped like a Streamlit upload."""

    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


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
        "card_payment": "Card Payment",
        "card_credit": "Card Credit / Refund",
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


RECON_COLUMNS = [
    "statement_id",
    "account_number",
    "method",
    "statement_kind",
    "beginning_balance",
    "total_credits",
    "total_debits",
    "expected_ending_balance",
    "ending_balance",
    "reconciliation_difference",
    "printed_net",
    "printed_items",
    "items",
    "status",
    "notes",
]


def _first_number(frame: pd.DataFrame, column: str):
    values = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors="coerce").dropna()
    return float(values.iloc[0]) if not values.empty else None


def _build_reconciliation_table(transactions: pd.DataFrame) -> pd.DataFrame:
    """
    Build one reconciliation row per statement and account, using the best evidence available:

    1. running balance: beginning + credits - debits must equal the last running balance;
    2. printed control totals ("10 Total Deposits : $8,337.98"), used when balances are
       missing or redacted: the net change and item count must agree;
    3. the statement's printed opening and closing balances (previous/new balance on a
       credit card) when the statement holds a single account.
    A difference within $0.01 is treated as reconciled.
    """
    if transactions.empty:
        return pd.DataFrame(columns=RECON_COLUMNS)
    rows = []
    accounts_per_statement = transactions.groupby("statement_id", dropna=False)["account_number"].nunique(dropna=False)
    # One row per account: a single PDF can hold several accounts (e.g. checking plus a credit line).
    for (statement_id, account_number), grp in transactions.groupby(["statement_id", "account_number"], dropna=False):
        # Preserve statement order: date, then PDF page/line position.
        ordered = grp.sort_values(["txn_date", "source_page", "source_line"]).copy()
        credits = float(pd.to_numeric(ordered["credit"], errors="coerce").fillna(0).sum())
        debits = float(pd.to_numeric(ordered["debit"], errors="coerce").fillna(0).sum())
        running = pd.to_numeric(ordered.get("running_balance"), errors="coerce").dropna()
        kind = str(ordered["statement_kind"].iloc[0]) if "statement_kind" in ordered and pd.notna(ordered["statement_kind"].iloc[0]) else "bank"
        row = {
            "statement_id": statement_id,
            "account_number": account_number,
            "method": None,
            "statement_kind": kind,
            "beginning_balance": None,
            "total_credits": credits,
            "total_debits": debits,
            "expected_ending_balance": None,
            "ending_balance": None,
            "reconciliation_difference": None,
            "printed_net": None,
            "printed_items": None,
            "items": len(ordered),
            "status": "Needs Review",
            "notes": "No running balance or printed totals found; manual reconciliation required.",
        }
        printed_credits = _first_number(ordered, "control_credit_total")
        printed_debits = _first_number(ordered, "control_debit_total")
        opening = _first_number(ordered, "statement_opening_balance")
        closing = _first_number(ordered, "statement_closing_balance")
        if not running.empty:
            # Opening balance: the first printed balance, less every transaction up to and including it
            # (some banks print a balance only on the last line of each day).
            net = (
                pd.to_numeric(ordered["credit"], errors="coerce").fillna(0)
                - pd.to_numeric(ordered["debit"], errors="coerce").fillna(0)
            ).cumsum()
            beginning = float(running.iloc[0]) - float(net.loc[running.index[0]])
            # Lines after the last printed balance can't be checked against it; carry them forward.
            ending = float(running.iloc[-1]) + float(net.iloc[-1] - net.loc[running.index[-1]])
            row.update(method="running_balance", beginning_balance=beginning, ending_balance=ending)
            row["expected_ending_balance"] = beginning + credits - debits
            row["reconciliation_difference"] = row["ending_balance"] - row["expected_ending_balance"]
            if abs(row["reconciliation_difference"]) <= 0.01:
                row.update(status="Reconciled", notes="Expected ending balance agrees to statement running balance.")
            else:
                row.update(status="Variance", notes="Expected ending balance differs from statement running balance.")
                # Checks listed only in a check summary never touch the register's running balance.
                unregistered_checks = ordered[(ordered["transaction_type"] == "check") & ordered["running_balance"].isna()]
                unregistered_total = float(pd.to_numeric(unregistered_checks["debit"], errors="coerce").fillna(0).sum())
                if unregistered_total and abs(row["reconciliation_difference"] - unregistered_total) <= 0.01:
                    row["notes"] = (
                        f"The difference equals the {len(unregistered_checks)} checks (${unregistered_total:,.2f}) listed in the "
                        "statement's check summary that don't appear in its transaction register. Trace these checks."
                    )
        elif printed_credits is not None or printed_debits is not None:
            # Banks differ on where reversals belong (a negative deposit vs. a withdrawal), so compare
            # the net change and the number of items rather than each side separately.
            printed_net = (printed_credits or 0.0) - (printed_debits or 0.0)
            counts = [_first_number(ordered, "control_credit_count"), _first_number(ordered, "control_debit_count")]
            printed_items = int(sum(c for c in counts if c is not None)) if any(c is not None for c in counts) else None
            difference = (credits - debits) - printed_net
            row.update(method="control_totals", printed_net=printed_net, printed_items=printed_items, reconciliation_difference=difference)
            items_ok = printed_items is None or printed_items == len(ordered)
            if abs(difference) <= 0.01 and items_ok:
                row.update(status="Reconciled", notes="Every transaction was read: the totals and item count agree with the totals printed on the statement.")
            elif abs(difference) <= 0.01:
                row.update(status="Variance", notes=f"Totals agree but the statement lists {printed_items} items and {len(ordered)} were read.")
            else:
                row.update(status="Variance", notes="The transactions read don't add up to the totals printed on the statement; some may be missing or misread.")
        elif opening is not None and closing is not None and accounts_per_statement.get(statement_id, 1) == 1:
            # A card balance rises with charges and falls with payments; a bank balance the other way round.
            expected = opening + debits - credits if kind == "credit_card" else opening + credits - debits
            row.update(method="summary_balance", beginning_balance=opening, ending_balance=closing, expected_ending_balance=expected)
            row["reconciliation_difference"] = closing - expected
            if abs(row["reconciliation_difference"]) <= 0.01:
                row.update(status="Reconciled", notes="Opening balance and the transactions read agree to the closing balance printed on the statement.")
            else:
                row.update(status="Variance", notes="The transactions read don't account for the change between the printed opening and closing balances.")
        rows.append(row)
    return pd.DataFrame(rows, columns=RECON_COLUMNS).sort_values(["statement_id", "account_number"]).reset_index(drop=True)


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

_section(
    "Upload statements",
    "Drop in one or more statement PDFs: downloaded from online banking, scanned, or redacted. Scans take a few seconds per page.",
)
uploads = st.file_uploader(
    "Upload bank statement PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)
if uploads:
    st.session_state["use_samples"] = False
sample_col, clear_col, _ = st.columns([1.6, 1, 2.4])
available_samples = [name for name in SAMPLE_FILES if (APP_DIR / name).exists()]
if not uploads and available_samples:
    if sample_col.button("Try it with sample statements", icon=":material/description:"):
        st.session_state["use_samples"] = True
    if st.session_state.get("use_samples") and clear_col.button("Clear samples"):
        st.session_state["use_samples"] = False
        st.rerun()

statement_files = list(uploads or [])
if not statement_files and st.session_state.get("use_samples"):
    statement_files = [_BundledFile(name, (APP_DIR / name).read_bytes()) for name in available_samples]
has_uploads = bool(statement_files)

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
    "redacted",
    "statement_kind",
    "statement_opening_balance",
    "statement_closing_balance",
    "control_credit_total",
    "control_credit_count",
    "control_debit_total",
    "control_debit_count",
]
flag_columns = ["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"]

all_transactions = pd.DataFrame(columns=tx_columns)
all_flags = pd.DataFrame(columns=flag_columns)
all_raw = pd.DataFrame(columns=["statement_id", "page", "text"])
results: List[ParseResult] = []

if has_uploads:
    file_rows: List[str] = []
    warnings: List[str] = []
    for statement_file in statement_files:
        try:
            # Parse each PDF into transactions, risk flags, and optional raw text.
            result = _parse_with_progress(statement_file.name, statement_file.getvalue(), large_txn_threshold)
        except Exception as exc:  # pragma: no cover
            file_rows.append(f'<div class="file-row"><span class="status bad">Error</span>{statement_file.name}<span class="meta">{exc}</span></div>')
            continue
        results.append(result)
        # Tell the user, file by file, how each statement was read.
        if result.transactions.empty:
            if any("couldn't be read" in n for n in result.notes):
                note = (
                    "Scanned statement. Reading scans needs the version that runs on your computer "
                    "(see the README); this browser version reads downloaded PDFs only."
                )
            elif not "".join(result.raw_text.get("text", pd.Series(dtype=str)).fillna("")).strip():
                note = "No readable text in this PDF."
            else:
                note = "No transactions found. Try it in the Add a New Bank tab."
            file_rows.append(f'<div class="file-row"><span class="status warn">Check</span>{statement_file.name}<span class="meta">{note}</span></div>')
        else:
            layout = str(result.transactions["bank_format"].iloc[0])
            layout = BUILT_IN_FORMAT_NAMES.get(layout, layout.replace("auto:", "Auto-detected: ").replace("custom:", "Saved bank: "))
            # Say plainly whether the bank is on the built-in list.
            if layout.startswith("Auto-detected: ") and layout[len("Auto-detected: "):] in BANK_NAMES:
                layout = f"<b>Recognized: {layout[len('Auto-detected: '):]}</b>"
            elif layout.startswith("Auto-detected"):
                layout = "Read automatically"
            statements = result.transactions["statement_id"].nunique()
            found = f"{statements} statements · " if statements > 1 else ""
            remarks = "".join(f" · {note}" for note in result.notes if "black boxes" not in note.lower())
            file_rows.append(
                f'<div class="file-row"><span class="status ok">Read</span>{statement_file.name}'
                f'<span class="meta">{found}{len(result.transactions)} transactions · {layout}{remarks}</span></div>'
            )
        # Redaction that didn't remove the text is a privacy problem worth a prominent warning.
        warnings += [f"**{statement_file.name}:** {note}" for note in result.notes if "black boxes" in note.lower()]
    st.markdown(f'<div class="file-list">{"".join(file_rows)}</div>', unsafe_allow_html=True)
    for warning in warnings:
        st.warning(warning, icon=":material/visibility_off:")
    if results:
        # Merge parsed output from all successfully processed statements.
        all_transactions = pd.concat([r.transactions for r in results], ignore_index=True)
        all_flags = pd.concat([r.flags for r in results], ignore_index=True)
        all_raw = pd.concat([r.raw_text for r in results], ignore_index=True)

# --- Aggregate metrics shared across dashboard tabs ---

total_debits = float(pd.to_numeric(all_transactions.get("debit"), errors="coerce").fillna(0).sum()) if not all_transactions.empty else 0.0
total_credits = float(pd.to_numeric(all_transactions.get("credit"), errors="coerce").fillna(0).sum()) if not all_transactions.empty else 0.0
net_flow = total_credits - total_debits
statement_count = int(all_transactions["statement_id"].nunique()) if not all_transactions.empty else 0
tx_count = len(all_transactions)
high_risk_count = int((all_transactions.get("risk_level") == "high").sum()) if not all_transactions.empty else 0
medium_risk_count = int((all_transactions.get("risk_level") == "medium").sum()) if not all_transactions.empty else 0
avg_risk_score = float(pd.to_numeric(all_transactions.get("risk_score"), errors="coerce").fillna(0).mean()) if not all_transactions.empty else 0.0
flag_count = len(all_flags)
reconciliation_df = _build_reconciliation_table(all_transactions)
has_data = has_uploads and not all_transactions.empty
EMPTY_NOTE = "Upload a statement above, or click **Try it with sample statements**, to see results here."

# --- Main tabbed UI ---

st.markdown('<div style="height:0.6rem"></div>', unsafe_allow_html=True)
overview_tab, dashboard_tab, transactions_tab, risk_tab, reconciliation_tab, export_tab, template_tab = st.tabs(
    ["Summary", "Dashboard", "Transactions", "Red Flags", "Bank Reconciliation", "Download Workpapers", "Add a New Bank"]
)


def _feature(icon_path: str, title: str, text: str) -> str:
    return (
        f'<div class="feature"><div class="feature-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        f'stroke="{NAVY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f'<path d="{icon_path}"/></svg></div><h4>{title}</h4><p>{text}</p></div>'
    )


with overview_tab:
    if not has_data:
        # Welcome screen: what the app does, before anything is uploaded.
        st.markdown(
            '<div class="feature-grid">'
            + _feature("M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6", "Reads any bank",
                       "Upload a statement from any bank. Transactions are found automatically, with nothing to set up.")
            + _feature("M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11", "Checks the math",
                       "Each account is reconciled against the statement's own balances or printed totals, so you can see if anything was misread.")
            + _feature("M4 21V4M4 4h12l-2 4 2 4H4", "Spots red flags",
                       "Large, round-dollar, duplicate and out-of-sequence items are flagged for a closer look.")
            + _feature("M12 3v12M7 10l5 5 5-5M5 21h14", "Exports workpapers",
                       "Download a formatted Excel workpaper and summary financial statements for the case file.")
            + "</div>",
            unsafe_allow_html=True,
        )
        # Make the built-in bank list visible before anyone uploads anything.
        chips = "".join(f'<span class="bank-chip">{name}</span>' for name in FEATURED_BANKS)
        st.markdown(
            f'<div class="banks-panel"><h4>Works with any bank</h4>'
            f"<p>Upload statements from any bank or credit union. These {len(BANKS)} are also labelled by name "
            f"when the name is printed on the statement. Either way, the Bank Reconciliation tab checks that "
            f"every transaction was read correctly.</p>"
            f"<div class=\"bank-chips\">{chips}"
            f'<span class="bank-chip more">+ {len(BANKS) - len(FEATURED_BANKS)} more</span></div></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"See all {len(BANKS)} banks labelled by name"):
            st.dataframe(pd.DataFrame(directory_table()), width="stretch", hide_index=True, height=360)
    else:
        # Summary KPI cards: volume, risk, and cash flow totals.
        _kpis(
            [
                ("Statements", f"{statement_count}", f"{tx_count} transactions", ""),
                ("Money in", _money(total_credits), "Deposits and other credits", "green"),
                ("Money out", _money(total_debits), "Checks, withdrawals and debits", "gold"),
                ("Net change", _money(net_flow), "Money in minus money out", ""),
                ("Higher-risk items", f"{high_risk_count + medium_risk_count}", f"{high_risk_count} high · {medium_risk_count} medium", "red"),
            ]
        )
        c1, c2 = st.columns([1.5, 1])
        with c1:
            _section("Where the money went", "Number of transactions by category")
            category_chart = all_transactions["txn_category"].map(_display_category_name).value_counts().rename_axis("Category").reset_index(name="Transactions")
            st.altair_chart(
                alt.Chart(category_chart)
                .mark_bar(color=NAVY, cornerRadiusEnd=4, height=18)
                .encode(
                    x=alt.X("Transactions:Q", title=None, axis=alt.Axis(grid=False, tickMinStep=1)),
                    y=alt.Y("Category:N", sort="-x", title=None),
                    tooltip=["Category", "Transactions"],
                )
                .properties(height=max(160, 34 * len(category_chart)))
                .configure_view(stroke=None),
                width="stretch",
            )
        with c2:
            _section("Risk levels", "Every transaction is scored 0 to 100")
            risk_chart = (
                all_transactions["risk_level"].str.title().value_counts().reindex(["High", "Medium", "Low"], fill_value=0)
                .rename_axis("Risk").reset_index(name="Transactions")
            )
            st.altair_chart(
                alt.Chart(risk_chart)
                .mark_arc(innerRadius=58, cornerRadius=3)
                .encode(
                    theta="Transactions:Q",
                    color=alt.Color(
                        "Risk:N",
                        scale=alt.Scale(domain=list(RISK_COLORS), range=list(RISK_COLORS.values())),
                        legend=alt.Legend(orient="bottom", title=None),
                    ),
                    tooltip=["Risk", "Transactions"],
                )
                .properties(height=240)
                .configure_view(stroke=None),
                width="stretch",
            )

with dashboard_tab:
    if not has_data:
        st.info(EMPTY_NOTE)
    else:
        dash = dashboard.prepare(
            all_transactions, {c: _display_category_name(c) for c in all_transactions["txn_category"].dropna().unique()}
        )
        dated = dash["date"].dropna()
        # --- Filters: every chart, KPI and export below uses the same filtered rows ---
        with st.container(border=True):
            st.markdown('<div class="section-title" style="margin-top:0">Filters</div>', unsafe_allow_html=True)
            f1, f2, f3 = st.columns([1.3, 1.6, 1.6])
            first_day, last_day = (dated.min().date(), dated.max().date()) if not dated.empty else (None, None)
            date_range = f1.date_input("Dates", value=(first_day, last_day), min_value=first_day, max_value=last_day, format="MM/DD/YYYY") if first_day else ()
            accounts = sorted(dash["account"].unique())
            chosen_accounts = f2.multiselect("Statements and accounts", accounts, placeholder="All")
            categories = sorted(dash["category"].unique())
            chosen_categories = f3.multiselect("Transaction types", categories, placeholder="All")
            g1, g2, g3, g4 = st.columns([1.5, 1.0, 1.4, 1.2])
            direction = g1.segmented_control("Direction", ["All", "Money in", "Money out"], default="All")
            chosen_risk = g2.multiselect("Risk", ["High", "Medium", "Low"], placeholder="All")
            granularity = g3.segmented_control("Group by", ["Daily", "Weekly", "Monthly"], default="Weekly") or "Weekly"
            search = g4.text_input("Search descriptions", placeholder="casino, ATM, Zelle…")

        view = dash
        if len(date_range) == 2:
            view = view[(view["date"].dt.date >= date_range[0]) & (view["date"].dt.date <= date_range[1]) | view["date"].isna()]
        if chosen_accounts:
            view = view[view["account"].isin(chosen_accounts)]
        if chosen_categories:
            view = view[view["category"].isin(chosen_categories)]
        if direction == "Money in":
            view = view[view["money_in"] > 0]
        elif direction == "Money out":
            view = view[view["money_out"] > 0]
        if chosen_risk:
            view = view[view["risk"].isin(chosen_risk)]
        if search:
            view = view[view["description"].str.contains(search, case=False, na=False, regex=False)]

        if view.empty:
            st.warning("No transactions match these filters.")
        else:
            _kpis(
                [
                    ("Transactions", f"{len(view):,}", f"of {len(dash):,} in total", ""),
                    ("Money in", _money(view["money_in"].sum()), f"{int((view['money_in'] > 0).sum())} items", "green"),
                    ("Money out", _money(view["money_out"].sum()), f"{int((view['money_out'] > 0).sum())} items", "gold"),
                    ("Net change", _money(view["net"].sum()), "Money in minus money out", "blue"),
                    ("Higher-risk items", f"{int(view['flagged'].sum())}", _money(view.loc[view["flagged"], "amount"].sum()) + " total", "red"),
                ]
            )
            charts = [
                ("Cash flow over time", f"{granularity} money in and out, with the net change", dashboard.cash_flow(view, granularity)),
                ("Balance over time", "Printed running balance, or the cumulative net change where the statement has none", dashboard.balance_over_time(view)),
                ("Transaction types", "Dollar total per type; labels show the number of transactions", dashboard.category_totals(view)),
                ("Money out by type over time", f"{granularity} totals, stacked by type", dashboard.category_over_time(view, granularity)),
                ("Red flags: why transactions were flagged", "How often each rule fired on medium- and high-risk transactions", dashboard.flag_reasons(view)),
                ("Risk timeline", "Every transaction by date and amount; bigger dots score higher. Hover for the reasons.", dashboard.risk_timeline(view)),
                ("Top payees and merchants", "Where the most money went", dashboard.top_payees(view)),
                ("Day of the week", "Transactions per weekday (weekends in taupe)", dashboard.weekday_pattern(view)),
            ]
            layout = [(0, 1), (2, 3), (4, 5), (6, 7)]
            for left, right in layout:
                c1, c2 = st.columns(2)
                for column, (title, subtitle, fig) in ((c1, charts[left]), (c2, charts[right])):
                    with column:
                        _section(title, subtitle)
                        if title.startswith("Red flags") and not view["flagged"].any():
                            st.caption("No medium- or high-risk transactions in this selection.")
                        else:
                            st.plotly_chart(fig, width="stretch", config=dashboard.PLOTLY_CONFIG)

            _section("Export", "Exactly what the filters above select. Each chart also has a camera icon (top right) to save it as an image.")
            e1, e2, e3 = st.columns(3)
            stamp = f"{datetime.now():%Y%m%d_%H%M}"
            e1.download_button("Filtered transactions (.xlsx)", dashboard.to_excel(view), file_name=f"transactions_{stamp}.xlsx", icon=":material/table_view:", width="stretch")
            e2.download_button("Filtered transactions (.csv)", dashboard.export_frame(view).to_csv(index=False).encode(), file_name=f"transactions_{stamp}.csv", mime="text/csv", icon=":material/description:", width="stretch")
            report = dashboard.to_html_report(f"{APP_NAME}: dashboard", f"{ORG_NAME} · {len(view)} transactions · exported {datetime.now():%b %d, %Y}", [(t, f) for t, _, f in charts])
            e3.download_button("Interactive dashboard (.html)", report.encode(), file_name=f"dashboard_{stamp}.html", mime="text/html", icon=":material/monitoring:", width="stretch")

with transactions_tab:
    if not has_data:
        st.info(EMPTY_NOTE)
    else:
        f1, f2, f3 = st.columns([1.2, 1.1, 1.3])
        statement_options = sorted(all_transactions["statement_id"].dropna().unique().tolist())
        selected_statements = f1.multiselect("Statement", statement_options, default=statement_options)
        selected_risks = f2.multiselect("Risk level", ["high", "medium", "low"], default=["high", "medium", "low"], format_func=str.title)
        search_term = f3.text_input("Search descriptions", placeholder="ATM, check, deposit…")
        filtered = all_transactions.copy()
        if selected_statements:
            filtered = filtered[filtered["statement_id"].isin(selected_statements)]
        if selected_risks:
            filtered = filtered[filtered["risk_level"].isin(selected_risks)]
        if search_term:
            filtered = filtered[filtered["description"].str.contains(search_term, case=False, na=False)]
        # Chronological, like the statement itself.
        filtered = filtered.sort_values(["statement_id", "txn_date", "source_page", "source_line"])
        filtered["txn_category"] = filtered["txn_category"].map(_display_category_name)
        filtered["risk_badge"] = filtered["risk_level"].map(_risk_badge)
        st.caption(f"Showing {len(filtered)} of {tx_count} transactions")
        st.dataframe(
            _money_cells(filtered, ["debit", "credit", "running_balance"])[
                ["txn_date", "statement_id", "description", "txn_category", "debit", "credit", "running_balance", "risk_badge"]
            ],
            column_config={
                "txn_date": DATE_COLUMN,
                "statement_id": "Statement",
                "description": st.column_config.TextColumn("Description", width="medium"),
                "txn_category": "Category",
                "debit": _money_text_column("Money out"),
                "credit": _money_text_column("Money in"),
                "running_balance": _money_text_column("Balance"),
                "risk_badge": "Risk",
            },
            width="stretch",
            hide_index=True,
            height=480,
        )

with risk_tab:
    if not has_data:
        st.info(EMPTY_NOTE)
    else:
        _kpis(
            [
                ("High risk", f"{high_risk_count}", "Look at these first", "red"),
                ("Medium risk", f"{medium_risk_count}", "Worth a second look", "gold"),
                ("Flags raised", f"{flag_count}", "Duplicates, gaps, large items and more", ""),
            ]
        )
        _section("Highest-risk transactions", "Sorted by risk score; the reasons column explains each score")
        high_risk = all_transactions[all_transactions["risk_level"].isin(["high", "medium"])].sort_values("risk_score", ascending=False).copy()
        high_risk["risk_badge"] = high_risk["risk_level"].map(_risk_badge)
        st.dataframe(
            high_risk[["txn_date", "description", "amount", "risk_score", "risk_badge", "risk_reasons"]].head(50),
            column_config={
                "txn_date": DATE_COLUMN,
                "description": st.column_config.TextColumn("Description", width="medium"),
                "amount": st.column_config.NumberColumn("Amount", **MONEY_COLUMN),
                "risk_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "risk_badge": "Risk",
                "risk_reasons": st.column_config.TextColumn("Why it was flagged", width="large"),
            },
            width="stretch",
            hide_index=True,
        )
        if not all_flags.empty:
            _section("All flags", "Every rule that fired, by severity")
            flags_view = all_flags.copy()
            flags_view["severity_badge"] = flags_view["severity"].map(_severity_badge)
            flags_view["flag_type"] = flags_view["flag_type"].str.replace("_", " ").str.capitalize()
            st.dataframe(
                flags_view[["severity_badge", "flag_type", "message", "txn_date", "amount"]],
                column_config={
                    "severity_badge": "Severity",
                    "flag_type": "Flag",
                    "message": st.column_config.TextColumn("Details", width="large"),
                    "txn_date": "Date",
                    "amount": st.column_config.NumberColumn("Amount", **MONEY_COLUMN),
                },
                width="stretch",
                hide_index=True,
            )

with reconciliation_tab:
    if not has_data:
        st.info(EMPTY_NOTE)
    else:
        _section(
            "Bank reconciliation",
            "Checks that every transaction was read: against the running balance, the totals printed on the statement, or its opening and closing balances",
        )
        for _, rec in reconciliation_df.iterrows():
            status_class = {"Reconciled": "ok", "Variance": "bad"}.get(rec["status"], "warn")
            account = f" · {rec['account_number']}" if pd.notna(rec["account_number"]) else ""
            card = rec["statement_kind"] == "credit_card"
            money_in, money_out = ("Payments and credits", "Charges") if card else ("Money in", "Money out")
            if rec["method"] == "control_totals":
                printed_items = f" ({int(rec['printed_items'])} items)" if pd.notna(rec["printed_items"]) else ""
                math = (
                    f'<span>{money_in}</span><span>{_money(rec["total_credits"])}</span>'
                    f'<span>− {money_out}</span><span>{_money(rec["total_debits"])}</span>'
                    f'<span class="total">= Net change read ({int(rec["items"])} items)</span><span class="total">{_money(rec["total_credits"] - rec["total_debits"])}</span>'
                    f'<span>Net change printed on statement{printed_items}</span><span>{_money(rec["printed_net"])}</span>'
                    f'<span class="total">Difference</span><span class="total">{_money(rec["reconciliation_difference"])}</span>'
                )
            elif rec["method"] in ("running_balance", "summary_balance"):
                opening_label = "Previous balance" if card else "Beginning balance"
                closing_label = "New balance on statement" if card else "Ending balance on statement"
                plus, minus = (money_out, money_in) if card else (money_in, money_out)
                plus_value, minus_value = (rec["total_debits"], rec["total_credits"]) if card else (rec["total_credits"], rec["total_debits"])
                math = (
                    f'<span>{opening_label}</span><span>{_money(rec["beginning_balance"])}</span>'
                    f'<span>+ {plus}</span><span>{_money(plus_value)}</span>'
                    f'<span>− {minus}</span><span>{_money(minus_value)}</span>'
                    f'<span class="total">= Expected ending balance</span><span class="total">{_money(rec["expected_ending_balance"])}</span>'
                    f'<span>{closing_label}</span><span>{_money(rec["ending_balance"])}</span>'
                    f'<span class="total">Difference</span><span class="total">{_money(rec["reconciliation_difference"])}</span>'
                )
            else:
                math = (
                    f'<span>{money_in}</span><span>{_money(rec["total_credits"])}</span>'
                    f'<span>{money_out}</span><span>{_money(rec["total_debits"])}</span>'
                )
            st.markdown(
                f'<div class="recon-card"><div class="recon-head"><span class="title">{rec["statement_id"]}{account}</span>'
                f'<span class="status {status_class}">{rec["status"]}</span></div>'
                f'<div class="recon-math">{math}</div><div class="recon-note">{rec["notes"]}</div></div>',
                unsafe_allow_html=True,
            )

with export_tab:
    if not has_data:
        st.info(EMPTY_NOTE)
    else:
        # Build Excel byte streams for forensic workpaper and summarized financial statements.
        workpaper_bytes = build_workpaper(all_transactions, all_flags, all_raw if include_raw_text else pd.DataFrame(), datetime.now())
        financial_bytes = build_financial_statements(all_transactions, reconciliation_df, datetime.now())
        d1, d2 = st.columns(2)
        with d1:
            st.markdown(
                '<div class="download-card"><h4>Forensic workpaper</h4><p>Every transaction with its category, risk score '
                "and reasons, plus a summary and a review list of flagged items.</p></div>",
                unsafe_allow_html=True,
            )
            st.download_button("Download workpaper (.xlsx)", data=BytesIO(workpaper_bytes).getvalue(), file_name=f"forensic_workpaper_{datetime.now():%Y%m%d_%H%M%S}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", icon=":material/download:", width="stretch")
        with d2:
            st.markdown(
                '<div class="download-card"><h4>Financial statements</h4><p>A management summary, statement of activities '
                "by month, and cash position from the bank reconciliation.</p></div>",
                unsafe_allow_html=True,
            )
            st.download_button("Download financial statements (.xlsx)", data=BytesIO(financial_bytes).getvalue(), file_name=f"financial_statements_{datetime.now():%Y%m%d_%H%M%S}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:", width="stretch")

with template_tab:
    # One-click onboarding: upload a statement from a new bank, check what was read, save it.
    _section("Add a new bank", "")
    st.markdown(
        '<div class="section-card">You don\'t need to add a bank to use it: statements from any bank are read automatically. '
        "Saving a bank here only labels its statements by name (and lets you check what the app reads first). "
        "Upload one of its statements, check the preview, and click <b>Save this bank</b>.</div>",
        unsafe_allow_html=True,
    )
    with st.expander(f"Banks already labelled by name ({len(BANKS)})"):
        st.dataframe(pd.DataFrame(directory_table()), width="stretch", hide_index=True, height=360)
    sample_upload = st.file_uploader("Upload one statement from the bank", type=["pdf"], key="template_sample_upload")
    if sample_upload is not None:
        with st.spinner("Reading the statement…"):
            analysis = _analyze_cached(sample_upload.name, sample_upload.getvalue(), _templates_key())
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
                _money_cells(analysis.preview.head(15), ["debit", "credit", "running_balance"]),
                column_config={
                    "txn_date": DATE_COLUMN,
                    "description": st.column_config.TextColumn("Description", width="large"),
                    "debit": _money_text_column("Money out"),
                    "credit": _money_text_column("Money in"),
                    "running_balance": _money_text_column("Balance"),
                },
                width="stretch",
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
    _section("Saved banks")
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
            width="stretch",
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
