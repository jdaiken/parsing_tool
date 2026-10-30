"""
Builds the rest of the Hartwell case: statements from three more (fictional) banks and the case documents.

make_demo_case.py writes Evelyn Hartwell's own Larkspur Valley Bank statements (files 1 to 6). This script
adds the other side of the money trail and the paperwork an investigator would be handed:

  7, 8   DP Companion Care LLC business checking at Quillbrook Credit Union, April and May 2025
         (subpoenaed): where Evelyn's checks and the $24,000 wire went.
  9, 10  Dana Pruitt's personal checking at Oxbow Prairie National Bank, April and May 2025 (subpoenaed):
         the Zelle payments, transfers out of the LLC, and cash deposited just under $10,000.
  11     A "Wrenfield Trust Bank" statement Dana's attorney sent as proof the money was repaid. It was written
         by an AI tool, and the app's Document Check reports it as possibly AI-generated.
  case_documents/  Exhibits A to I: engagement letter, family interview notes, caregiver agreement, invoice,
         CD maturity notice, account change confirmation, wire confirmation, check images, attorney's letter.

Everything is invented: the banks (with .example web addresses), the people, the account numbers and every
transaction. Each page carries the red SAMPLE banner. ANSWER_KEY.md says what is planted where.

Run from the repository root (needs reportlab and pypdfium2, which are not app dependencies):
    python demo/make_case_pack.py
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from make_demo_case import BANNER, _set_dates, money, with_balances

OUT = Path(__file__).resolve().parent
DOCS = OUT / "case_documents"
PAGE_W, PAGE_H = letter

# --- People and accounts (all fictional) ---------------------------------------------------------
LLC = ["DP COMPANION CARE LLC", "1907 LOCUST ST STE 2", "MAPLE GROVE IA 50999"]
LLC_ACCOUNT = "70033390"
DANA = ["DANA M PRUITT", "88 TIMBER RIDGE CT APT 4", "MAPLE GROVE IA 50999"]
DANA_ACCOUNT = "005520"
DANA_PHONE = "(319) 555-0188"
EVELYN_PHONE = "(319) 555-0127"

# --- Quillbrook Credit Union: DP Companion Care LLC business checking --------------------------
# (date, description, amount, category). The LLC's only money in comes from Evelyn; most of it leaves
# for Dana's personal account and a car. No payroll, no insurance, no other clients.
LLC_APRIL_OPENING = 312.40
LLC_APRIL = [
    ("04/07", "MOBILE DEPOSIT CHECK 2043 EVELYN R HARTWELL", 1200.00, "deposit"),
    ("04/08", "MOBILE DEPOSIT CHECK 2044 EVELYN R HARTWELL", 1200.00, "deposit"),
    ("04/09", "ONLINE TRANSFER TO OXBOW PRAIRIE NATL BK XXXX5520", -2000.00, "transfer"),
    ("04/11", "VERIZON WIRELESS PAYMENT", -96.44, "other"),
    ("04/15", "WIRE IN ORG EVELYN R HARTWELL LARKSPUR VLY BK REF 88213", 24000.00, "deposit"),
    ("04/15", "INCOMING WIRE FEE", -15.00, "fee"),
    ("04/16", "CHECK 1001", -18750.00, "check"),
    ("04/17", "ONLINE TRANSFER TO OXBOW PRAIRIE NATL BK XXXX5520", -3000.00, "transfer"),
    ("04/25", "DEPOSIT CHECK 2047 EVELYN R HARTWELL", 1500.00, "deposit"),
    ("04/28", "ONLINE TRANSFER TO OXBOW PRAIRIE NATL BK XXXX5520", -1500.00, "transfer"),
    ("04/30", "MONTHLY MAINTENANCE FEE", -12.00, "fee"),
]
LLC_MAY = [
    ("05/08", "MOBILE DEPOSIT CHECK 2048 EVELYN R HARTWELL", 1500.00, "deposit"),
    ("05/09", "ONLINE TRANSFER TO OXBOW PRAIRIE NATL BK XXXX5520", -1000.00, "transfer"),
    ("05/12", "VERIZON WIRELESS PAYMENT", -96.44, "other"),
    ("05/15", "AMBROSE LANE MOTORS LOAN PMT ACH", -612.30, "other"),
    ("05/19", "ONLINE TRANSFER TO OXBOW PRAIRIE NATL BK XXXX5520", -500.00, "transfer"),
    ("05/30", "MONTHLY MAINTENANCE FEE", -12.00, "fee"),
]

# --- Oxbow Prairie National Bank: Dana Pruitt personal checking ---------------------------------
# Listed by section, like many large banks: deposits, electronic withdrawals, card withdrawals.
DANA_APRIL_OPENING = 1842.17
DANA_APRIL = [
    ("04/01", "ZELLE PAYMENT TO RIVERTON PROPERTY MGMT RENT", -1150.00, "electronic"),
    ("04/03", "CARD PURCHASE CASEY'S #3310 MAPLE GROVE IA", -48.12, "card"),
    ("04/04", "ZELLE PAYMENT FROM EVELYN HARTWELL CONF JPM99A1X2F", 500.00, "deposit"),
    ("04/07", "DOORDASH INC PAYOUT", 186.52, "deposit"),
    ("04/09", "ONLINE TRANSFER FROM QUILLBROOK CU XXXX3390", 2000.00, "deposit"),
    ("04/12", "CARD PURCHASE LUCKY STAR CASINO TAMA IA", -300.00, "card"),
    ("04/17", "ONLINE TRANSFER FROM QUILLBROOK CU XXXX3390", 3000.00, "deposit"),
    ("04/18", "ZELLE PAYMENT FROM EVELYN HARTWELL CONF JPM99B7K4Q", 1000.00, "deposit"),
    ("04/19", "CARD PURCHASE LUCKY STAR CASINO TAMA IA", -600.00, "card"),
    ("04/21", "DOORDASH INC PAYOUT", 142.10, "deposit"),
    ("04/22", "CASH DEPOSIT 1ST AVE BRANCH", 9000.00, "deposit"),
    ("04/23", "PRAIRIELAND MUTUAL INS AUTO PREMIUM", -148.20, "electronic"),
    ("04/25", "CASH DEPOSIT 1ST AVE BRANCH", 9500.00, "deposit"),
    ("04/26", "CARD PURCHASE BEST BUY #212 CEDAR RAPIDS IA", -1299.99, "card"),
    ("04/28", "ONLINE TRANSFER FROM QUILLBROOK CU XXXX3390", 1500.00, "deposit"),
    ("04/29", "CARD PURCHASE LUCKY STAR CASINO TAMA IA", -800.00, "card"),
]
DANA_MAY = [
    ("05/01", "ZELLE PAYMENT TO RIVERTON PROPERTY MGMT RENT", -1150.00, "electronic"),
    ("05/02", "ZELLE PAYMENT FROM EVELYN HARTWELL CONF JPM99C2W8M", 2000.00, "deposit"),
    ("05/03", "CARD PURCHASE LUCKY STAR CASINO TAMA IA", -1000.00, "card"),
    ("05/05", "DOORDASH INC PAYOUT", 163.40, "deposit"),
    ("05/09", "ONLINE TRANSFER FROM QUILLBROOK CU XXXX3390", 1000.00, "deposit"),
    ("05/12", "ZELLE PAYMENT FROM EVELYN HARTWELL CONF JPM99D5T1R", 1500.00, "deposit"),
    ("05/15", "CARD PURCHASE MAPLE GROVE JEWELERS", -2450.00, "card"),
    ("05/19", "ONLINE TRANSFER FROM QUILLBROOK CU XXXX3390", 500.00, "deposit"),
    ("05/21", "CASH DEPOSIT 1ST AVE BRANCH", 8500.00, "deposit"),
    ("05/23", "PRAIRIELAND MUTUAL INS AUTO PREMIUM", -148.20, "electronic"),
    ("05/24", "CARD PURCHASE SUNWAVE CRUISES ONLINE", -3280.00, "card"),
    ("05/27", "CASH DEPOSIT 1ST AVE BRANCH", 4800.00, "deposit"),
    ("05/28", "CARD PURCHASE LUCKY STAR CASINO TAMA IA", -700.00, "card"),
]

# --- The AI-generated "proof of repayment" (Wrenfield Trust Bank) ------------------------------
# Claims Dana repaid Evelyn $24,000 in May. Evelyn's real May statement shows no such deposits.
FAKE_OPENING = 26412.55
FAKE_ROWS = [
    ("05/02", "Payroll Deposit - DP Companion Care LLC", 3200.00),
    ("05/06", "Transfer to Evelyn Hartwell - Loan Repayment", -10000.00),
    ("05/09", "Grocery Store Purchase", -142.37),
    ("05/13", "Utility Payment", -118.20),
    ("05/20", "Transfer to Evelyn Hartwell - Loan Repayment", -14000.00),
    ("05/27", "Restaurant Purchase", -64.50),
    ("05/31", "Interest Earned", 2.15),
]
FAKE_ROUTING = "073905528"  # fails the ABA check digit, as made-up routing numbers usually do


def _banner(c: canvas.Canvas) -> None:
    """The red SAMPLE banner across the top of every page."""
    c.setFillColorRGB(0.85, 0.12, 0.12)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(PAGE_W / 2, 772, BANNER)
    c.setFillColorRGB(0, 0, 0)


def _fit(text: str, font: str, size: float, width: float) -> str:
    """Drop trailing words until the text fits the column."""
    while stringWidth(text, font, size) > width and " " in text:
        text = text.rsplit(" ", 1)[0]
    return text


def _meta(c: canvas.Canvas, creator: str, producer: str, title: str) -> None:
    """Document details a bank's statement system writes."""
    c.setCreator(creator)
    c.setProducer(producer)
    c.setTitle(title)
    c.setAuthor(creator)


# --- Quillbrook layout: separate Withdrawals and Deposits columns, running balance ---------------
def quillbrook_statement(path: Path, period: str, opening: float, rows) -> float:
    """A credit union business statement: share draft account, two amount columns and a running balance."""
    closing = rows[-1]["balance"]
    c = canvas.Canvas(str(path), pagesize=letter)
    _meta(c, "Quillbrook Member Statements", "QCU eDocs 3.1", "Business Share Draft Statement (SAMPLE)")
    _banner(c)
    c.setFillColorRGB(0.13, 0.36, 0.25)
    c.setFont("Times-Bold", 20)
    c.drawString(40, 738, "Quillbrook Credit Union")
    c.setFont("Times-Italic", 9)
    c.drawString(40, 726, "Serving members in central Iowa since 1961 (fictional institution used for training)")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Times-Roman", 9)
    c.drawString(40, 713, "PO Box 220, Ames, IA 50010   quillbrookcu.example   800-555-0177")
    for i, line in enumerate(LLC):
        c.drawString(40, 680 - i * 11, line)
    c.setFont("Times-Bold", 10)
    c.drawString(350, 690, "BUSINESS SHARE DRAFT STATEMENT")
    c.setFont("Times-Roman", 9)
    c.drawString(350, 676, f"Statement Period: {period}")
    c.drawString(350, 664, f"Member Account #: {LLC_ACCOUNT}")
    c.drawString(350, 652, "Share Draft Suffix: S70")
    deposits = sum(r["amount"] for r in rows if r["amount"] > 0)
    withdrawals = -sum(r["amount"] for r in rows if r["amount"] < 0)
    y = 610
    c.setFont("Times-Bold", 11)
    c.drawString(40, y, "Account Summary")
    c.setFont("Times-Roman", 9)
    for label, value in (("Previous Balance", money(opening, dollar=True)),
                         ("Deposits and Credits", money(deposits, dollar=True)),
                         ("Withdrawals and Debits", money(withdrawals, dollar=True)),
                         ("New Balance", money(closing, dollar=True))):
        y -= 13
        c.drawString(40, y, label)
        c.drawRightString(260, y, value)
    y -= 30
    c.setFont("Times-Bold", 11)
    c.drawString(40, y, "Account Activity")
    y -= 15
    c.setFont("Times-Bold", 8.5)
    c.drawString(40, y, "Date")
    c.drawString(85, y, "Transaction Description")
    c.drawRightString(440, y, "Withdrawals")
    c.drawRightString(505, y, "Deposits")
    c.drawRightString(570, y, "Balance")
    y -= 13
    c.setFont("Times-Roman", 9)
    c.drawString(85, y, "Previous Balance")
    c.drawRightString(570, y, f"{opening:,.2f}")
    for row in rows:
        y -= 13
        c.drawString(40, y, row["date"])
        c.drawString(85, y, _fit(row["desc"], "Times-Roman", 9, 300))
        column = 440 if row["amount"] < 0 else 505
        c.drawRightString(column, y, f"{abs(row['amount']):,.2f}")
        c.drawRightString(570, y, f"{row['balance']:,.2f}")
    y -= 13
    c.setFont("Times-Bold", 9)
    c.drawString(85, y, "New Balance")
    c.drawRightString(570, y, f"{closing:,.2f}")
    c.setFont("Times-Roman", 7)
    c.drawString(40, 40, "Federally insured by NCUA. Quillbrook Credit Union is a fictional institution created for forensic accounting training.")
    c.drawRightString(572, 28, "Page 1 of 1")
    c.showPage()
    c.save()
    return closing


# --- Oxbow layout: sections with totals, no running balance, a daily balance table --------------
def oxbow_statement(path: Path, period: str, opening: float, rows) -> float:
    """A large-bank style personal statement: summary, sections by type with totals, daily ending balances."""
    closing = round(opening + sum(r[2] for r in rows), 2)
    deposits = [r for r in rows if r[3] == "deposit"]
    electronic = [r for r in rows if r[3] == "electronic"]
    card = [r for r in rows if r[3] == "card"]
    c = canvas.Canvas(str(path), pagesize=letter)
    _meta(c, "Oxbow Prairie StatementWorks", "OPNB Composer 7.2", "Personal Checking Statement (SAMPLE)")
    pages = 2

    def header(page: int) -> None:
        """Banner, logo line, account number and page number on every page."""
        _banner(c)
        c.setFillColorRGB(0.42, 0.18, 0.05)
        c.setFont("Courier-Bold", 16)
        c.drawString(40, 740, "OXBOW PRAIRIE NATIONAL BANK")
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Courier", 8)
        c.drawString(40, 729, "oxbowprairie.example  |  Customer Care 1-800-555-0163  |  Member FDIC (fictional)")
        c.drawRightString(572, 745, period)
        c.drawRightString(572, 734, f"Account Number: {DANA_ACCOUNT}")
        c.drawRightString(572, 30, f"Page {page} of {pages}")

    header(1)
    c.setFont("Courier", 9)
    for i, line in enumerate(DANA):
        c.drawString(40, 700 - i * 11, line)
    y = 640
    c.setFont("Courier-Bold", 10)
    c.drawString(40, y, "PRAIRIE EVERYDAY CHECKING")
    c.setFont("Courier", 9)
    for label, value in (("Beginning Balance", money(opening, dollar=True)),
                         ("Deposits and Additions", money(sum(r[2] for r in deposits), dollar=True)),
                         ("Electronic Withdrawals", money(sum(r[2] for r in electronic), dollar=True)),
                         ("ATM & Debit Card Withdrawals", money(sum(r[2] for r in card), dollar=True)),
                         ("Ending Balance", money(closing, dollar=True))):
        y -= 12
        c.drawString(40, y, label)
        c.drawRightString(330, y, value)
    y -= 26

    def section(title: str, items, total_label: str, y: float) -> float:
        """One section: heading, a line per transaction, and its total."""
        c.setFont("Courier-Bold", 10)
        c.drawString(40, y, title)
        y -= 13
        c.setFont("Courier-Bold", 8)
        c.drawString(40, y, "DATE")
        c.drawString(90, y, "DESCRIPTION")
        c.drawRightString(570, y, "AMOUNT")
        y -= 12
        c.setFont("Courier", 8.5)
        for when, desc, amount, _ in items:
            c.drawString(40, y, when)
            c.drawString(90, y, _fit(desc, "Courier", 8.5, 380))
            c.drawRightString(570, y, f"${abs(amount):,.2f}")
            y -= 11.5
        c.setFont("Courier-Bold", 8.5)
        c.drawString(90, y, total_label)
        c.drawRightString(570, y, f"${abs(sum(r[2] for r in items)):,.2f}")
        return y - 24

    y = section("DEPOSITS AND ADDITIONS", deposits, "Total Deposits and Additions", y)
    y = section("ELECTRONIC WITHDRAWALS", electronic, "Total Electronic Withdrawals", y)
    if y < 200:
        c.showPage()
        header(2)
        y = 700
    y = section("ATM & DEBIT CARD WITHDRAWALS", card, "Total ATM & Debit Card Withdrawals", y)
    if c.getPageNumber() == 1:
        c.showPage()
        header(2)
        y = 700
    # Daily ending balances, four to a line.
    c.setFont("Courier-Bold", 10)
    c.drawString(40, y, "DAILY ENDING BALANCE")
    y -= 14
    c.setFont("Courier", 8.5)
    balance, daily = opening, {}
    for when, _, amount, _ in sorted(rows, key=lambda r: r[0]):
        balance = round(balance + amount, 2)
        daily[when] = balance
    entries = list(daily.items())
    for start in range(0, len(entries), 4):
        x = 40
        for when, value in entries[start:start + 4]:
            c.drawString(x, y, when)
            c.drawRightString(x + 115, y, f"${value:,.2f}")
            x += 135
        y -= 12
    c.showPage()
    c.save()
    return closing


# --- The AI-generated statement ----------------------------------------------------------------
def ai_generated_statement(path: Path) -> None:
    """
    What an AI chat tool produces when asked for "a bank statement showing loan repayments": ReportLab with its
    default details, a markdown heading it didn't render, a date that doesn't exist, a made-up routing number,
    "Page 1 of 2" on a one-page file, an account number that changes, and a running balance that doesn't add up.
    """
    c = canvas.Canvas(str(path), pagesize=letter)  # no creator, producer or title set: ReportLab's defaults stay
    _banner(c)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, 735, "Wrenfield Trust Bank")
    c.setFont("Helvetica", 9)
    c.drawString(40, 721, "1200 Commerce Avenue, Des Moines, IA 50309")
    c.drawString(40, 709, f"Routing Number: {FAKE_ROUTING}")
    c.drawString(360, 735, "Monthly Account Statement")
    c.drawString(360, 721, "Statement Period: 05/01/2025 - 05/31/2025")
    c.drawString(360, 709, "Statement Date: 06/31/2025")
    c.drawString(360, 697, "Account Number: ****4417")
    c.drawString(40, 680, "Account Holder: Dana M. Pruitt")
    c.drawString(40, 668, "88 Timber Ridge Ct, Apt 4, Maple Grove, IA 50999")
    rows, closing = with_balances(FAKE_OPENING, [(d, desc, amt, "x") for d, desc, amt in FAKE_ROWS])
    deposits = sum(r["amount"] for r in rows if r["amount"] > 0)
    withdrawals = -sum(r["amount"] for r in rows if r["amount"] < 0)
    y = 635
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "**Account Summary**")
    c.setFont("Helvetica", 9)
    for label, value in (("Account No:", "****4471"), ("Opening Balance:", money(FAKE_OPENING, dollar=True)),
                         ("Total Deposits:", money(deposits, dollar=True)), ("Total Withdrawals:", money(withdrawals, dollar=True)),
                         ("Closing Balance:", money(closing, dollar=True))):
        y -= 13
        c.drawString(40, y, label)
        c.drawRightString(300, y, value)
    y -= 30
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Transaction History")
    y -= 15
    c.setFont("Helvetica-Bold", 9)
    for x, label in ((40, "Date"), (100, "Description")):
        c.drawString(x, y, label)
    c.drawRightString(470, y, "Amount")
    c.drawRightString(570, y, "Balance")
    y -= 13
    c.setFont("Helvetica", 9)
    c.drawString(40, y, "05/01")
    c.drawString(100, y, "Opening Balance")
    c.drawRightString(570, y, f"{FAKE_OPENING:,.2f}")
    for i, row in enumerate(rows):
        y -= 13
        balance = row["balance"] + (100.00 if i == 2 else 0)  # the AI tool's arithmetic slip
        c.drawString(40, y, row["date"])
        c.drawString(100, y, row["desc"])
        c.drawRightString(470, y, money(row["amount"]))
        c.drawRightString(570, y, f"{balance:,.2f}")
    y -= 13
    c.setFont("Helvetica-Bold", 9)
    c.drawString(100, y, "Closing Balance")
    c.drawRightString(570, y, f"{closing:,.2f}")
    y -= 40
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(40, y, "Thank you for banking with Wrenfield Trust Bank. This statement is provided for informational purposes.")
    c.drawString(40, y - 11, "Wrenfield Trust Bank is a member of the FDIC. Equal Housing Lender.")
    c.setFont("Helvetica", 7)
    c.drawRightString(572, 30, "Page 1 of 2")
    c.showPage()
    c.save()


def main_statements() -> None:
    """Write files 7 to 11 and print the balances for the answer key."""
    llc_april, llc_april_close = with_balances(LLC_APRIL_OPENING, LLC_APRIL)
    llc_may, llc_may_close = with_balances(llc_april_close, LLC_MAY)
    quillbrook_statement(OUT / "7_dp_companion_care_2025-04.pdf", "04/01/2025 - 04/30/2025", LLC_APRIL_OPENING, llc_april)
    quillbrook_statement(OUT / "8_dp_companion_care_2025-05.pdf", "05/01/2025 - 05/31/2025", llc_april_close, llc_may)
    dana_april_close = oxbow_statement(OUT / "9_pruitt_personal_2025-04.pdf", "April 1, 2025 through April 30, 2025", DANA_APRIL_OPENING, DANA_APRIL)
    dana_may_close = oxbow_statement(OUT / "10_pruitt_personal_2025-05.pdf", "May 1, 2025 through May 31, 2025", dana_april_close, DANA_MAY)
    ai_generated_statement(OUT / "11_wrenfield_repayment_proof_2025-05.pdf")
    for name, day in (("7_dp_companion_care_2025-04", "20250501"), ("8_dp_companion_care_2025-05", "20250601"),
                      ("9_pruitt_personal_2025-04", "20250501"), ("10_pruitt_personal_2025-05", "20250601"),
                      ("11_wrenfield_repayment_proof_2025-05", "20250912")):
        _set_dates(OUT / f"{name}.pdf", day)
    print(f"LLC: April ends {llc_april_close:,.2f}, May ends {llc_may_close:,.2f}")
    print(f"Dana: April ends {dana_april_close:,.2f}, May ends {dana_may_close:,.2f}")


# =================================================================================================
# Case documents (Exhibits A to I)
# =================================================================================================

_SS = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_SS["Normal"], fontName="Times-Roman", fontSize=11, leading=15, spaceAfter=8)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=12, spaceAfter=4)
HEAD = ParagraphStyle("head", parent=BODY, fontName="Times-Bold", fontSize=12, spaceBefore=6, spaceAfter=6)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Times-Bold", fontSize=15, leading=19, alignment=1, spaceAfter=12)
SANS = ParagraphStyle("sans", parent=BODY, fontName="Helvetica", fontSize=9.5, leading=13)
SANS_HEAD = ParagraphStyle("sanshead", parent=SANS, fontName="Helvetica-Bold", fontSize=11, spaceBefore=6)


def _document(path: Path, letterhead: Sequence[Tuple[str, str, float]], story: list, footer: str) -> None:
    """
    A letter or form: the SAMPLE banner and a letterhead (text, font, size) on each page, then the story.
    The details name the (fictional) sender, not a PDF tool.
    """
    def on_page(c: canvas.Canvas, doc) -> None:
        """Banner, letterhead and footer on every page."""
        _banner(c)
        y = 745
        for text, font, size in letterhead:
            c.setFont(font, size)
            c.drawString(54, y, text)
            y -= size + 3
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.line(54, y + 2, PAGE_W - 54, y + 2)
        c.setFont("Helvetica", 7)
        c.drawString(54, 30, footer)
        c.drawRightString(PAGE_W - 54, 30, f"Page {doc.page}")

    top = 792 - 745 + sum(size + 3 for _, _, size in letterhead) + 18
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=54, rightMargin=54, topMargin=top, bottomMargin=54,
                            title=path.stem.replace("_", " "), author=letterhead[0][0], creator=letterhead[0][0],
                            producer=letterhead[0][0])
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


def _p(text: str, style=BODY) -> Paragraph:
    """A paragraph in the given style."""
    return Paragraph(text, style)


def _table(rows, widths, header=True, font="Times-Roman", size=10) -> Table:
    """A ruled table; the first row is bold when header is set."""
    cell = ParagraphStyle("cell", fontName=font, fontSize=size, leading=size + 2.5)
    bold = ParagraphStyle("cellbold", parent=cell, fontName="Helvetica-Bold" if font.startswith("Helvetica") else "Times-Bold")
    # Wrap plain text in paragraphs so long values break onto a second line instead of running past the edge.
    rows = [[Paragraph(str(v), bold if header and r == 0 else cell) if isinstance(v, str) else v for v in row]
            for r, row in enumerate(rows)]
    table = Table(rows, colWidths=widths)
    style = [("FONT", (0, 0), (-1, -1), font, size), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("FONT", (0, 0), (-1, 0), font.split("-")[0] + "-Bold" if "-" not in font else font.replace("Roman", "Bold"), size),
                  ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EFF6"))]
    table.setStyle(TableStyle(style))
    return table


FIRM = [("BRENNAN & THALE ELDER LAW, PLLC", "Times-Bold", 14),
        ("410 Grand Avenue, Suite 300, Des Moines, IA 50309  ·  brennanthale.example  ·  515-555-0110", "Times-Roman", 9),
        ("A fictional law firm created for forensic accounting training", "Times-Italic", 8)]
LARKSPUR = [("LARKSPUR VALLEY BANK, N.A.", "Helvetica-Bold", 14),
            ("P O Box 4400, Des Moines, IA 50306  ·  larkspurvalleybank.example  ·  1-800-555-0142", "Helvetica", 8.5),
            ("Fictional institution used for training", "Helvetica-Oblique", 7.5)]
FICTION = "Fictional document created for forensic accounting training. All names, institutions and figures are invented."


def exhibit_a(path: Path) -> None:
    """The engagement letter: who the team works for, what they are asked to answer, what they were given."""
    docs = [
        ["Exhibit", "Document", "Source"],
        ["1-4", "Larkspur Valley Bank checking statements, March-May 2025, and the May 2025 Visa statement", "Larkspur Valley Bank (authorization of Laura Byrne under power of attorney)"],
        ["5", "\"Family copy\" of the April 2025 checking statement", "Emailed to Laura Byrne by Dana Pruitt, 06/24/2025"],
        ["6", "Scanned, redacted copy of the May 2025 checking statement", "Maple Grove Police Department referral packet"],
        ["7-8", "DP Companion Care LLC business checking, April-May 2025", "Quillbrook Credit Union, by subpoena"],
        ["9-10", "Dana M. Pruitt personal checking, April-May 2025", "Oxbow Prairie National Bank, by subpoena"],
        ["11", "\"Wrenfield Trust Bank\" statement, May 2025", "Enclosed with Exhibit I"],
        ["A-I", "This letter, interview notes, caregiver agreement, invoice, bank notices, wire confirmation, check images, opposing counsel's letter", "Client file and Larkspur Valley Bank"],
    ]
    story = [
        _p("September 15, 2025"),
        _p("Forensic Accounting Team<br/>Fraud Examination Practicum"),
        _p("<b>Re: Evelyn R. Hartwell, conservatorship petition and civil recovery: engagement for forensic accounting services</b>"),
        _p("Dear Team:"),
        _p("Thank you for agreeing to assist this office. We represent Laura Byrne, daughter and agent under power of attorney for "
           "her mother, Evelyn R. Hartwell, age 81, of Maple Grove, Iowa. Between April and May 2025 Mrs. Hartwell's checking "
           "account went from about $16,000, plus a $50,000 certificate of deposit, to overdrawn. Her paid caregiver, Dana M. "
           "Pruitt, who bills through DP Companion Care LLC, had access to her checkbook, debit card and online banking during that time."),
        _p("Please answer the following, supported by workpapers:", HEAD),
        _p("1. What money left Mrs. Hartwell's accounts from March 1 through May 31, 2025, and where did it go? Trace it to the "
           "recipient accounts where the records allow."),
        _p("2. How much of what was paid to DP Companion Care LLC and Ms. Pruitt is supported by the caregiver agreement and "
           "invoices (Exhibits C and D)? How much is not?"),
        _p("3. What happened to the cash withdrawn from Mrs. Hartwell's account?"),
        _p("4. Is the \"family copy\" of the April statement (Exhibit 5) a true copy? Is the Wrenfield Trust Bank statement "
           "(Exhibit 11) authentic, and does it support opposing counsel's claim that $24,000 was repaid?"),
        _p("5. What amount, in your opinion, left Mrs. Hartwell's control without documented authorization? Show the calculation "
           "and state what you could not determine."),
        _p("Documents provided", HEAD),
        _table([[_p(c, SMALL) for c in row] for row in docs], [0.6 * inch, 3.4 * inch, 2.9 * inch]),
        Spacer(1, 10),
        _p("Please record the SHA-256 fingerprint of each statement file as you receive it, and keep your analysis to what the "
           "documents show: report findings as consistent or inconsistent with the explanations offered, and leave conclusions "
           "about intent or guilt to the trier of fact. If a record you need is missing, tell us what to request."),
        _p("Your workpapers and a findings memo are due October 17, 2025."),
        _p("Sincerely,<br/><br/><font name='Times-Italic' size='14'>Ruth A. Brennan</font><br/>Ruth A. Brennan, Attorney at Law"),
    ]
    _document(path, FIRM, story, FICTION)


def exhibit_b(path: Path) -> None:
    """Interview notes with the client's daughter: the family's account of events and the leads to follow."""
    notes = [
        "Mom hired Dana Pruitt in late March from a flyer at the pharmacy. Agreed rate $24/hour, Monday, Wednesday and "
        "Friday mornings, about 4 hours a visit. Dana said she runs a small company, DP Companion Care.",
        "Mom's memory has been slipping since last fall. She can still talk about the past clearly but loses track of bills.",
        "In April Dana \"set up Mom's phone\" and \"helped with online banking\". Mom has never used online banking herself. "
        f"Mom's number is the landline, {EVELYN_PHONE}. Dana's cell is {DANA_PHONE}.",
        "Mom had a $50,000 CD at Larkspur that came due in April. She had planned to roll it over. When I asked in July, she "
        "said Dana told her the money was going into \"something better\". Mom does not remember signing anything for a wire "
        "and says she never lent Dana or her company money.",
        "Larkspur called Mom on May 29 about an overdraft; Mom called me. That is how we found out.",
        "When I asked Dana for Mom's statements she emailed me a copy of April on June 24 (Exhibit 5). It looked normal to me.",
        "Dana started driving a new SUV in mid-April. She told my brother she got \"a great deal\".",
        "Mom has never gambled as far as any of us know. Lucky Star Casino is about 45 minutes away and Mom no longer drives.",
        "Mom kept her checkbook in the kitchen drawer. We found checks 2045 and 2046 missing from the book, with no entries in the register.",
    ]
    story = [
        _p("MEMORANDUM: CLIENT INTERVIEW NOTES", TITLE),
        _p("Privileged and confidential: attorney work product (fictional)", ParagraphStyle("c", parent=SMALL, alignment=1)),
        _table([["Interviewee:", "Laura Byrne (daughter; agent under power of attorney)"], ["Date:", "July 2, 2025"],
                ["Interviewer:", "Ruth A. Brennan"], ["Also present:", "None"]], [1.3 * inch, 5.6 * inch], header=False),
        Spacer(1, 12),
        *[_p(f"{i}. {n}") for i, n in enumerate(notes, start=1)],
        _p("Follow-up", HEAD),
        _p("Subpoena records for DP Companion Care LLC and Dana Pruitt. Request Larkspur's wire file, check images and the record "
           "of contact changes on Mom's account. Ask Laura for any invoices from DP Companion Care (she found one, Exhibit D)."),
    ]
    _document(path, FIRM, story, FICTION)


def exhibit_c(path: Path) -> None:
    """The caregiver agreement: what DP Companion Care was entitled to be paid."""
    terms = [
        ("Services", "Companion care: meal preparation, light housekeeping, errands, medication reminders and transportation to appointments."),
        ("Schedule", "Monday, Wednesday and Friday, 9:00 a.m. to 1:00 p.m. (12 hours per week). Additional hours only with the Client's written approval."),
        ("Rate", "$24.00 per hour. No other fees, deposits or advances."),
        ("Invoices and payment", "Provider invoices every two weeks, listing dates and hours worked. Client pays by check within 10 days of an invoice."),
        ("Errands", "Purchases for the Client up to $100 at a time, with receipts returned to the Client."),
        ("Prohibited", "Provider and its staff will not accept loans, gifts or money beyond the rate above; will not use the Client's "
                       "debit or credit cards, checks or online banking; and will not change the Client's account information."),
        ("Term", "Begins April 1, 2025. Either party may end this agreement with 7 days' notice."),
    ]
    story = [
        _p("CAREGIVER SERVICES AGREEMENT", TITLE),
        _p("This agreement is made March 28, 2025 between <b>Evelyn R. Hartwell</b>, 214 Birchwood Lane, Maple Grove, Iowa "
           "(the \"Client\"), and <b>DP Companion Care LLC</b>, 1907 Locust Street, Suite 2, Maple Grove, Iowa (the \"Provider\")."),
        _table([[_p(f"<b>{k}</b>", SMALL), _p(v, SMALL)] for k, v in terms], [1.5 * inch, 5.4 * inch], header=False),
        Spacer(1, 22),
        _table([[_p("<font name='Times-Italic' size='15'>Evelyn R. Hartwell</font>"), _p("<font name='Times-Italic' size='15'>Dana M. Pruitt</font>")],
                ["Evelyn R. Hartwell, Client", "Dana M. Pruitt, Member, DP Companion Care LLC"], ["Date: 3/28/2025", "Date: 3/28/2025"]],
               [3.45 * inch, 3.45 * inch], header=False),
    ]
    _document(path, [("DP COMPANION CARE LLC", "Helvetica-Bold", 14),
                     ("1907 Locust St, Suite 2, Maple Grove, IA 50999  ·  " + DANA_PHONE, "Helvetica", 8.5),
                     ("Fictional company used for training", "Helvetica-Oblique", 7.5)], story, FICTION)


def exhibit_d(path: Path) -> None:
    """The only invoice the family found: 24 hours for the first two weeks of April."""
    visits = ["04/02", "04/04", "04/07", "04/09", "04/11"]
    rows = [["Date", "Service", "Hours", "Rate", "Amount"]]
    hours = [4, 4, 4, 4, 8]
    for day, h in zip(visits, hours):
        rows.append([f"{day}/2025", "Companion care" + (" (incl. appointment)" if h == 8 else ""), str(h), "$24.00", f"${h * 24:,.2f}"])
    total = sum(hours) * 24
    rows.append(["", "Total due", str(sum(hours)), "", f"${total:,.2f}"])
    story = [
        _p("INVOICE", TITLE),
        _table([["Invoice #:", "INV-1001"], ["Invoice date:", "April 14, 2025"], ["Bill to:", "Evelyn R. Hartwell, 214 Birchwood Ln, Maple Grove IA"],
                ["Service period:", "April 1 - April 13, 2025"], ["Terms:", "Due within 10 days. Make checks payable to DP Companion Care LLC."]],
               [1.4 * inch, 5.5 * inch], header=False),
        Spacer(1, 14),
        _table(rows, [1.1 * inch, 2.9 * inch, 0.8 * inch, 0.9 * inch, 1.2 * inch], font="Helvetica", size=9.5),
        Spacer(1, 14),
        _p("Thank you for choosing DP Companion Care!", SANS),
    ]
    _document(path, [("DP COMPANION CARE LLC", "Helvetica-Bold", 14),
                     ("1907 Locust St, Suite 2, Maple Grove, IA 50999  ·  " + DANA_PHONE, "Helvetica", 8.5),
                     ("Fictional company used for training", "Helvetica-Oblique", 7.5)], story, FICTION)


def exhibit_e(path: Path) -> None:
    """The bank's notice that the $50,000 CD was about to mature, and where the money would go."""
    story = [
        _p("March 14, 2025", SANS),
        _p("EVELYN R HARTWELL<br/>214 BIRCHWOOD LN<br/>MAPLE GROVE IA 50999", SANS),
        _p("Your certificate of deposit is maturing", SANS_HEAD),
        _table([["Certificate number", "ending 5521"], ["Opened", "April 14, 2024"], ["Term", "12 months"],
                ["Principal", "$50,000.00"], ["Interest", "Paid quarterly by check (final payment mailed at maturity)"],
                ["Maturity date", "April 14, 2025"],
                ["Instructions on file", "Transfer principal to Larkspur Classic Checking ending 8701 at maturity"]],
               [2.0 * inch, 4.9 * inch], header=False, font="Helvetica", size=9.5),
        Spacer(1, 10),
        _p("If you'd like to renew your certificate or change these instructions, visit any branch or call us before the "
           "maturity date. After April 14 the funds will be in your checking account and available to you.", SANS),
        _p("Larkspur Valley Bank, Deposit Operations", SANS),
    ]
    _document(path, LARKSPUR, story, FICTION)


def exhibit_f(path: Path) -> None:
    """The bank's confirmation that the phone number and online banking were changed on April 3."""
    story = [
        _p("April 3, 2025", SANS),
        _p("EVELYN R HARTWELL<br/>214 BIRCHWOOD LN<br/>MAPLE GROVE IA 50999", SANS),
        _p("Confirmation of changes to your account", SANS_HEAD),
        _p("We're writing to confirm the following changes made today to your Larkspur Classic Checking account ending 8701:", SANS),
        _table([["Change", "Before", "After", "How requested"],
                ["Phone number on file", EVELYN_PHONE, DANA_PHONE, "Phone call, 04/03/2025 10:14 a.m."],
                ["Email address", "(none)", "dmpcare@mailbox.example", "Phone call, 04/03/2025 10:14 a.m."],
                ["Online banking", "Not enrolled", "Enrolled; one-time passcodes sent by text to the phone on file", "Online, 04/03/2025 10:31 a.m."]],
               [1.5 * inch, 1.2 * inch, 2.4 * inch, 1.8 * inch], font="Helvetica", size=8.5),
        Spacer(1, 10),
        _p("<b>If you did not request these changes, call us right away at 1-800-555-0142.</b> For your security this letter is "
           "mailed to the address on file.", SANS),
        _p("Larkspur Valley Bank, Customer Care", SANS),
    ]
    _document(path, LARKSPUR, story, FICTION)


def exhibit_g(path: Path) -> None:
    """The outgoing wire confirmation: $24,000 to the LLC, authorized by a passcode sent to the caregiver's phone."""
    rows = [
        ["Date and time", "April 15, 2025, 9:42 a.m. CT"], ["Wire reference", "88213"],
        ["From account", "Larkspur Classic Checking ending 8701, EVELYN R HARTWELL"],
        ["Amount", "$24,000.00"], ["Wire fee", "$30.00"],
        ["Beneficiary", "DP COMPANION CARE LLC, 1907 LOCUST ST STE 2, MAPLE GROVE IA 50999"],
        ["Beneficiary bank", "QUILLBROOK CREDIT UNION, AMES IA"], ["Beneficiary account", LLC_ACCOUNT],
        ["Purpose (as entered)", "PREPAID CARE SERVICES"],
        ["Channel", "Online banking"],
        ["Authentication", f"One-time passcode sent by text to {DANA_PHONE} at 9:40 a.m.; entered correctly at 9:41 a.m."],
        ["Device", "iPhone, new device first seen 04/03/2025"],
        ["Status", "Completed 04/15/2025 10:05 a.m."],
    ]
    story = [
        _p("OUTGOING WIRE TRANSFER CONFIRMATION", ParagraphStyle("t", parent=SANS_HEAD, fontSize=13, alignment=1, spaceAfter=10)),
        _table(rows, [2.0 * inch, 4.9 * inch], header=False, font="Helvetica", size=9.5),
        Spacer(1, 10),
        _p("Wire transfers can't be reversed once completed. Produced from Larkspur Valley Bank's wire file in response to a "
           "request from the account holder's agent under power of attorney, July 21, 2025.", SANS),
    ]
    _document(path, LARKSPUR, story, FICTION)


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _words(n: int) -> str:
    """Whole dollars in words, as written on a check."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + _words(n % 100) if n % 100 else "")
    return _words(n // 1000) + " thousand" + (" " + _words(n % 1000) if n % 1000 else "")


def _check(c: canvas.Canvas, y: float, *, number: str, date: str, payee: str, amount: float, memo: str, payer: List[str],
           bank: str, signature: str, sig_font: str, account: str, endorsement: Optional[List[str]] = None) -> None:
    """One check image, front (and back, when endorsed), drawn at height y."""
    w, h, x = 504, 200, 54
    c.setFillColorRGB(0.93, 0.96, 0.93)
    c.setStrokeColorRGB(0.4, 0.5, 0.4)
    c.rect(x, y, w, h, fill=1)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 12, y + h - 18, payer[0])
    c.setFont("Helvetica", 7.5)
    for i, line in enumerate(payer[1:]):
        c.drawString(x + 12, y + h - 29 - i * 9, line)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(x + w - 12, y + h - 18, number)
    c.setFont("Helvetica", 8)
    c.drawString(x + 330, y + h - 46, "DATE")
    c.setFont("Times-Italic", 12)
    c.drawString(x + 360, y + h - 46, date)
    c.setFont("Helvetica", 7)
    c.drawString(x + 12, y + 118, "PAY TO THE")
    c.drawString(x + 12, y + 110, "ORDER OF")
    c.setFont("Times-Italic", 13)
    c.drawString(x + 62, y + 112, payee)
    c.line(x + 60, y + 108, x + 390, y + 108)
    c.rect(x + 400, y + 106, 92, 20)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x + 486, y + 111, f"{amount:,.2f}")
    c.setFont("Times-Italic", 12)
    cents = round(amount * 100) % 100
    c.drawString(x + 14, y + 86, f"{_words(int(amount)).capitalize()} and {cents:02d}/100")
    c.line(x + 12, y + 82, x + 440, y + 82)
    c.setFont("Helvetica", 7)
    c.drawString(x + 446, y + 85, "DOLLARS")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + 12, y + 64, bank)
    c.setFont("Helvetica", 7)
    c.drawString(x + 12, y + 40, "MEMO")
    c.setFont("Times-Italic", 11)
    c.drawString(x + 40, y + 41, memo)
    c.line(x + 38, y + 38, x + 230, y + 38)
    c.setFont(sig_font, 15)
    c.drawString(x + 300, y + 42, signature)
    c.line(x + 290, y + 38, x + 490, y + 38)
    c.setFont("Courier", 10)
    c.drawString(x + 60, y + 14, f"#{number}#  {account}  (MICR line, sample)")
    if endorsement:
        bx = x + w - 170
        c.setFillColorRGB(1, 1, 1)
        c.rect(bx, y - 110, 170, 100, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(bx + 6, y - 20, f"BACK OF CHECK {number}")
        c.setFont("Times-Italic", 9.5)
        for i, line in enumerate(endorsement):
            c.drawString(bx + 6, y - 34 - i * 12, line)


def exhibit_h(path: Path) -> None:
    """Images of the checks to DP Companion Care, with their endorsements, and the LLC's check for the SUV."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Exhibit H - Check images")
    c.setAuthor("Larkspur Valley Bank")
    c.setCreator("Larkspur Image Archive")
    c.setProducer("Larkspur Image Archive")
    evelyn = ["EVELYN R. HARTWELL", "214 Birchwood Ln", "Maple Grove, IA 50999"]
    endorse = ["DP Companion Care LLC", "For mobile deposit only", "Quillbrook CU", f"Acct {LLC_ACCOUNT}"]
    checks = [
        dict(number="2043", date="4/7/2025", payee="DP Companion Care LLC", amount=1200.00, memo="care",
             signature="Evelyn R. Hartwell", sig_font="Times-Italic"),
        dict(number="2044", date="4/7/2025", payee="DP Companion Care LLC", amount=1200.00, memo="care April",
             signature="Evelyn R. Hartwell", sig_font="Times-Italic"),
        dict(number="2047", date="4/24/2025", payee="DP Companion Care LLC", amount=1500.00, memo="advance",
             signature="Evelyn Hartwell", sig_font="Helvetica-Oblique"),
        dict(number="2048", date="5/7/2025", payee="DP Companion Care LLC", amount=1500.00, memo="May care",
             signature="Evelyn Hartwell", sig_font="Helvetica-Oblique"),
    ]
    for page_checks in (checks[:2], checks[2:]):
        _banner(c)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(54, 745, "Larkspur Valley Bank: paid check images, account ending 8701 (fictional)")
        for slot, check in enumerate(page_checks):
            _check(c, 500 - slot * 350, payer=evelyn, bank="LARKSPUR VALLEY BANK, N.A.", account="4410228701",
                   endorsement=endorse, **check)
        c.setFont("Helvetica", 7)
        c.drawString(54, 30, FICTION)
        c.showPage()
    _banner(c)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, 745, "Quillbrook Credit Union: paid check image, account " + LLC_ACCOUNT + " (fictional, by subpoena)")
    _check(c, 500, number="1001", date="4/15/2025", payee="Ambrose Lane Motors", amount=18750.00,
           memo="SUV down pmt - D. Pruitt", payer=LLC, bank="QUILLBROOK CREDIT UNION", account=LLC_ACCOUNT,
           signature="Dana M Pruitt", sig_font="Times-Italic",
           endorsement=["Ambrose Lane Motors", "For deposit only"])
    c.setFont("Helvetica", 9)
    c.drawString(54, 330, "Note from Larkspur Valley Bank: checks 2045 and 2046 were never presented for payment.")
    c.drawString(54, 316, "Check 2049 ($600.00, payable to cash) was returned unpaid on 05/29/2025 for insufficient funds.")
    c.setFont("Helvetica", 7)
    c.drawString(54, 30, FICTION)
    c.showPage()
    c.save()


def exhibit_i(path: Path) -> None:
    """Opposing counsel's letter: the wire was a loan, repaid in May (see the enclosed statement, file 11)."""
    story = [
        _p("September 12, 2025"),
        _p("Ruth A. Brennan<br/>Brennan &amp; Thale Elder Law, PLLC<br/>410 Grand Avenue, Suite 300<br/>Des Moines, IA 50309"),
        _p("<b>Re: Evelyn R. Hartwell / DP Companion Care LLC</b>"),
        _p("Dear Ms. Brennan:"),
        _p("I represent Dana M. Pruitt and DP Companion Care LLC. Your letter of August 28 suggests my clients took money from "
           "Mrs. Hartwell without authorization. They did not."),
        _p("The $24,000 wire of April 15, 2025 was a short-term loan from Mrs. Hartwell to DP Companion Care LLC so that the "
           "company could expand its services. Mrs. Hartwell offered the loan herself and the terms were agreed orally. It was "
           "repaid in full in May 2025 by two transfers from Ms. Pruitt's account at Wrenfield Trust Bank, $10,000 on May 6 and "
           "$14,000 on May 20. A copy of that statement is enclosed."),
        _p("The checks paid to DP Companion Care LLC were compensation for care, including overnight and weekend care that "
           "Mrs. Hartwell requested as her needs grew. The Zelle payments to Ms. Pruitt reimbursed groceries and errands."),
        _p("Ms. Pruitt cared for Mrs. Hartwell faithfully. I trust this resolves the matter. Please direct any further "
           "communication about it to me."),
        _p("Very truly yours,<br/><br/><font name='Times-Italic' size='14'>Garrick L. Doyle</font><br/>Garrick L. Doyle, Attorney at Law"),
        _p("Enclosure: Wrenfield Trust Bank statement, May 2025 (file 11)", SMALL),
    ]
    _document(path, [("GARRICK L. DOYLE, ATTORNEY AT LAW", "Times-Bold", 14),
                     ("22 Main Street, Tama, IA 52339  ·  doylelaw.example  ·  641-555-0190", "Times-Roman", 9),
                     ("A fictional attorney created for forensic accounting training", "Times-Italic", 8)], story, FICTION)


EXHIBITS = [
    ("A", "Engagement_letter", exhibit_a, "20250915"),
    ("B", "Family_interview_notes", exhibit_b, "20250702"),
    ("C", "Caregiver_services_agreement", exhibit_c, "20250328"),
    ("D", "DP_Companion_Care_invoice", exhibit_d, "20250414"),
    ("E", "CD_maturity_notice", exhibit_e, "20250314"),
    ("F", "Account_change_confirmation", exhibit_f, "20250403"),
    ("G", "Wire_transfer_confirmation", exhibit_g, "20250721"),
    ("H", "Check_images", exhibit_h, "20250721"),
    ("I", "Opposing_counsel_letter", exhibit_i, "20250912"),
]


def main_documents() -> None:
    """Write Exhibits A to I into case_documents/."""
    DOCS.mkdir(exist_ok=True)
    for letter_, name, build, day in EXHIBITS:
        path = DOCS / f"Exhibit_{letter_}_{name}.pdf"
        build(path)
        _set_dates(path, day)
        print("wrote", path.relative_to(OUT.parent))


if __name__ == "__main__":
    main_statements()
    main_documents()
