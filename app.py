"""
Streamlit front-end for Bank Statement Analyzer.

Upload bank statement PDFs, parse transactions, review risk/reconciliation
dashboards, export Excel workpapers, and manage custom bank-format templates.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from html import escape
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List

import altair as alt
import pandas as pd
import streamlit as st

import dashboard
import fraud_rules
import pdf_text
import projects
from authenticity import WARN, checks_frame, verdict
from auto_parser import CREDIT_WORDS
from bank_directory import BANKS, directory_table

BANK_NAMES = {bank["name"] for bank in BANKS}
from financial_statements import build_financial_statements
from statement_parser import BUILT_IN_FORMAT_NAMES, ParseResult, analyze_statement, parse_statement
from reconciliation import build_reconciliation_table
from template_manager import delete_template, extract_preview_text, load_templates, save_template
from version import APP_VERSION
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
ORG_URL = "https://www.justiceforfraudvictimsproject.org/"
# Shades of the palette used to separate areas of the page.
PAGE_BG = "#F4F5F7"  # light gray page behind the white cards
BLUE_TINT = "#E8EFF6"  # pale blue for icons, highlights and the sidebar
BLUE_LINE = "#C5D4E3"  # blue-gray borders
RISK_COLORS = {"High": "#B42318", "Medium": "#D97706", "Low": "#15803D"}

APP_DIR = Path(__file__).resolve().parent
REPO_URL = "https://github.com/jdaiken/parsing_tool"
# Opens VS Code and offers to clone the repository (needs VS Code installed).
VSCODE_CLONE_URL = "vscode://vscode.git/clone?url=https%3A%2F%2Fgithub.com%2Fjdaiken%2Fparsing_tool.git"
# Streamlit Community Cloud runs apps from /mount/src. Its disk is shared by every visitor, so
# projects there are kept per browser session only, and users are told to download them.
HOSTED = str(APP_DIR).startswith("/mount/src")
# The server version (deploy/server) runs on an organization's own server, behind its sign-in.
# BSA_APPROVED_SERVER=1 says the organization has approved that server for case data;
# BSA_USER_HEADER names the header its sign-in proxy sets to the signed-in person, so each
# person sees only their own projects.
APPROVED_SERVER = os.environ.get("BSA_APPROVED_SERVER") == "1"
USER_HEADER = os.environ.get("BSA_USER_HEADER", "").strip()
# Files that make up the app, for "Download the app"; never projects/ or saved banks.
APP_FILE_PATTERNS = [
    "*.py", "*.pdf", "*.md", "requirements.txt", "requirements-lock.txt", "index.html", ".gitignore", ".nojekyll",
    ".dockerignore", "start.bat", "start.sh", ".streamlit/config.toml", ".vscode/*.json", ".github/*.yml",
    ".github/workflows/*.yml", "assets/*", "assets/fonts/*", "demo/*", "docs/*.md", "deploy/*/*", "tools/*.py", "tests/*.py",
]
# The fictional demo case in demo/ (see demo/ANSWER_KEY.md): three months of checking and a credit card,
# and separately a doctored "family copy" of April next to the genuine April statement.
SAMPLE_CASE = ["demo/1_checking_2025-03.pdf", "demo/2_checking_2025-04.pdf", "demo/3_checking_2025-05.pdf", "demo/4_credit_card_2025-05.pdf"]
SAMPLE_DOCTORED = ["demo/2_checking_2025-04.pdf", "demo/5_checking_2025-04_family_copy.pdf"]

st.set_page_config(page_title=APP_NAME, page_icon=":material/account_balance:", layout="wide")


@st.cache_resource(show_spinner=False)
def _font_faces() -> str:
    """The brand fonts, embedded so the page never calls an outside font service (assets/fonts, SIL Open Font License)."""
    faces = (
        ("Inter", "inter-latin-wght-normal.woff2", "normal", "100 900"),
        ("Jost", "jost-latin-wght-normal.woff2", "normal", "100 900"),
        ("Cormorant Garamond", "cormorant-garamond-latin-wght-italic.woff2", "italic", "300 700"),
    )
    css = []
    for family, file_name, style, weights in faces:
        path = APP_DIR / "assets" / "fonts" / file_name
        if path.exists():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            css.append(
                f"@font-face {{font-family: '{family}'; font-style: {style}; font-weight: {weights}; font-display: swap; "
                f"src: url(data:font/woff2;base64,{data}) format('woff2');}}"
            )
    return "\n".join(css)


def _logo_html() -> str:
    """The organization's logo if one was added to assets/, otherwise a scales-of-justice mark."""
    for name, mime in (("logo.svg", "image/svg+xml"), ("logo.png", "image/png"), ("logo.jpg", "image/jpeg")):
        path = APP_DIR / "assets" / name
        if path.exists():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return (
                f'<a class="brand-link" href="{ORG_URL}" target="_blank" rel="noopener noreferrer" title="Visit {ORG_NAME}">'
                f'<img class="brand-logo" src="data:{mime};base64,{encoded}" alt="{ORG_NAME} logo"></a>'
            )
    return (
        f'<div class="brand-mark"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M12 3v18M5 21h14M4 7h16M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0z"/></svg></div>'
    )


st.markdown(
    f"""
    <style>
    {_font_faces()}
    .stApp, .stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea, .stApp li, .stApp h1, .stApp h2,
    .stApp h3, .stApp h4, .stApp h5, .stApp [data-baseweb="tab"] {{
        font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;}}
    .stApp {{background: {PAGE_BG};}}
    .stApp a {{color: {BLUE};}}
    /* Inputs stay white so they stand out on the gray page. */
    .stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"], .stApp [data-baseweb="select"] > div,
    .stApp [data-testid="stNumberInputContainer"], .stApp [data-baseweb="input"] input, .stApp textarea {{background: #FFFFFF;}}
    .stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"], .stApp [data-baseweb="select"] > div {{border-color: {BLUE_LINE};}}
    .stApp [data-testid="stIconMaterial"] {{font-family: 'Material Symbols Rounded' !important;}}
    /* Hide Streamlit's menu and decoration, but not the toolbar itself: it holds the button that reopens the sidebar. */
    #MainMenu, [data-testid="stToolbarActions"], [data-testid="stDecoration"], footer {{visibility: hidden; height: 0;}}
    /* Streamlit's (hidden) top bar still takes space; start the page below it so the logo is never cut off. */
    header[data-testid="stHeader"] {{background: transparent;}}
    .block-container {{padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1180px;}}
    h1, h2, h3, h4, h5 {{color: {NAVY}; letter-spacing: -0.01em;}}

    .brand {{border-radius: 14px; overflow: hidden; box-shadow: 0 10px 30px rgba(29, 40, 68, 0.16); border: 1px solid #DADDE3;}}
    .brand-top {{display: flex; align-items: center; justify-content: space-between; gap: 1rem;
                 background: #FFFFFF; padding: 1.1rem 1.6rem; min-height: 92px; border-bottom: 4px solid {BLUE};}}
    .brand-link {{display: block; flex: none; border-radius: 8px; transition: opacity 0.15s ease, transform 0.15s ease;}}
    .brand-link:hover {{opacity: 0.85; transform: translateY(-1px);}}
    .brand-logo {{height: 64px; width: auto; flex: none; display: block; object-fit: contain;}}
    .brand-mark {{width: 52px; height: 52px; flex: none; border-radius: 50%; background: {NAVY};
                  display: flex; align-items: center; justify-content: center;}}
    .brand-band {{position: relative; overflow: hidden; background: linear-gradient(100deg, #8A877A 0%, {TAUPE} 55%, #9C998D 100%);
                  color: #FFFFFF; padding: 1.6rem 1.8rem 1.5rem 1.8rem;}}
    .brand-band::after {{content: ""; position: absolute; right: -40px; top: -60px; width: 260px; height: 260px;
                         border-radius: 50%; border: 1px solid rgba(255,255,255,0.18);}}
    .brand-name {{font-family: 'Cormorant Garamond', Georgia, serif; font-style: italic; font-weight: 600;
                  font-size: 2.6rem; line-height: 1.05; color: #FFFFFF;}}
    .brand-tagline {{font-family: 'Jost', system-ui, sans-serif; font-weight: 300; font-size: 1.08rem; color: #F4F2EC; margin-top: 0.45rem;}}
    .brand-privacy {{font-family: 'Jost', system-ui, sans-serif; font-weight: 400; font-size: 0.9rem; color: #FFFFFF; margin-top: 0.7rem;}}

    .section-title {{font-family: 'Jost', system-ui, sans-serif; font-size: 1.15rem; font-weight: 500; color: {NAVY}; margin: 1.6rem 0 0.2rem 0;
                     padding-left: 0.65rem; border-left: 4px solid {BLUE}; line-height: 1.25;}}
    .section-sub {{font-size: 0.9rem; color: #5B6575; margin-bottom: 0.6rem; padding-left: calc(0.65rem + 4px);}}
    [data-testid="stFileUploaderDropzone"] {{border: 2px dashed {BLUE_LINE}; background: #FFFFFF; border-radius: 12px;}}
    [data-testid="stFileUploaderDropzone"]:hover {{border-color: {BLUE}; background: {BLUE_TINT};}}

    .feature-grid {{display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.9rem; margin-top: 0.4rem;}}
    .feature {{background: #FFFFFF; border: 1px solid #E1E5EB; border-top: 3px solid {BLUE}; border-radius: 14px; padding: 1.1rem 1.15rem;
               box-shadow: 0 2px 8px rgba(29, 40, 68, 0.06);}}
    .feature-icon {{width: 38px; height: 38px; border-radius: 10px; background: {BLUE_TINT}; display: flex;
                    align-items: center; justify-content: center; margin-bottom: 0.7rem;}}
    .feature h4 {{margin: 0 0 0.3rem 0; font-size: 0.98rem; color: {NAVY};}}
    .feature p {{margin: 0; font-size: 0.86rem; color: #5B6575; line-height: 1.45;}}

    .kpi-grid {{display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.8rem; margin: 0.6rem 0 1rem 0;}}
    .kpi {{background: #FFFFFF; border: 1px solid #E3E7EE; border-top: 3px solid {NAVY}; border-radius: 12px;
           padding: 0.85rem 1rem; box-shadow: 0 2px 8px rgba(29, 40, 68, 0.06);}}
    .kpi.gold {{border-top-color: {TAUPE};}}
    .kpi.blue {{border-top-color: {BLUE};}}
    .kpi.red {{border-top-color: {RISK_COLORS['High']};}}
    .kpi.green {{border-top-color: {RISK_COLORS['Low']};}}
    .kpi-label {{font-size: 0.75rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: #6B7280;}}
    .kpi-value {{font-size: 1.55rem; font-weight: 700; color: #111827; margin-top: 0.2rem; font-variant-numeric: tabular-nums;}}
    .kpi-sub {{font-size: 0.8rem; color: #6B7280; margin-top: 0.1rem;}}

    .file-list {{display: flex; flex-direction: column; gap: 0.35rem; margin: 0.4rem 0 0.2rem 0;}}
    .file-row {{display: flex; align-items: center; gap: 0.6rem; font-size: 0.88rem; color: #1F2937;
                background: #FFFFFF; border: 1px solid #E1E5EB; border-left: 3px solid {BLUE}; border-radius: 10px; padding: 0.45rem 0.75rem;}}
    .file-row .meta {{color: #6B7280; margin-left: auto; font-size: 0.8rem;}}
    .status {{display: inline-block; font-size: 0.75rem; font-weight: 600; padding: 0.15rem 0.6rem; border-radius: 999px;}}
    .status.ok {{background: #E7F6EC; color: #15803D;}}
    .status.warn {{background: #FEF3E2; color: #B45309;}}
    .status.bad {{background: #FDECEA; color: #B42318;}}

    .recon-card {{background: #FFFFFF; border: 1px solid #E1E5EB; border-radius: 14px; padding: 1rem 1.15rem; margin-bottom: 0.8rem;
                  box-shadow: 0 2px 8px rgba(29, 40, 68, 0.05);}}
    .recon-head {{background: {LIGHT}; margin: -1rem -1.15rem 0.7rem -1.15rem; padding: 0.65rem 1.15rem; border-radius: 14px 14px 0 0;
                  border-bottom: 1px solid #E1E5EB;}}
    .recon-head {{display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.6rem;}}
    .recon-head .title {{font-weight: 600; color: {NAVY};}}
    .recon-math {{display: grid; grid-template-columns: 1fr auto; row-gap: 0.25rem; max-width: 420px;
                  font-size: 0.9rem; color: #374151; font-variant-numeric: tabular-nums;}}
    .recon-math .total {{border-top: 1px solid #D1D5DB; padding-top: 0.25rem; font-weight: 600; color: #111827;}}
    .findings {{display: grid; gap: 0.6rem; margin-bottom: 1rem;}}
    .finding {{background: #FFFFFF; border: 1px solid #E1E5EB; border-left: 4px solid #D97706; border-radius: 12px; padding: 0.75rem 1rem;
               box-shadow: 0 2px 8px rgba(29, 40, 68, 0.05);}}
    .finding.high {{border-left-color: #B42318;}}
    .finding.low {{border-left-color: #15803D;}}
    .finding-head {{display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;}}
    .finding-head .title {{font-weight: 600; color: {NAVY};}}
    .finding-head .acct {{margin-left: auto; font-size: 0.78rem; color: #6B7280;}}
    .finding p {{margin: 0.35rem 0 0; font-size: 0.88rem; color: #374151;}}
    .doc-intro {{font-size: 0.92rem; color: #374151; max-width: 860px;}}
    .doc-row {{display: grid; grid-template-columns: 8.5rem 1fr; gap: 0.75rem; padding: 0.55rem 0; border-top: 1px solid #EEF1F5;}}
    .doc-row .status {{justify-self: start; align-self: start;}}
    .doc-name {{font-weight: 600; color: #1F2937; font-size: 0.9rem;}}
    .doc-detail {{font-size: 0.86rem; color: #4B5563;}}
    .doc-example {{font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; color: #7C2D12;
        background: #FFF7ED; border-radius: 6px; padding: 0.15rem 0.45rem; margin-top: 0.25rem;}}
    .status.muted {{background: #F3F4F6; color: #6B7280;}}
    .doc-warn {{color: #B42318;}}
    .project-head {{background: linear-gradient(100deg, {BLUE_TINT} 0%, #FFFFFF 70%); border: 1px solid #E1E5EB; border-left: 4px solid {BLUE};
                    border-radius: 12px; padding: 0.8rem 1.1rem; margin-bottom: 0.6rem;}}
    .project-head .project-name {{color: {NAVY}; font-size: 1.3rem; font-weight: 600;}}
    .project-head p {{margin: 0.2rem 0; color: #374151; font-size: 0.9rem;}}
    .project-head span {{font-size: 0.78rem; color: #6B7280;}}
    .stApp p.side-note {{font-size: 0.85rem; color: #4B5563; margin-bottom: 0.4rem; line-height: 1.45;}}
    .recon-note {{font-size: 0.82rem; color: #6B7280; margin-top: 0.5rem;}}

    .download-card {{background: #FFFFFF; border: 1px solid #E1E5EB; border-top: 3px solid {BLUE}; border-radius: 14px; padding: 1.1rem 1.15rem;
                     min-height: 150px; box-shadow: 0 2px 8px rgba(29, 40, 68, 0.06);}}
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
    /* Tabs as a gray rail with the open tab raised in white. Two sets of selectors: newer Streamlit
       (role="tab", data-testid="stTab") and older versions, such as the in-browser build (baseweb). */
    .stTabs [role="tablist"] {{gap: 0.05rem; background: #E7EAEF; border-radius: 12px; padding: 0.3rem; border-bottom: none;}}
    .stTabs [role="tab"] {{border-radius: 9px; padding: 0.4rem 0.45rem; color: #4B5563; transition: background 0.15s ease;}}
    .stTabs [role="tab"] p {{font-family: 'Jost', system-ui, sans-serif; font-size: 0.93rem; white-space: nowrap;}}
    .stTabs [role="tab"]:hover {{background: #F5F6F8; color: {NAVY};}}
    .stTabs [role="tab"][aria-selected="true"] {{color: {NAVY}; background: #FFFFFF; box-shadow: 0 1px 3px rgba(29, 40, 68, 0.16);}}
    .stTabs [role="tab"][aria-selected="true"] p {{font-weight: 500;}}
    .stTabs .react-aria-SelectionIndicator, .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{display: none;}}
    div[data-testid="stMetric"] {{background: #FFFFFF; border: 1px solid #E3E7EE; border-radius: 12px; padding: 0.75rem 0.95rem;}}
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {{border-radius: 10px; font-weight: 600;}}
    .stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"], .stFormSubmitButton > button[kind="secondaryFormSubmit"],
    .stLinkButton > a[kind="secondary"], [data-testid="stPopover"] button {{background: #FFFFFF; border: 1px solid {BLUE_LINE}; color: {NAVY};}}
    .stButton > button[kind="secondary"]:hover, .stDownloadButton > button[kind="secondary"]:hover,
    .stFormSubmitButton > button[kind="secondaryFormSubmit"]:hover, .stLinkButton > a[kind="secondary"]:hover {{border-color: {BLUE}; background: {BLUE_TINT}; color: {NAVY};}}
    [data-testid="stExpander"] details {{background: #FFFFFF; border: 1px solid #E1E5EB; border-radius: 10px;}}
    [data-testid="stDataFrame"], [data-testid="stDataEditor"] {{background: #FFFFFF; border-radius: 10px; box-shadow: 0 2px 8px rgba(29, 40, 68, 0.05);}}
    section[data-testid="stSidebar"] {{background: linear-gradient(180deg, {BLUE_TINT} 0%, #F1F4F8 100%); border-right: 1px solid {BLUE_LINE};}}
    section[data-testid="stSidebar"] h4 {{color: {NAVY}; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
                                          border-bottom: 1px solid {BLUE_LINE}; padding-bottom: 0.35rem; margin-top: 0.6rem;}}
    .app-footer {{margin-top: 3rem; padding: 1rem; border-radius: 12px; background: {NAVY};
                  font-size: 0.8rem; color: #D6DEE8; text-align: center;}}
    .app-footer a {{color: #FFFFFF !important; text-decoration: none; border-bottom: 1px solid rgba(255,255,255,0.4);}}
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
elif APPROVED_SERVER:
    privacy_note = "Runs on your organization's approved server"

st.markdown(
    f"""
    <div class="brand">
      <div class="brand-top">
        {_logo_html()}
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
# On a server (Streamlit Cloud or any other), uploads leave the user's computer. Say so, unless the
# organization running the server has approved it for case data and set BSA_APPROVED_SERVER=1.
RUNS_ON_SERVER = not privacy_note
if RUNS_ON_SERVER:
    st.error(
        "**Demonstration copy: don't upload real case statements here.** This copy runs on a shared server, so files "
        "uploaded to it leave your computer. For real cases, use the version that runs on your computer or your "
        "organization's own copy.",
        icon=":material/gpp_maybe:",
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


# --- Sidebar: global options that affect parsing and export ---

if USER_HEADER:
    # One projects folder per signed-in person; the folder name is a fingerprint of who they are.
    signed_in = st.context.headers.get(USER_HEADER, "").strip().lower()
    if not signed_in:
        st.error("Sign-in required: this copy only works through your organization's sign-in page.", icon=":material/lock:")
        st.stop()
    PROJECTS_BASE = projects.PROJECTS_DIR / "users" / hashlib.sha256(signed_in.encode("utf-8")).hexdigest()[:32]
    PROJECTS_BASE.mkdir(parents=True, exist_ok=True)
elif HOSTED or RUNS_ON_SERVER:
    # A shared server nobody approved: keep projects for this browser session only.
    PROJECTS_BASE = Path(st.session_state.setdefault("projects_dir", tempfile.mkdtemp(prefix="projects-")))
else:
    PROJECTS_BASE = projects.PROJECTS_DIR


@st.cache_data(show_spinner=False)
def _app_zip(stamp: tuple) -> bytes:
    """The app's own files as a .zip, to open in VS Code. `stamp` changes when a file does."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, _ in stamp:
            zf.write(APP_DIR / path, f"bank-statement-analyzer/{path}")
    return buffer.getvalue()


def _app_files() -> tuple:
    found = {p for pattern in APP_FILE_PATTERNS for p in APP_DIR.glob(pattern) if p.is_file() and "__pycache__" not in p.parts}
    return tuple(sorted((p.relative_to(APP_DIR).as_posix(), p.stat().st_mtime) for p in found))


# A project picked in a form is applied before the picker is drawn on the next run.
if "open_project" in st.session_state:
    st.session_state["project"] = st.session_state.pop("open_project")
project_list = projects.list_projects(PROJECTS_BASE)
project_names = {p["slug"]: p["name"] + ("" if p["encrypted"] else " (not password-protected)") for p in project_list}
if st.session_state.get("project") not in project_names:
    st.session_state["project"] = ""
# Keys of the projects unlocked in this browser session; never written anywhere.
project_keys = st.session_state.setdefault("project_keys", {})


def _clear_session(keep_projects_dir: bool = True) -> None:
    """Forget everything this session holds: unlocked keys, uploads, cached statement text and results."""
    pdf_text._CACHE.clear()
    st.cache_data.clear()
    keep = {"projects_dir": st.session_state.get("projects_dir")} if keep_projects_dir else {}
    st.session_state.clear()
    st.session_state.update({k: v for k, v in keep.items() if v})


with st.sidebar:
    st.markdown("#### Project")
    st.selectbox(
        "Open a project",
        [""] + list(project_names),
        format_func=lambda slug: project_names.get(slug, "No project (quick look)"),
        key="project",
        help="A project keeps a case's statements and your notes together, encrypted with its password.",
    )
    if st.session_state["project"] in project_keys:
        if st.button("Lock project", icon=":material/lock:", width="stretch",
                     help="Forget this project's password in this session. You'll need the password to open it again."):
            project_keys.pop(st.session_state["project"], None)
            st.session_state["open_project"] = ""
            st.rerun()
    with st.expander("New project", icon=":material/create_new_folder:"):
        with st.form("new_project", clear_on_submit=True, border=False):
            new_name = st.text_input("Project name", placeholder="Case 2025-014",
                                     help="The name is the only thing stored unencrypted. Use a case number, not a person's name.")
            new_description = st.text_area("Description (optional)", height=70)
            new_password = st.text_input("Password", type="password", help=f"At least {projects.MIN_PASSWORD} characters.")
            new_password_again = st.text_input("Password again", type="password")
            st.caption("Everything in the project is encrypted with this password. A lost password can't be recovered: "
                       "keep it in your organization's password manager.")
            if st.form_submit_button("Create project", type="primary"):
                try:
                    if new_password != new_password_again:
                        raise ValueError("The two passwords don't match.")
                    slug, key = projects.create_project(new_name, new_description, new_password, PROJECTS_BASE)
                    project_keys[slug] = key
                    st.session_state["open_project"] = slug
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    with st.expander("Open a project file", icon=":material/folder_open:"):
        project_file = st.file_uploader("Project file (.bsacase)", type=["bsacase", "zip"], label_visibility="collapsed")
        project_file_password = st.text_input("The file's password", type="password", key="project_file_password",
                                              help="For an older unencrypted .zip, type a new password to protect it with.")
        if project_file is not None and st.button("Open this project"):
            try:
                slug, key = projects.import_case(project_file.getvalue(), project_file_password, PROJECTS_BASE)
                project_keys[slug] = key
                st.session_state["open_project"] = slug
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if PROJECTS_BASE.name.startswith("projects-"):
        st.caption(
            "On this hosted version, projects last until you close the tab. Download a project (Project tab) "
            "to keep it, or run the app on your computer, where projects are saved in its projects folder."
        )

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
    analyst = st.text_input("Analyst (printed on workpapers)", key="analyst", placeholder="Your name")
    st.caption(f"Banks you've added: {len(load_templates())}")
    if st.button("Clear this session", icon=":material/mop:", width="stretch",
                 help="Forgets uploads, results and unlocked projects in this browser tab. Saved projects stay saved."):
        _clear_session()
        st.rerun()

    st.markdown("#### Work on it in VS Code")
    st.markdown(
        '<p class="side-note">Get your own copy of the app to run, or change, on your computer. Run locally, '
        "statements never leave your machine.</p>",
        unsafe_allow_html=True,
    )
    st.link_button("Open in VS Code", VSCODE_CLONE_URL, icon=":material/code:", width="stretch",
                   help="Opens VS Code and copies the app from GitHub. Needs VS Code and Git installed.")
    st.download_button("Download the app (.zip)", data=_app_zip(_app_files()), file_name="bank-statement-analyzer.zip",
                       mime="application/zip", icon=":material/download:", width="stretch")
    with st.expander("Then what?"):
        st.markdown(
            "1. Install [Python](https://www.python.org/downloads/) and [VS Code](https://code.visualstudio.com/).\n"
            "2. Unzip the download. In VS Code choose **File → Open Folder** and pick the folder.\n"
            "3. Choose **Terminal → Run Task → Start the app**. The first start installs what the app needs "
            "(a few minutes); then it opens in your browser.\n\n"
            f"Without VS Code: double-click `start.bat` (Windows) or run `./start.sh` (Mac/Linux). The code is also on [GitHub]({REPO_URL})."
        )

# --- File upload and parsing ---

current_project = None
open_slug = st.session_state["project"]
project_key = project_keys.get(open_slug)
if open_slug and projects.is_encrypted(open_slug, PROJECTS_BASE) and project_key is None:
    # A protected project stays closed until its password is typed in this session.
    _section(f"{project_names[open_slug]} is locked", "Type the project's password to open it.")
    with st.form("unlock_project", border=False):
        unlock_password = st.text_input("Password", type="password")
        if st.form_submit_button("Unlock", type="primary", icon=":material/lock_open:"):
            try:
                project_keys[open_slug] = projects.unlock(open_slug, unlock_password, PROJECTS_BASE)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.stop()
if open_slug:
    current_project = projects.load_project(open_slug, PROJECTS_BASE, project_key)
if current_project:
    _section(
        f"Statements in {current_project['name']}",
        "Statements you add are saved in this project. Notes, and removing a statement, are on the Project tab.",
    )
else:
    _section(
        "Upload statements",
        "Drop in one or more statement PDFs: downloaded from online banking, scanned, or redacted. Scans take a few seconds per page.",
    )
uploads = st.file_uploader(
    "Upload bank statement PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    key=f"uploads_{st.session_state['project']}",
)
if current_project:
    # Each upload is copied into the project once (so removing it later doesn't bring it back).
    seen = st.session_state.setdefault("saved_uploads", set())
    fresh = [u for u in uploads or [] if (current_project["slug"], u.file_id) not in seen]
    if fresh:
        added = projects.add_files(current_project["slug"], [(u.name, u.getvalue()) for u in fresh], PROJECTS_BASE, project_key)
        seen.update((current_project["slug"], u.file_id) for u in fresh)
        if added:
            st.toast(f"Saved to {current_project['name']}: {', '.join(added)}", icon=":material/folder:")
        current_project = projects.load_project(current_project["slug"], PROJECTS_BASE, project_key)
    uploads = []
if uploads:
    st.session_state["use_samples"] = None
SAMPLE_SETS = {"case": SAMPLE_CASE, "doctored": SAMPLE_DOCTORED}
sample_col, doctored_col, clear_col, _ = st.columns([1.6, 1.6, 1, 1.4])
if not uploads and not current_project and all((APP_DIR / name).exists() for name in SAMPLE_CASE + SAMPLE_DOCTORED):
    if sample_col.button("Try it with sample statements", icon=":material/description:", help="A fictional elder-fraud case: 3 months of checking and a credit card"):
        st.session_state["use_samples"] = "case"
    if doctored_col.button("Try a doctored statement", icon=":material/policy:", help="A genuine statement next to an edited copy of it"):
        st.session_state["use_samples"] = "doctored"
    if st.session_state.get("use_samples") and clear_col.button("Clear samples"):
        st.session_state["use_samples"] = None
        st.rerun()

statement_files = list(uploads or [])
if current_project:
    statement_files = [_BundledFile(name, data) for name, data in projects.read_files(current_project["slug"], PROJECTS_BASE, project_key)]
elif not statement_files and st.session_state.get("use_samples") in SAMPLE_SETS:
    statement_files = [
        _BundledFile(Path(name).name, (APP_DIR / name).read_bytes()) for name in SAMPLE_SETS[st.session_state["use_samples"]]
    ]
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
    "section",
    "balance_check",
    "source_file",
    "source_sha256",
]
flag_columns = ["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"]

all_transactions = pd.DataFrame(columns=tx_columns)
all_flags = pd.DataFrame(columns=flag_columns)
all_raw = pd.DataFrame(columns=["statement_id", "page", "text"])
results: List[ParseResult] = []
file_names: List[str] = []
findings: List[fraud_rules.Finding] = []

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
        file_names.append(statement_file.name)
        doc_level, doc_headline = verdict(getattr(result, "document_checks", []))
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
            if doc_level != "clean":
                remarks += f' · <b class="doc-warn">{doc_headline}: see Document Check</b>'
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
        # Fraud patterns are looked for across all statements together (a new payee only shows up
        # against earlier months); they raise the risk of the transactions involved.
        all_transactions, findings, pattern_flags = fraud_rules.apply(all_transactions)
        all_flags = pd.concat([pattern_flags, all_flags], ignore_index=True)
if current_project:
    # Notes are keyed by statement and position on the page, so they survive re-reading the files.
    all_transactions["note_key"] = (
        all_transactions["statement_id"].astype(str) + "|" + all_transactions["source_page"].astype(str)
        + "|" + all_transactions["source_line"].astype(str)
    )
    all_transactions["note"] = [current_project["txn_notes"].get(key, "") for key in all_transactions["note_key"]]
# The evidence record: one row per file analyzed, with its fingerprint and what was found in it.
evidence = pd.DataFrame(
    [
        {
            "File": name,
            "SHA-256": getattr(r, "source", {}).get("sha256", ""),
            "Bytes": getattr(r, "source", {}).get("bytes"),
            "Pages": getattr(r, "source", {}).get("pages"),
            "Pages read with OCR": getattr(r, "source", {}).get("ocr_pages"),
            "Transactions": len(r.transactions),
            "Statements": ", ".join(sorted(r.transactions["statement_id"].astype(str).unique())) if not r.transactions.empty else "",
            "Document check": verdict(getattr(r, "document_checks", []))[1],
        }
        for name, r in zip(file_names, results)
    ],
    columns=["File", "SHA-256", "Bytes", "Pages", "Pages read with OCR", "Transactions", "Statements", "Document check"],
)
document_checks = pd.concat(
    [checks_frame(name, getattr(r, "document_checks", [])) for name, r in zip(file_names, results)] or [checks_frame("", [])], ignore_index=True
)

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
reconciliation_df = build_reconciliation_table(all_transactions)
if not evidence.empty and not reconciliation_df.empty:
    file_of = reconciliation_df["statement_id"].astype(str).str.split(" · ").str[0]
    evidence["Reconciliation"] = [
        ", ".join(sorted(set(reconciliation_df.loc[file_of == Path(name).stem, "status"].astype(str)))) for name in evidence["File"]
    ]
has_data = has_uploads and not all_transactions.empty
EMPTY_NOTE = "Upload a statement above, or click **Try it with sample statements**, to see results here."

# --- Main tabbed UI ---

st.markdown('<div style="height:0.6rem"></div>', unsafe_allow_html=True)
tab_names = ["Summary", "Dashboard", "Transactions", "Red Flags", "Document Check", "Bank Reconciliation", "Download Workpapers", "Add a New Bank"]
if current_project:
    tab_names.insert(0, "Project")
tabs = dict(zip(tab_names, st.tabs(tab_names)))
overview_tab, dashboard_tab, transactions_tab, risk_tab, document_tab, reconciliation_tab, export_tab, template_tab = (
    tabs[name] for name in tab_names if name != "Project"
)

if current_project:
    with tabs["Project"]:
        slug = current_project["slug"]
        protected = current_project["encrypted"]
        st.markdown(
            f'<div class="project-head"><div class="project-name">{escape(current_project["name"])}</div>'
            f'<p>{escape(current_project["description"]) or "No description yet."}</p>'
            f'<span>{"🔒 Encrypted" if protected else "⚠ Not password-protected"} · created {escape(current_project["created"])}'
            f' · last saved {escape(current_project["updated"])}'
            f' · {len(current_project["files"])} statement{"s" if len(current_project["files"]) != 1 else ""}</span></div>',
            unsafe_allow_html=True,
        )
        if not protected:
            # Projects from before encryption: offer to encrypt them in place.
            st.warning("This project was saved before projects were encrypted: its statements and notes are readable by anyone "
                       "with access to this computer. Protect it with a password.", icon=":material/lock_open:")
            with st.form(f"protect_{slug}", border=False):
                c1, c2, c3 = st.columns([1, 1, 0.7])
                protect_password = c1.text_input("New password", type="password", help=f"At least {projects.MIN_PASSWORD} characters.")
                protect_again = c2.text_input("Password again", type="password")
                if c3.form_submit_button("Protect this project", type="primary"):
                    try:
                        if protect_password != protect_again:
                            raise ValueError("The two passwords don't match.")
                        project_keys[slug] = projects.protect(slug, protect_password, PROJECTS_BASE)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        left, right = st.columns([1.15, 1])
        with left:
            _section("Statements", "Add a note to each statement, or tick Remove to take it out of the project")
            counts = all_transactions.groupby(all_transactions["statement_id"].astype(str).str.split(" · ").str[0]).size() if has_uploads and not all_transactions.empty else pd.Series(dtype=int)
            file_table = pd.DataFrame(
                [
                    {"File": f["name"], "Added": f["added"], "Transactions": int(counts.get(Path(f["name"]).stem, 0)),
                     "Note": current_project["file_notes"].get(f["name"], ""), "Remove": False}
                    for f in current_project["files"]
                ],
                columns=["File", "Added", "Transactions", "Note", "Remove"],
            )
            with st.form(f"files_{slug}", border=False):
                edited_files = st.data_editor(
                    file_table,
                    column_config={"Note": st.column_config.TextColumn("Note", width="large"), "Remove": st.column_config.CheckboxColumn("Remove", width="small")},
                    disabled=["File", "Added", "Transactions"],
                    hide_index=True,
                    width="stretch",
                )
                if st.form_submit_button("Save statement notes"):
                    meta = projects.load_project(slug, PROJECTS_BASE, project_key)
                    meta["file_notes"] = {row["File"]: str(row["Note"] or "") for _, row in edited_files.iterrows() if str(row["Note"] or "").strip()}
                    projects.log_event(meta, "Statement notes saved")
                    projects.save_project(meta, PROJECTS_BASE, project_key)
                    for _, row in edited_files[edited_files["Remove"]].iterrows():
                        projects.remove_file(slug, row["File"], PROJECTS_BASE, project_key)
                    st.rerun()
            if not current_project["files"]:
                st.caption("No statements yet: add them with the upload box above.")
        with right:
            _section("Case notes", "Your working notes for this project; saved with it and included in the workpaper")
            with st.form(f"notes_{slug}", border=False):
                project_name = st.text_input("Project name", value=current_project["name"],
                                             help="Stored unencrypted so the project can be listed: use a case number, not a person's name.")
                project_description = st.text_area("Description", value=current_project["description"], height=70)
                case_notes = st.text_area("Notes", value=current_project["notes"], height=260,
                                          placeholder="Who asked for the review, what you've found, what to request next…")
                if st.form_submit_button("Save notes", type="primary"):
                    meta = projects.load_project(slug, PROJECTS_BASE, project_key)
                    meta.update(name=project_name.strip() or meta["name"], description=project_description, notes=case_notes)
                    projects.log_event(meta, "Case notes saved")
                    projects.save_project(meta, PROJECTS_BASE, project_key)
                    st.rerun()
        st.caption("Notes on single transactions are on the Transactions tab (the Note column).")
        with st.expander("Case log", icon=":material/history:"):
            st.caption("When statements were added or removed, notes saved and the project downloaded. Included in the workpaper.")
            st.dataframe(pd.DataFrame(current_project["log"], columns=["time", "event", "detail"]).iloc[::-1],
                         column_config={"time": "When", "event": "What", "detail": "Details"}, hide_index=True, width="stretch")
        _section("Keep a copy, or close the case", "")
        d1, d2 = st.columns([1.3, 1])
        with d1:
            st.markdown("**Download the project**")
            st.caption("One encrypted .bsacase file with the statements and every note. Send the password separately from "
                       "the file (never in the same email). Open it again from the sidebar.")
            with st.form(f"export_{slug}", border=False):
                e1, e2 = st.columns(2)
                export_password = e1.text_input("Password for the file", type="password", help=f"At least {projects.MIN_PASSWORD} characters.")
                export_again = e2.text_input("Password again", type="password", key="export_again")
                if st.form_submit_button("Encrypt for download", icon=":material/enhanced_encryption:"):
                    try:
                        if export_password != export_again:
                            raise ValueError("The two passwords don't match.")
                        st.session_state[f"case_file_{slug}"] = projects.export_case(slug, export_password, PROJECTS_BASE, project_key)
                    except ValueError as exc:
                        st.error(str(exc))
            if st.session_state.get(f"case_file_{slug}"):
                st.download_button("Download project (.bsacase)", data=st.session_state[f"case_file_{slug}"], file_name=f"{slug}.bsacase",
                                   mime="application/octet-stream", icon=":material/download:", type="primary",
                                   on_click=lambda: st.session_state.pop(f"case_file_{slug}", None))
        with d2:
            st.markdown("**Close the case**")
            st.caption("Erases this project (statements, notes and log) from this app and clears this session. "
                       "Download it first if it must be kept.")
            with st.popover("Close case and erase", icon=":material/delete_forever:"):
                st.markdown(f"Erase **{escape(current_project['name'])}** from this app? This can't be undone.")
                if st.button("Yes, erase it", type="primary"):
                    projects.delete_project(slug, PROJECTS_BASE)
                    _clear_session()
                    st.rerun()


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
                       "Fraud patterns such as structuring, gambling, new payees and a draining balance are flagged, and each file is checked for signs of editing.")
            + _feature("M12 3v12M7 10l5 5 5-5M5 21h14", "Exports workpapers",
                       "Download a formatted Excel workpaper and summary financial statements for the case file.")
            + "</div>",
            unsafe_allow_html=True,
        )
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
            report = dashboard.to_html_report(
                f"{APP_NAME}: dashboard",
                f"{ORG_NAME} · {len(view)} transactions · exported {datetime.now().astimezone():%b %d, %Y %H:%M %Z} · {APP_NAME} {APP_VERSION}",
                [(t, f) for t, _, f in charts],
                sources=list(zip(evidence["File"], evidence["SHA-256"])),
            )
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
        st.caption(f"Showing {len(filtered)} of {tx_count} transactions" + (" · type in the Note column to add a note; it's saved to the project" if current_project else ""))
        shown_columns = ["txn_date", "statement_id", "description", "txn_category", "debit", "credit", "running_balance", "risk_badge"]
        column_config = {
            "txn_date": DATE_COLUMN,
            "statement_id": "Statement",
            "description": st.column_config.TextColumn("Description", width="medium"),
            "txn_category": "Category",
            "debit": _money_text_column("Money out"),
            "credit": _money_text_column("Money in"),
            "running_balance": _money_text_column("Balance"),
            "risk_badge": "Risk",
            "note": st.column_config.TextColumn("Note", width="medium"),
        }
        table = _money_cells(filtered, ["debit", "credit", "running_balance"])
        if current_project:
            # No key: the editor's identity comes from the rows and notes shown, so it starts fresh whenever
            # either changes and its edits always line up with the rows on screen. (A keyed editor also
            # hits a bug in the in-browser build of Streamlit.)
            edited = st.data_editor(
                table[shown_columns + ["note", "note_key"]],
                column_config=column_config,
                column_order=shown_columns[:3] + ["note"] + shown_columns[3:],
                disabled=shown_columns + ["note_key"],
                width="stretch",
                hide_index=True,
                height=480,
            )
            changed = {k: str(n or "").strip() for k, n in zip(edited["note_key"], edited["note"]) if str(n or "").strip() != current_project["txn_notes"].get(k, "")}
            if changed:
                meta = projects.load_project(current_project["slug"], PROJECTS_BASE, project_key)
                for key, note in changed.items():
                    if note:
                        meta["txn_notes"][key] = note
                    else:
                        meta["txn_notes"].pop(key, None)
                projects.save_project(meta, PROJECTS_BASE, project_key)
                st.rerun()
        else:
            st.dataframe(table[shown_columns], column_config=column_config, width="stretch", hide_index=True, height=480)

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
        if findings:
            _section("Fraud patterns found", "Patterns investigators look for, across all the statements uploaded. Each is a reason to look closer, not proof of fraud.")
            cards = []
            for finding in findings:
                cards.append(
                    f'<div class="finding {finding.severity}"><div class="finding-head"><span class="status {"bad" if finding.severity == "high" else "warn" if finding.severity == "medium" else "ok"}">'
                    f'{finding.severity.title()}</span><span class="title">{escape(finding.title)}</span>'
                    f'<span class="acct">Account {escape(str(finding.account))}</span></div><p>{escape(finding.detail)}</p></div>'
                )
            st.markdown('<div class="findings">' + "".join(cards) + "</div>", unsafe_allow_html=True)
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

with document_tab:
    if not results:
        st.info(EMPTY_NOTE)
    else:
        st.markdown(
            '<p class="doc-intro">Edited statements tend to leave the same traces: the file was re-saved by a PDF editor, '
            "a few lines are in a different font, balances don't add up, dates are out of place. Each file is checked for them "
            "below. A warning is a reason to get the statement <b>directly from the bank</b>; a clean result doesn't prove a "
            "statement is genuine.</p>",
            unsafe_allow_html=True,
        )
        icons = {"ok": ("ok", "Looks normal"), "warn": ("bad", "Worth checking"), "note": ("warn", "Note"), "skipped": ("muted", "Not checked")}
        for name, result in zip(file_names, results):
            level, headline = verdict(getattr(result, "document_checks", []))
            rows = "".join(
                f'<div class="doc-row"><span class="status {icons[c.status][0]}">{icons[c.status][1]}</span>'
                f'<div><div class="doc-name">{escape(c.name)}</div><div class="doc-detail">{escape(c.detail)}</div>'
                + ("".join(f'<div class="doc-example">{escape(e)}</div>' for e in c.examples) if c.status == WARN or c.examples else "")
                + "</div></div>"
                for c in getattr(result, "document_checks", [])
            )
            st.markdown(
                f'<div class="recon-card doc-card {level}"><div class="recon-head"><span class="title">{escape(name)}</span>'
                f'<span class="status {"ok" if level == "clean" else "warn" if level == "review" else "bad"}">{headline}</span></div>{rows}</div>',
                unsafe_allow_html=True,
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
        case_notes = None
        if current_project:
            case_notes = pd.DataFrame(
                [{"item": "Project", "note": current_project["name"]}, {"item": "Description", "note": current_project["description"]},
                 {"item": "Case notes", "note": current_project["notes"]}]
                + [{"item": f"Statement: {name}", "note": note} for name, note in current_project["file_notes"].items()]
            )
        analyzed_at = datetime.now().astimezone()
        run_details = [
            ("App version", f"{APP_NAME} {APP_VERSION}"),
            ("Analyst", st.session_state.get("analyst") or "(not entered)"),
            ("Project", current_project["name"] if current_project else "(none)"),
            ("Large-transaction threshold", f"${large_txn_threshold:,.0f}"),
            ("Statement files analyzed", len(results)),
        ]
        case_log = pd.DataFrame(current_project["log"], columns=["time", "event", "detail"]) if current_project else None
        workpaper_bytes = build_workpaper(
            all_transactions.drop(columns=["note_key"], errors="ignore"), all_flags, all_raw if include_raw_text else pd.DataFrame(),
            analyzed_at, document_checks, case_notes, evidence, run_details, case_log,
        )
        financial_bytes = build_financial_statements(all_transactions, reconciliation_df, analyzed_at)
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
        _section("Evidence record", "Each statement's SHA-256 fingerprint: any copy with the same fingerprint is byte-for-byte the "
                 "file analyzed here. The workpaper's Evidence sheet holds the same record, and every transaction row names its file, page and line.")
        st.dataframe(evidence, hide_index=True, width="stretch",
                     column_config={"SHA-256": st.column_config.TextColumn("SHA-256", width="large")})
        st.caption(f"{APP_NAME} {APP_VERSION} · analyzed {analyzed_at:%b %d, %Y %H:%M %Z}"
                   + (f" · analyst: {st.session_state['analyst']}" if st.session_state.get("analyst") else ""))

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
    f'<div class="app-footer">{APP_NAME} · <a href="{ORG_URL}" target="_blank" rel="noopener noreferrer">{ORG_NAME}</a></div>',
    unsafe_allow_html=True,
)
