"""
Builds the demo case pack: fictional statements telling one elder-financial-exploitation story.

Everything here is invented: the bank ("Larkspur Valley Bank"), the people, the account numbers
and every transaction. Each page carries a "SAMPLE" banner so the files can't pass as real
statements. See ANSWER_KEY.md for what is planted where.

Run from the repository root (needs reportlab and pypdfium2, which are not app dependencies):
    python demo/make_demo_case.py
"""

from __future__ import annotations

import random
import re
from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent
BANK = "Larkspur Valley Bank"
BANK_DOMAIN = "larkspurvalleybank.example"
PHONE = "1-800-555-0142"
CUSTOMER = ["EVELYN R. HARTWELL", "214 BIRCHWOOD LN", "MAPLE GROVE IA 50999"]
CHECKING_NUMBER = "4410228701"
CARD_ENDING = "7731"
BANNER = "SAMPLE STATEMENT - FICTIONAL DATA FOR TRAINING ONLY - NOT A REAL ACCOUNT"
GENUINE_META = {"creator": "Larkspur eStatements", "producer": "Larkspur DocGen 4.2"}

# --- The story --------------------------------------------------------------------------
# March: normal life. April: a paid caregiver (Dana Pruitt) gets access. May: the account drains.
# category: deposit | check | card (ATM & debit card) | electronic | fee
MARCH = [
    ("03/03", "PENSION DEPOSIT IOWA PUBLIC EMPLOYEES RET SYS", 1124.36, "deposit"),
    ("03/03", "SOCIAL SECURITY SSA TREAS 310 XXSOC SEC", 1846.00, "deposit"),
    ("03/04", "CARD PURCHASE 03/03 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -84.17, "card"),
    ("03/05", "MIDAMERICAN ENERGY AUTOPAY PPD ID 9001", -112.40, "electronic"),
    ("03/07", "CARD PURCHASE 03/06 WALGREENS #4471 MAPLE GROVE IA CARD 0417", -23.89, "card"),
    ("03/10", "CHECK 2041", -100.00, "check"),
    ("03/12", "MEDIACOM CABLE AUTOPAY PPD ID 4421", -89.99, "electronic"),
    ("03/14", "CARD PURCHASE 03/13 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -61.02, "card"),
    ("03/17", "ATM WITHDRAWAL 03/17 1ST AVE BRANCH MAPLE GROVE IA CARD 0417", -100.00, "card"),
    ("03/19", "CITY OF MAPLE GROVE WATER UTIL PPD ID 2208", -46.18, "electronic"),
    ("03/21", "CHECK 2042", -180.00, "check"),
    ("03/24", "CARD PURCHASE 03/22 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -72.44, "card"),
    ("03/27", "AARP MEDICARE SUPPLEMENT PREMIUM PPD ID 7713", -214.50, "electronic"),
    ("03/28", "CARD PURCHASE 03/27 WALGREENS #4471 MAPLE GROVE IA CARD 0417", -18.25, "card"),
    ("03/31", "INTEREST PAYMENT", 0.42, "deposit"),
]
APRIL = [
    ("04/01", "PENSION DEPOSIT IOWA PUBLIC EMPLOYEES RET SYS", 1124.36, "deposit"),
    ("04/02", "CARD PURCHASE 04/01 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -66.10, "card"),
    ("04/03", "SOCIAL SECURITY SSA TREAS 310 XXSOC SEC", 1846.00, "deposit"),
    ("04/04", "ZELLE PAYMENT TO DANA PRUITT JPM99A1X2F", -500.00, "electronic"),
    ("04/07", "MIDAMERICAN ENERGY AUTOPAY PPD ID 9001", -98.73, "electronic"),
    ("04/08", "CHECK 2043 DP COMPANION CARE LLC", -1200.00, "check"),
    ("04/09", "CHECK 2044 DP COMPANION CARE LLC", -1200.00, "check"),
    ("04/11", "ATM WITHDRAWAL 04/11 LUCKY STAR CASINO TAMA IA CARD 0417", -400.00, "card"),
    ("04/12", "ATM WITHDRAWAL 04/12 LUCKY STAR CASINO TAMA IA CARD 0417", -500.00, "card"),
    ("04/12", "NON-NETWORK ATM FEE", -3.50, "fee"),
    ("04/14", "CD MATURITY TRANSFER FROM CERTIFICATE ...5521", 50000.00, "deposit"),
    ("04/15", "WIRE TRANSFER OUT DP COMPANION CARE LLC REF 88213", -24000.00, "electronic"),
    ("04/15", "OUTGOING WIRE FEE", -30.00, "fee"),
    ("04/16", "MEDIACOM CABLE AUTOPAY PPD ID 4421", -89.99, "electronic"),
    ("04/18", "ZELLE PAYMENT TO DANA PRUITT JPM99B7K4Q", -1000.00, "electronic"),
    ("04/19", "ATM WITHDRAWAL 04/19 LUCKY STAR CASINO TAMA IA CARD 0417", -500.00, "card"),
    ("04/21", "CASH WITHDRAWAL 1ST AVE BRANCH MAPLE GROVE IA", -9500.00, "card"),
    ("04/22", "AARP MEDICARE SUPPLEMENT PREMIUM PPD ID 7713", -214.50, "electronic"),
    ("04/24", "CASH WITHDRAWAL 1ST AVE BRANCH MAPLE GROVE IA", -9800.00, "card"),
    ("04/25", "CARD PURCHASE 04/24 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -45.10, "card"),
    ("04/28", "CHECK 2047 DP COMPANION CARE LLC", -1500.00, "check"),
    ("04/30", "INTEREST PAYMENT", 0.31, "deposit"),
]
MAY = [
    ("05/01", "PENSION DEPOSIT IOWA PUBLIC EMPLOYEES RET SYS", 1124.36, "deposit"),
    ("05/02", "ZELLE PAYMENT TO DANA PRUITT JPM99C2W8M", -2000.00, "electronic"),
    ("05/03", "ATM WITHDRAWAL 05/03 LUCKY STAR CASINO TAMA IA CARD 0417", -500.00, "card"),
    ("05/03", "ATM WITHDRAWAL 05/03 LUCKY STAR CASINO TAMA IA CARD 0417", -500.00, "card"),
    ("05/03", "NON-NETWORK ATM FEE", -3.50, "fee"),
    ("05/03", "NON-NETWORK ATM FEE", -3.50, "fee"),
    ("05/05", "SOCIAL SECURITY SSA TREAS 310 XXSOC SEC", 1846.00, "deposit"),
    ("05/06", "CARD PURCHASE 05/06 TARGET GIFT CARD MALL MAPLE GROVE IA CARD 0417", -500.00, "card"),
    ("05/06", "CARD PURCHASE 05/06 WALGREENS GIFT CARDS #4471 MAPLE GROVE IA CARD 0417", -500.00, "card"),
    ("05/08", "MIDAMERICAN ENERGY AUTOPAY PPD ID 9001", -87.12, "electronic"),
    ("05/09", "CHECK 2048 DP COMPANION CARE LLC", -1500.00, "check"),
    ("05/12", "ZELLE PAYMENT TO DANA PRUITT JPM99D5T1R", -1500.00, "electronic"),
    ("05/16", "MEDIACOM CABLE AUTOPAY PPD ID 4421", -89.99, "electronic"),
    ("05/17", "ATM WITHDRAWAL 05/17 LUCKY STAR CASINO TAMA IA CARD 0417", -500.00, "card"),
    ("05/20", "CASH WITHDRAWAL 1ST AVE BRANCH MAPLE GROVE IA", -9000.00, "card"),
    ("05/22", "AARP MEDICARE SUPPLEMENT PREMIUM PPD ID 7713", -214.50, "electronic"),
    ("05/23", "CASH WITHDRAWAL 1ST AVE BRANCH MAPLE GROVE IA", -5080.00, "card"),
    ("05/27", "CARD PURCHASE 05/26 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -38.66, "card"),
    ("05/28", "CITY OF MAPLE GROVE WATER UTIL PPD ID 2208", -46.18, "electronic"),
    ("05/28", "OVERDRAFT FEE ITEM PAID", -35.00, "fee"),
    ("05/29", "INSUFFICIENT FUNDS FEE RETURNED ITEM CHECK 2049", -35.00, "fee"),
]
MARCH_OPENING = 14892.47

CARD_MAY = {
    "previous": 412.60,
    "payments": [("05/02", "05/02", "PAYMENT THANK YOU", -412.60)],
    "purchases": [
        ("05/05", "05/06", "BEST BUY #212 CEDAR RAPIDS IA", 849.99),
        ("05/06", "05/07", "GOOGLE *PLAY GIFT CARD G.CO/HELPPAY#", 300.00),
        ("05/07", "05/08", "VANILLA GIFT CARD ONLINE 833-322-6760", 500.00),
        ("05/14", "05/15", "HY-VEE #1123 MAPLE GROVE IA", 52.13),
        ("05/21", "05/22", "APPLE.COM/BILL GIFT CARD 866-712-7753", 400.00),
    ],
    "cash_advances": [
        ("05/03", "05/05", "CASH ADVANCE LUCKY STAR CASINO TAMA IA", 1000.00),
        ("05/18", "05/19", "CASH ADVANCE LUCKY STAR CASINO TAMA IA", 500.00),
    ],
    "fees": [("05/05", "05/05", "CASH ADVANCE FEE", 40.00), ("05/19", "05/19", "CASH ADVANCE FEE", 20.00)],
    "interest": [("05/31", "05/31", "INTEREST CHARGE ON CASH ADVANCES", 23.47)],
}


def _fit(text: str, font: str, size: float, width: float) -> str:
    """Drop trailing words until the description fits before the amount column."""
    while stringWidth(text, font, size) > width and " " in text:
        text = text.rsplit(" ", 1)[0]
    return text


def money(value: float, sign: bool = True, dollar: bool = False) -> str:
    """Format an amount as printed on the statements: '1,234.56', '- 1,234.56' for money out, optionally with a $."""
    text = f"{abs(value):,.2f}"
    if dollar:
        text = "$" + text
    return ("- " + text) if sign and value < 0 else text


def with_balances(opening: float, rows):
    """Add a running balance to each row; returns (rows, closing balance)."""
    balance, out = opening, []
    for when, desc, amount, cat in rows:
        balance = round(balance + amount, 2)
        out.append({"date": when, "desc": desc, "amount": amount, "cat": cat, "balance": balance})
    return out, balance


def summary_for(opening, rows, closing):
    """The checking summary box: beginning balance, totals by category, ending balance."""
    totals = {cat: round(sum(r["amount"] for r in rows if r["cat"] == cat), 2) for cat in ("deposit", "check", "card", "electronic", "fee")}
    return [
        ("Beginning Balance", money(opening, dollar=True), True),
        ("Deposits and Additions", money(totals["deposit"]), False),
        ("Checks Paid", money(totals["check"]), False),
        ("ATM & Debit Card Withdrawals", money(totals["card"]), False),
        ("Electronic Withdrawals", money(totals["electronic"]), False),
        ("Fees", money(totals["fee"]), False),
        ("Ending Balance", money(closing, dollar=True), True),
    ]


def _header(c: canvas.Canvas, period_text: str, page: int, pages: int) -> None:
    """Draw the page header (sample banner, bank name, period, account number) and footer."""
    c.setFillColorRGB(0.85, 0.12, 0.12)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(306, 772, BANNER)
    c.setFillColorRGB(0.07, 0.24, 0.42)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, 740, "LARKSPUR VALLEY")
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(40, 728, f"{BANK}, N.A.  P O Box 4400  Des Moines, IA 50306")
    c.setFont("Helvetica", 9)
    c.drawString(360, 742, period_text)
    c.drawString(360, 729, "Account Number:")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(440, 729, CHECKING_NUMBER)
    c.setFont("Helvetica", 7)
    c.drawRightString(572, 30, f"Page {page} of {pages}")
    c.drawString(40, 30, f"{BANK}, N.A. Member FDIC (fictional institution used for training)")


def checking_statement(path: Path, period_text: str, opening: float, rows, *, meta=None, edits=None) -> float:
    """
    Draw one month of checking. `edits` (for the doctored copy) can set per-row "font",
    "balance_text", "amount_text", and override summary lines with "summary".
    """
    edits = edits or {}
    closing = rows[-1]["balance"] if rows else opening
    c = canvas.Canvas(str(path), pagesize=letter)
    meta = meta or GENUINE_META
    c.setCreator(meta["creator"])
    c.setProducer(meta["producer"])
    c.setTitle("Account statement (SAMPLE)")
    per_page = [rows[:24], rows[24:]] if len(rows) > 24 else [rows]
    pages = len(per_page)
    for page_number, page_rows in enumerate(per_page, start=1):
        _header(c, period_text, page_number, pages)
        y = 705
        if page_number == 1:
            c.setFont("Helvetica", 9)
            for line in CUSTOMER:
                c.drawString(40, y, line)
                y -= 11
            c.setFont("Helvetica", 8)
            c.drawString(360, 705, f"Web site: {BANK_DOMAIN}")
            c.drawString(360, 694, f"Service Center: {PHONE}")
            y = 640
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "CHECKING SUMMARY")
            c.setFont("Helvetica", 9)
            c.drawString(200, y, "Larkspur Classic Checking")
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(400, y - 14, "AMOUNT")
            y -= 27
            for label, value, bold in edits.get("summary") or summary_for(opening, rows, closing):
                c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
                c.drawString(40, y, label)
                c.drawRightString(400, y, value)
                y -= 12
            y -= 18
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "TRANSACTION DETAIL" + (" (continued)" if page_number > 1 else ""))
        y -= 16
        c.setFont("Helvetica-Bold", 8)
        c.drawString(40, y, "DATE")
        c.drawString(80, y, "DESCRIPTION")
        c.drawRightString(480, y, "AMOUNT")
        c.drawRightString(570, y, "BALANCE")
        y -= 14
        if page_number == 1:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(80, y, "Beginning Balance")
            c.drawRightString(570, y, money(opening, dollar=True))
            y -= 13
        for row in page_rows:
            edit = edits.get(id(row), {})
            font = edit.get("font", "Helvetica")
            c.setFont(font, 9)
            c.drawString(40, y, row["date"])
            c.drawString(80, y, _fit(row["desc"], font, 9, 340))
            c.drawRightString(480, y, edit.get("amount_text", money(row["amount"])))
            c.drawRightString(570, y, edit.get("balance_text", f"{row['balance']:,.2f}"))
            y -= 13
        if page_number == pages:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(80, y, "Ending Balance")
            c.drawRightString(570, y, edits.get("ending_text", money(closing, dollar=True)))
        c.showPage()
    c.save()
    return closing


def card_statement(path: Path) -> None:
    """Draw the May credit card statement from CARD_MAY."""
    d = CARD_MAY
    purchases = sum(t[3] for t in d["purchases"])
    advances = sum(t[3] for t in d["cash_advances"])
    fees = sum(t[3] for t in d["fees"])
    interest = sum(t[3] for t in d["interest"])
    payments = sum(t[3] for t in d["payments"])
    new_balance = round(d["previous"] + payments + purchases + advances + fees + interest, 2)
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setCreator(GENUINE_META["creator"])
    c.setProducer(GENUINE_META["producer"])
    c.setTitle("Credit card statement (SAMPLE)")
    _header(c, "Statement period 05/01/25 - 05/31/25", 1, 1)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, 712, "Larkspur Visa Signature Credit Card")
    c.setFont("Helvetica", 9)
    c.drawString(40, 699, f"Account Number: XXXX XXXX XXXX {CARD_ENDING}")
    for i, line in enumerate(CUSTOMER):
        c.drawString(40, 684 - i * 11, line)
    y = 640
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "ACCOUNT SUMMARY")
    y -= 14
    c.setFont("Helvetica", 9)
    for label, value in [
        ("Previous Balance", money(d["previous"], dollar=True)),
        ("Payment, Credits", "- " + money(-payments, sign=False, dollar=True)),
        ("Purchases", "+ " + money(purchases, dollar=True)),
        ("Cash Advances", "+ " + money(advances, dollar=True)),
        ("Fees Charged", "+ " + money(fees, dollar=True)),
        ("Interest Charged", "+ " + money(interest, dollar=True)),
        ("New Balance", money(new_balance, dollar=True)),
    ]:
        c.drawString(40, y, label)
        c.drawRightString(300, y, value)
        y -= 12
    c.drawString(330, 626, f"Minimum Payment Due: {money(40, dollar=True)}")
    c.drawString(330, 614, "Payment Due Date: 06/25/25")
    c.drawString(330, 602, f"Credit Limit: {money(5000, dollar=True)}")
    y -= 14
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "ACCOUNT ACTIVITY")
    y -= 14
    c.setFont("Helvetica-Bold", 8)
    for x, label in ((40, "Date of Transaction"), (130, "Merchant Name or Transaction Description")):
        c.drawString(x, y, label)
    c.drawRightString(570, y, "$ Amount")
    y -= 14
    for title, key in (
        ("PAYMENTS AND OTHER CREDITS", "payments"),
        ("PURCHASES", "purchases"),
        ("CASH ADVANCES", "cash_advances"),
        ("FEES CHARGED", "fees"),
        ("INTEREST CHARGED", "interest"),
    ):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, title)
        y -= 13
        c.setFont("Helvetica", 9)
        for trans_date, _post, desc, amount in d[key]:
            c.drawString(40, y, trans_date)
            c.drawString(130, y, desc)
            c.drawRightString(570, y, f"{amount:,.2f}" if amount >= 0 else f"-{abs(amount):,.2f}")
            y -= 13
        y -= 4
    c.showPage()
    c.save()


def doctored_april(path: Path, opening: float) -> None:
    """
    The copy the caregiver could show the family: the casino, Zelle, wire and cash lines are
    removed and the caregiver's checks relabelled. The edits leave the tells a reviewer (and the
    app's document check) looks for. ANSWER_KEY.md lists them.
    """
    hidden = ("LUCKY STAR", "WIRE", "CASH WITHDRAWAL", "CD MATURITY", "NON-NETWORK", "OUTGOING WIRE")
    kept = [r for r in APRIL if not any(h in r[1] for h in hidden)]
    rows = []
    for when, desc, amount, cat in kept:
        if "ZELLE PAYMENT TO DANA PRUITT JPM99A1X2F" in desc:
            desc = "ZELLE PAYMENT FROM DANA PRUITT JPM99A1X2F"  # relabelled, still money out
        desc = desc.replace("DP COMPANION CARE LLC", "MAPLE GROVE HOME HEALTH")
        rows.append((when, desc, amount, cat))
    # Out of date order: the 04/22 premium is moved after 04/25, and a May item slips in.
    rows.sort(key=lambda r: r[0])
    premium = next(r for r in rows if r[1].startswith("AARP"))
    rows.remove(premium)
    rows.insert(len(rows) - 2, premium)
    rows.insert(len(rows) - 1, ("05/02", "CARD PURCHASE 05/01 HY-VEE #1123 MAPLE GROVE IA CARD 0417", -52.80, "card"))
    with_bal, closing = with_balances(opening, rows)
    edits = {}
    edited_markers = ("MAPLE GROVE HOME HEALTH", "ZELLE PAYMENT FROM")
    for row in with_bal:
        if any(m in row["desc"] for m in edited_markers):
            edits[id(row)] = {"font": "Times-Roman"}  # typed over in a different font
    # One balance typed by hand that doesn't follow from the line above it.
    broken = with_bal[5]
    edits.setdefault(id(broken), {})["balance_text"] = f"{broken['balance'] + 1000:,.2f}"
    # Summary claims deposits that the detail doesn't show, and an ending balance without a comma.
    summary = summary_for(opening, with_bal, closing)
    summary[1] = ("Deposits and Additions", money(sum(r["amount"] for r in with_bal if r["cat"] == "deposit") + 1500), False)
    edits["summary"] = summary
    edits["ending_text"] = f"${closing:.2f}"
    checking_statement(path, "April 01, 2025 through April 30, 2025", opening, with_bal, meta={"creator": "iLovePDF", "producer": "iLovePDF"}, edits=edits)
    # Saved weeks after it was created: an edited file.
    _set_dates(path, "20250502", "20250623")


def _set_dates(path: Path, created: str, modified: Optional[str] = None) -> None:
    """Give the PDF the creation (and last-saved) date a real file would have, as YYYYMMDD."""
    data = path.read_bytes()
    data = re.sub(rb"(/CreationDate \(D:)\d{8}", rb"\g<1>" + created.encode(), data)
    data = re.sub(rb"(/ModDate \(D:)\d{8}", rb"\g<1>" + (modified or created).encode(), data)
    path.write_bytes(data)


def scanned_redacted(source: Path, path: Path) -> None:
    """A printed-and-scanned copy with the client's identifiers blacked out (image only, no text)."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFilter

    random.seed(7)
    pdf = pdfium.PdfDocument(str(source))
    images = []
    for index in range(len(pdf)):
        image = pdf[index].render(scale=150 / 72).to_pil().convert("L")
        draw = ImageDraw.Draw(image)
        k = 150 / 72  # points to pixels
        def box(x0, y0, x1, y1):  # PDF points, origin bottom-left
            """Black out a rectangle given in PDF points (origin at the bottom left)."""
            draw.rectangle([x0 * k, (792 - y1) * k, x1 * k, (792 - y0) * k], fill=0)
        box(436, 724, 520, 739)  # account number
        if index == 0:
            box(38, 680, 200, 716)  # name and address
        image = image.rotate(0.4, expand=False, fillcolor=255, resample=Image.BICUBIC)
        image = image.filter(ImageFilter.GaussianBlur(0.5))
        image = Image.blend(image, Image.effect_noise(image.size, 40), 0.06)  # scanner grain
        images.append(image.convert("RGB"))
    pdf.close()
    images[0].save(path, "PDF", resolution=150, save_all=True, append_images=images[1:])


def main() -> None:
    """Build every file in the demo case pack."""
    march, march_close = with_balances(MARCH_OPENING, MARCH)
    april, april_close = with_balances(march_close, APRIL)
    may, may_close = with_balances(april_close, MAY)
    for name, rows in (("March", march), ("April", april), ("May", may)):
        low = min(r["balance"] for r in rows)
        print(f"{name}: {len(rows)} transactions, ending {rows[-1]['balance']:,.2f}, lowest {low:,.2f}")
    checking_statement(OUT / "1_checking_2025-03.pdf", "March 01, 2025 through March 31, 2025", MARCH_OPENING, march)
    checking_statement(OUT / "2_checking_2025-04.pdf", "April 01, 2025 through April 30, 2025", march_close, april)
    checking_statement(OUT / "3_checking_2025-05.pdf", "May 01, 2025 through May 31, 2025", april_close, may)
    card_statement(OUT / "4_credit_card_2025-05.pdf")
    # Genuine files are written once, the day after the period ends.
    for name, day in (("1_checking_2025-03", "20250401"), ("2_checking_2025-04", "20250501"),
                      ("3_checking_2025-05", "20250601"), ("4_credit_card_2025-05", "20250601")):
        _set_dates(OUT / f"{name}.pdf", day)
    doctored_april(OUT / "5_checking_2025-04_family_copy.pdf", march_close)
    scanned_redacted(OUT / "3_checking_2025-05.pdf", OUT / "6_checking_2025-05_scanned_redacted.pdf")
    _set_dates(OUT / "6_checking_2025-05_scanned_redacted.pdf", "20250718")  # scanned weeks later


if __name__ == "__main__":
    main()
