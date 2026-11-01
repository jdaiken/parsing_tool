"""
Account inventory: which accounts the statements cover, and the statements on file for each.

The first thing an investigator writes down in a bank records case is an inventory: every account,
whose it is, which statements are on hand and which are missing. This module builds it from the
statements loaded:

- `statement_list` gives one row per statement: the account it belongs to, its period, opening and
  closing balances, transactions, reconciliation result and document check.
- `account_inventory` groups those by account and looks across each account's statements for what
  needs following up: months with no statement, a balance that doesn't carry forward from one
  statement to the next, and two statements for the same period (a duplicate copy, or two versions
  that disagree, the way a doctored copy does).

A statement whose account number isn't shown (a redacted copy) is matched to an account with a
statement for the same period and the same balances, and says so.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from authenticity import PERIOD_TEXT, _period, verdict
from auto_parser import suggest_bank_name

STATEMENT_COLUMNS = [
    "account", "bank", "account_type", "account_number", "file", "statement_id", "period_start", "period_end",
    "opening_balance", "closing_balance", "transactions", "money_in", "money_out", "reconciliation", "document_check",
    "sha256", "note",
]
INVENTORY_COLUMNS = [
    "account", "bank", "account_type", "account_number", "statements", "period_start", "period_end", "months_missing",
    "opening_balance", "closing_balance", "transactions", "money_in", "money_out", "reconciliation", "document_check", "follow_up",
]
NOT_SHOWN = "not shown"
# Words a statement uses for the kind of account, in the order they are tried.
ACCOUNT_TYPES = [
    (re.compile(r"money\s+market", re.IGNORECASE), "Money market"),
    (re.compile(r"\bsavings\b|\bshare\s+savings\b", re.IGNORECASE), "Savings"),
    (re.compile(r"certificate\s+of\s+deposit", re.IGNORECASE), "Certificate of deposit"),
    (re.compile(r"\bchecking\b|share\s+draft", re.IGNORECASE), "Checking"),
]


def _money(value) -> str:
    """$1,234.56, -$79.93, or a dash for a missing figure."""
    if value is None or pd.isna(value):
        return "-"
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def _last_four(account_number) -> Optional[str]:
    """The last four digits of an account or card number ('005520 · Prairie Checking' -> '5520'); None if not shown."""
    digits = re.sub(r"\D", "", str(account_number or "").split("·")[0])
    return digits[-4:] if len(digits) >= 4 else None


def _bank_name(tx: pd.DataFrame, full_text: str) -> str:
    """The bank's name: from how the statement was read ('auto:Quillbrook Credit Union'), else from its header."""
    label = str(tx["bank_format"].iloc[0]) if "bank_format" in tx and len(tx) else ""
    if label.startswith("auto:") and label[5:] and label[5:] != "unknown":
        return label[5:]
    return suggest_bank_name(full_text) or "Bank not identified"


def _account_type(tx: pd.DataFrame, full_text: str) -> str:
    """Credit card, checking, savings...: from the way it was read, then the words on the statement."""
    if "statement_kind" in tx and (tx["statement_kind"] == "credit_card").any():
        return "Credit card"
    product = str(tx["account_number"].dropna().iloc[0]) if tx["account_number"].notna().any() else ""
    for text in (product, full_text):
        # The word that comes first wins: the heading names the account; fine print mentions the others.
        found = [(m.start(), name) for pattern, name in ACCOUNT_TYPES for m in [pattern.search(text)] if m]
        if found:
            return min(found)[1]
    return "Deposit account"


def _statement_period(tx: pd.DataFrame, full_text: str) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    The period the statement covers: as printed on it ("April 1, 2025 through April 30, 2025") when that
    can be read, otherwise the first and last transaction dates.
    """
    candidates = []
    if "statement_date" in tx and tx["statement_date"].notna().any():
        candidates.append(str(tx["statement_date"].dropna().iloc[0]))
    printed = PERIOD_TEXT.search(full_text or "")
    if printed:
        candidates.append(printed.group(0))
    for text in candidates:
        found = _period(text)
        if found:
            return pd.Timestamp(found[0]).normalize(), pd.Timestamp(found[1]).normalize()
    dates = tx["txn_date"].dropna()
    if dates.empty:
        return None, None
    return dates.min().normalize(), dates.max().normalize()


def _first(frame: pd.DataFrame, column: str):
    """The first non-missing value in a column (statement-level figures repeat on every row), or None."""
    if column not in frame or frame[column].dropna().empty:
        return None
    return frame[column].dropna().iloc[0]


def statement_list(results: Sequence, file_names: Sequence[str], recon: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    One row per statement in the files loaded (a file can hold several statements or accounts), with the
    account it belongs to. `results` are statement_parser.ParseResult objects, in the same order as
    `file_names`; `recon` is the reconciliation table, for each statement's result.
    """
    rows: List[Dict] = []
    for name, result in zip(file_names, results):
        tx = result.transactions
        if tx.empty:
            continue
        text = "\n".join(result.raw_text["text"].fillna("").astype(str)) if "text" in result.raw_text else ""
        doc_level, doc_headline = verdict(getattr(result, "document_checks", []))
        for (statement_id, account_number), grp in tx.groupby(["statement_id", tx["account_number"].fillna("")], sort=False):
            raw = text
            if tx["statement_id"].nunique() > 1 and "statement_id" in result.raw_text:
                raw = "\n".join(result.raw_text.loc[result.raw_text["statement_id"] == statement_id, "text"].fillna("").astype(str))
            start, end = _statement_period(grp, raw)
            status = ""
            if recon is not None and not recon.empty:
                match = recon[(recon["statement_id"] == statement_id) & (recon["account_number"].fillna("") == account_number)]
                status = str(match["status"].iloc[0]) if not match.empty else ""
            last4 = _last_four(account_number)
            rows.append({
                "bank": _bank_name(grp, raw),
                "account_type": _account_type(grp, raw),
                "account_number": f"····{last4}" if last4 else NOT_SHOWN,
                "file": name,
                "statement_id": statement_id,
                "period_start": start,
                "period_end": end,
                "opening_balance": _first(grp, "statement_opening_balance"),
                "closing_balance": _first(grp, "statement_closing_balance"),
                "transactions": len(grp),
                "money_in": float(grp["credit"].fillna(0).sum()),
                "money_out": float(grp["debit"].fillna(0).sum()),
                "reconciliation": status,
                "document_check": doc_headline,
                "doc_level": doc_level,
                "sha256": (getattr(result, "source", {}) or {}).get("sha256", ""),
                "note": "",
                "account_key": account_number,  # as read, to find the statement's transactions again
            })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=STATEMENT_COLUMNS)
    frame = _match_unnumbered(frame)
    frame["account"] = frame["bank"] + " · " + frame["account_type"] + " " + frame["account_number"]
    return frame.sort_values(["account", "period_start", "file"], na_position="last").reset_index(drop=True)


def _same_figures(a, b) -> bool:
    """Two balances that are both known and equal to the cent."""
    return a is not None and b is not None and pd.notna(a) and pd.notna(b) and abs(float(a) - float(b)) < 0.005


def _match_unnumbered(frame: pd.DataFrame) -> pd.DataFrame:
    """
    A statement with no account number (a redacted copy) is filed under the account that has a statement
    from the same bank for the same period with the same opening and closing balances.
    """
    for i, row in frame[frame["account_number"] == NOT_SHOWN].iterrows():
        twins = frame[(frame["account_number"] != NOT_SHOWN) & (frame["bank"] == row["bank"])
                      & (frame["period_start"] == row["period_start"]) & (frame["period_end"] == row["period_end"])]
        twins = twins[[_same_figures(o, row["opening_balance"]) and _same_figures(c, row["closing_balance"])
                       for o, c in zip(twins["opening_balance"], twins["closing_balance"])]]
        if not twins.empty:
            twin = twins.iloc[0]
            frame.loc[i, ["account_type", "account_number"]] = [twin["account_type"], twin["account_number"]]
            frame.loc[i, "note"] = f"Account number not shown; filed here because its period and balances match {twin['file']}."
    return frame


def _months(start: pd.Timestamp, end: pd.Timestamp) -> List[pd.Period]:
    """Every calendar month from start to end, inclusive."""
    return list(pd.period_range(start.to_period("M"), end.to_period("M"), freq="M"))


def _follow_up(statements: pd.DataFrame) -> Tuple[List[str], List[str]]:
    """
    (missing months, things to follow up) for one account's statements: months with no statement,
    balances that don't carry forward, and statements that cover the same period.
    """
    dated = statements.dropna(subset=["period_start", "period_end"]).sort_values(["period_start", "file"])
    notes: List[str] = []
    missing: List[str] = []
    if dated.empty:
        return missing, notes
    covered = {m for _, r in dated.iterrows() for m in _months(r["period_start"], r["period_end"])}
    for month in _months(dated["period_start"].min(), dated["period_end"].max()):
        if month not in covered:
            missing.append(month.strftime("%b %Y"))
    if missing:
        notes.append(f"No statement for {', '.join(missing)}: request {'it' if len(missing) == 1 else 'them'} from the bank.")
    # Statements for the same period: copies of each other, or versions that disagree.
    seen = set()
    rows = list(dated.iterrows())
    for i, (_, a) in enumerate(rows):
        for _, b in rows[i + 1:]:
            if b["period_start"] > a["period_end"] or (a["file"], b["file"]) in seen:
                continue
            seen.add((a["file"], b["file"]))
            when = f"{a['period_start']:%m/%d}-{a['period_end']:%m/%d/%Y}"
            if _same_figures(a["opening_balance"], b["opening_balance"]) and _same_figures(a["closing_balance"], b["closing_balance"]):
                notes.append(f"{a['file']} and {b['file']} both cover {when} with the same balances: copies of one statement.")
            else:
                notes.append(f"{a['file']} and {b['file']} both cover {when} but disagree (closing balance {_money(a['closing_balance'])} "
                             f"vs {_money(b['closing_balance'])}). Get this statement directly from the bank.")
    # Each statement should open with the balance the one before it closed with.
    previous = None
    for _, row in dated.iterrows():
        if previous is not None and row["period_start"] > previous["period_end"]:
            gap_free = row["period_start"] - previous["period_end"] <= pd.Timedelta(days=5)
            if gap_free and pd.notna(previous["closing_balance"]) and pd.notna(row["opening_balance"]) \
                    and not _same_figures(previous["closing_balance"], row["opening_balance"]):
                notes.append(f"{previous['file']} closes at {_money(previous['closing_balance'])} but {row['file']} opens at "
                             f"{_money(row['opening_balance'])}: a statement or transactions may be missing.")
            previous = row
        elif previous is None:
            previous = row
    return missing, notes


def account_inventory(statements: pd.DataFrame) -> pd.DataFrame:
    """One row per account: the statements on file, the period they cover, totals, and what to follow up."""
    if statements.empty:
        return pd.DataFrame(columns=INVENTORY_COLUMNS)
    rows = []
    for account, grp in statements.groupby("account", sort=True):
        dated = grp.dropna(subset=["period_start"]).sort_values("period_start")
        missing, notes = _follow_up(grp)
        notes = [n for n in grp["note"] if n] + notes
        # Totals from one statement per period, so a duplicate copy isn't counted twice.
        primary = grp.sort_values(["doc_level", "file"], key=lambda s: s.map({"clean": 0, "review": 1, "altered": 2, "generated": 3})
                                  if s.name == "doc_level" else s).drop_duplicates(["period_start", "period_end"])
        reconciled = (grp["reconciliation"] == "Reconciled").sum()
        flagged = grp[grp["doc_level"] != "clean"]
        rows.append({
            "account": account,
            "bank": grp["bank"].iloc[0],
            "account_type": grp["account_type"].iloc[0],
            "account_number": grp["account_number"].iloc[0],
            "statements": len(grp),
            "period_start": dated["period_start"].min() if not dated.empty else None,
            "period_end": dated["period_end"].max() if not dated.empty else None,
            "months_missing": ", ".join(missing) if missing else "None",
            "opening_balance": dated["opening_balance"].iloc[0] if not dated.empty else None,
            "closing_balance": dated.sort_values("period_end")["closing_balance"].iloc[-1] if not dated.empty else None,
            "transactions": int(primary["transactions"].sum()),
            "money_in": float(primary["money_in"].sum()),
            "money_out": float(primary["money_out"].sum()),
            "reconciliation": "All reconciled" if reconciled == len(grp) else f"{reconciled} of {len(grp)} reconciled",
            "document_check": "No signs of editing" if flagged.empty else "; ".join(f"{r['file']}: {r['document_check']}" for _, r in flagged.iterrows()),
            "follow_up": " ".join(notes) if notes else "Nothing to follow up",
        })
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS)


def for_export(frame: pd.DataFrame) -> pd.DataFrame:
    """A copy with dates as mm/dd/yyyy text and readable column names, for the workpaper and downloads."""
    out = frame.drop(columns=[c for c in ("doc_level", "account_key") if c in frame]).copy()
    for column in ("period_start", "period_end"):
        if column in out:
            out[column] = pd.to_datetime(out[column]).dt.strftime("%m/%d/%Y")
    return out.rename(columns=lambda c: c.replace("_", " ").capitalize())


# --- The statements as an Excel workbook ----------------------------------------------------------

def _sheet_name(index: int, row) -> str:
    """'1 Larkspur Checking 8701': a sheet name Excel accepts (31 characters, none of []:*?/\\)."""
    bank = re.sub(r"\b(Bank|National|Credit Union|Trust|Valley|N\.A\.)\b", "", str(row["bank"])).split()
    short = " ".join(bank[:2]) or "Bank"
    kind = {"Credit card": "Card", "Deposit account": "Account"}.get(row["account_type"], row["account_type"])
    number = str(row["account_number"]).replace("····", "").replace(NOT_SHOWN, "")
    return re.sub(r"[\[\]:*?/\\]", "", f"{index} {short} {kind} {number}".strip())[:31]


def statements_workbook(statements: pd.DataFrame, inventory: pd.DataFrame, transactions: pd.DataFrame,
                        holders: Optional[Dict[str, str]] = None, title: str = "Statements by account") -> bytes:
    """
    The statements as an Excel workbook: an Accounts sheet (the inventory, each account linked to its sheet),
    then one sheet per account with every statement on file, in period order. Each statement opens with
    the balance it prints, lists its transactions with a running balance worked out by formula, and closes
    with the printed closing balance and the difference, so anyone can check the arithmetic in Excel.
    `holders` optionally names each account's holder ({account label: name}).
    """
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    navy, blue, taupe = "1D2844", "246094", "918E81"
    head_fill, tint, soft = PatternFill("solid", fgColor=navy), PatternFill("solid", fgColor="E8EFF6"), PatternFill("solid", fgColor="F4F5F7")
    warn_fill = PatternFill("solid", fgColor="FDF1EF")
    thin = Side(style="thin", color="C5D4E3")
    money, date_fmt = '#,##0.00;[Red]-#,##0.00;"-"', "mm/dd/yyyy"
    holders = holders or {}

    wb = Workbook()
    summary = wb.active
    summary.title = "Accounts"
    names = {account: _sheet_name(i, row) for i, (account, row) in enumerate(inventory.set_index("account").iterrows(), start=1)}

    def header(ws, row: int, labels: Sequence[str]) -> None:
        """A navy header row."""
        for col, label in enumerate(labels, start=1):
            cell = ws.cell(row=row, column=col, value=label)
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            cell.border = Border(bottom=thin)

    # Accounts: the inventory, with a link to each account's sheet.
    summary["A1"] = title
    summary["A1"].font = Font(name="Cambria", size=16, bold=True, color=navy)
    summary["A2"] = ("Each account has its own sheet (click its name). Running balances on those sheets are worked out by formula "
                     "from each statement's opening balance; the difference column compares them with what the bank printed.")
    summary["A2"].font = Font(size=9, color="555555")
    columns = ["Account", "Holder", "Bank", "Type", "Account no.", "Statements", "First period", "Last period", "Months missing",
               "Opening balance", "Closing balance", "Money in", "Money out", "Reconciliation", "Document check", "Follow up"]
    header(summary, 4, columns)
    for r, (_, row) in enumerate(inventory.iterrows(), start=5):
        values = [row["account"], holders.get(row["account"], ""), row["bank"], row["account_type"], row["account_number"], row["statements"],
                  row["period_start"], row["period_end"], row["months_missing"], row["opening_balance"], row["closing_balance"],
                  row["money_in"], row["money_out"], row["reconciliation"], row["document_check"], row["follow_up"]]
        for c, value in enumerate(values, start=1):
            cell = summary.cell(row=r, column=c, value=None if (value is not None and not isinstance(value, str) and pd.isna(value)) else value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(bottom=thin)
            if c in (7, 8):
                cell.value = cell.value.to_pydatetime() if isinstance(cell.value, pd.Timestamp) else cell.value
                cell.number_format = date_fmt
            if c in (10, 11, 12, 13):
                cell.number_format = money
        link = summary.cell(row=r, column=1)
        link.hyperlink = f"#'{names[row['account']]}'!A1"
        link.font = Font(color=blue, underline="single", bold=True)
        if row["follow_up"] != "Nothing to follow up":
            summary.cell(row=r, column=16).fill = warn_fill
    for col, width in zip("ABCDEFGHIJKLMNOP", (36, 30, 24, 14, 13, 13, 11, 14, 22, 18, 14, 14, 14, 16, 30, 60)):
        summary.column_dimensions[col].width = width
    summary.freeze_panes = "B5"
    summary.page_setup.orientation = "landscape"
    summary.page_setup.fitToWidth, summary.page_setup.fitToHeight = 1, 0
    summary.sheet_properties.pageSetUpPr.fitToPage = True

    # Statements on file, under the inventory.
    r0 = 5 + len(inventory) + 2
    summary.cell(row=r0, column=1, value="Statements on file").font = Font(size=12, bold=True, color=navy)
    header(summary, r0 + 1, ["Account", "File", "Period start", "Period end", "Opening balance", "Closing balance", "Transactions",
                             "Reconciliation", "Document check", "SHA-256"])
    for r, (_, row) in enumerate(statements.iterrows(), start=r0 + 2):
        values = [row["account"], row["file"], row["period_start"], row["period_end"], row["opening_balance"], row["closing_balance"],
                  row["transactions"], row["reconciliation"], row["document_check"], row["sha256"]]
        for c, value in enumerate(values, start=1):
            if isinstance(value, pd.Timestamp):
                value = value.to_pydatetime()
            cell = summary.cell(row=r, column=c, value=None if (value is not None and not isinstance(value, str) and pd.isna(value)) else value)
            cell.number_format = date_fmt if c in (3, 4) else money if c in (5, 6) else "General"
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(wrap_text=c in (1, 2, 9), vertical="top")
        summary.cell(row=r, column=2).hyperlink = f"#'{names[row['account']]}'!A1"

    # One sheet per account.
    cols = ["Date", "Description", "Money in", "Money out", "Balance (worked out)", "Balance (printed)", "Difference",
            "Check no.", "Category", "Page", "Line"]
    for account, inv in inventory.set_index("account").iterrows():
        ws = wb.create_sheet(names[account])
        ws.sheet_properties.tabColor = blue
        card = inv["account_type"] == "Credit card"
        ws["A1"] = account
        ws["A1"].font = Font(name="Cambria", size=14, bold=True, color=navy)
        ws["A2"] = " · ".join(x for x in (holders.get(account, ""), f"{inv['statements']} statement{'s' if inv['statements'] != 1 else ''}",
                                          f"months missing: {inv['months_missing']}") if x)
        ws["A3"] = f"Follow up: {inv['follow_up']}"
        ws["A3"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells("A3:K3")
        ws.row_dimensions[3].height = 15 * max(1, min(6, len(inv["follow_up"]) // 140 + 1))
        if inv["follow_up"] != "Nothing to follow up":
            ws["A3"].fill = warn_fill
        ws["A4"] = ("A card balance goes up with charges and down with payments." if card else
                    "The balance goes up with money in and down with money out.") + \
                   " Lines are in the order the statement prints them (in date order when it groups them by type)."
        ws["A4"].font = Font(size=9, italic=True, color=taupe)
        header(ws, 6, cols)
        r = 7
        for _, stmt in statements[statements["account"] == account].sort_values(["period_start", "file"]).iterrows():
            tx = transactions[(transactions["statement_id"] == stmt["statement_id"])
                              & (transactions["account_number"].fillna("") == stmt["account_key"])]
            printed_balances = tx["running_balance"].notna().any() if "running_balance" in tx else False
            tx = tx.sort_values(["source_page", "source_line"] if printed_balances else ["txn_date", "source_page", "source_line"])
            period = (f"{stmt['period_start']:%m/%d/%Y} – {stmt['period_end']:%m/%d/%Y}" if pd.notna(stmt["period_start"]) else "period not shown")
            ws.cell(row=r, column=1, value=f"{stmt['file']}   ·   {period}   ·   {stmt['reconciliation'] or 'not reconciled'}   ·   {stmt['document_check']}")
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=11)
            questioned = stmt["doc_level"] != "clean" or bool(stmt["note"])
            ws.cell(row=r, column=1).font = Font(bold=True, color="B42318" if stmt["doc_level"] in ("altered", "generated") else navy)
            ws.cell(row=r, column=1).fill = warn_fill if questioned else tint
            r += 1
            ws.cell(row=r, column=2, value="Opening balance (per statement)").font = Font(italic=True)
            opening = stmt["opening_balance"]
            ws.cell(row=r, column=5, value=None if opening is None or pd.isna(opening) else float(opening)).number_format = money
            ws.cell(row=r, column=6, value=None if opening is None or pd.isna(opening) else float(opening)).number_format = money
            first_tx = r + 1
            for _, t in tx.iterrows():
                r += 1
                when = t["txn_date"].to_pydatetime() if pd.notna(t["txn_date"]) else t.get("txn_date_raw")
                values = [when, t["description"], None if pd.isna(t["credit"]) else float(t["credit"]),
                          None if pd.isna(t["debit"]) else float(t["debit"])]
                for c, value in enumerate(values, start=1):
                    ws.cell(row=r, column=c, value=value)
                ws.cell(row=r, column=1).number_format = date_fmt
                sign = f"E{r - 1}+N(D{r})-N(C{r})" if card else f"E{r - 1}+N(C{r})-N(D{r})"
                ws.cell(row=r, column=5, value=f'=IF(E{r - 1}="","",{sign})').number_format = money
                if printed_balances and pd.notna(t["running_balance"]):
                    ws.cell(row=r, column=6, value=float(t["running_balance"])).number_format = money
                    ws.cell(row=r, column=7, value=f'=IF(OR(E{r}="",F{r}=""),"",ROUND(F{r}-E{r},2))').number_format = money
                for c, key in ((8, "check_number"), (9, "txn_category"), (10, "source_page"), (11, "source_line")):
                    value = t.get(key)
                    if key == "txn_category" and isinstance(value, str):
                        value = value.replace("_", " ").capitalize()  # "card_purchase" -> "Card purchase"
                    ws.cell(row=r, column=c, value=None if value is None or (not isinstance(value, str) and pd.isna(value)) else value)
                for c in (3, 4):
                    ws.cell(row=r, column=c).number_format = money
            last_tx = r
            r += 1
            ws.cell(row=r, column=2, value="Closing balance (per statement) and totals").font = Font(bold=True)
            if last_tx >= first_tx:
                ws.cell(row=r, column=3, value=f"=SUM(C{first_tx}:C{last_tx})")
                ws.cell(row=r, column=4, value=f"=SUM(D{first_tx}:D{last_tx})")
            ws.cell(row=r, column=5, value=f"=E{r - 1}")
            closing = stmt["closing_balance"]
            ws.cell(row=r, column=6, value=None if closing is None or pd.isna(closing) else float(closing))
            ws.cell(row=r, column=7, value=f'=IF(OR(E{r}="",F{r}=""),"",ROUND(F{r}-E{r},2))')
            for c in range(1, 12):
                cell = ws.cell(row=r, column=c)
                cell.fill, cell.border = soft, Border(top=thin, bottom=thin)
                cell.font = Font(bold=True)
                if c in (3, 4, 5, 6, 7):
                    cell.number_format = money
            r += 2
        for col, width in zip("ABCDEFGHIJK", (11, 52, 13, 13, 15, 15, 11, 9, 18, 6, 6)):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "C7"
        ws.cell(row=1, column=11, value="Back to Accounts").hyperlink = "#'Accounts'!A1"
        ws.cell(row=1, column=11).font = Font(color=blue, underline="single", size=9)
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "6:6"

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
