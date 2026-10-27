# Bank Statement Analyzer

Turn bank statement PDFs into forensic accounting workpapers in minutes. Built for the Justice for Fraud Victims Project and for forensic accounting students.

Upload one or more statement PDFs and the app:
- reads the transactions automatically, even from banks it has never seen
- checks every running balance so you can see whether it read the statement correctly
- flags transactions worth a closer look (large, round-dollar, duplicates, check gaps, and more)
- runs a bank reconciliation for each account
- exports a formatted Excel workpaper and summary financial statements

The **Dashboard** tab has interactive charts (cash flow over time, balances, transaction types, red flags, a risk timeline, top payees and day-of-week patterns). Filter by date, account, transaction type, direction, risk or a search word, then export exactly what you selected: Excel, CSV, or a self-contained interactive HTML dashboard. Each chart can also be saved as an image.

**Statements stay private.** Both versions below process files on your own computer. Nothing is uploaded to a server.

## Option 1: Use it in your web browser (no install)

Host this folder on any static web host. For GitHub Pages: repository **Settings → Pages**, deploy from the `main` branch, root folder. Then open the Pages link. The first visit downloads the app (about 40 MB); after that it runs entirely inside the browser tab.

To try the browser version on your own machine, run `python -m http.server` in this folder and open http://localhost:8000.

## Option 2: Run it on your computer

1. Install Python 3.10 or newer.
2. In this folder, create and activate a virtual environment:
   - Windows: `python -m venv .venv` then `.venv\Scripts\activate`
   - Mac/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Start the app: `streamlit run app.py`

It opens at http://localhost:8501. `.streamlit/config.toml` keeps it private: only this computer can open it, and no usage statistics are sent.

## Scanned, redacted and credit card statements

- **Scanned statements** (pages that are pictures, such as a printout that was scanned) are read with OCR on your own computer. The OCR models come with `pip install -r requirements.txt`, nothing is downloaded or uploaded, and it works offline. Expect a few seconds per page. The in-browser version can't run OCR, so use the version on your computer for scans.
- **Redacted statements:** blacked-out text shows as `[redacted]`. If an amount is blacked out but the running balance isn't, the amount is worked out from the change in balance. If black boxes were drawn over text that is still in the PDF (a common redaction mistake), the app hides that text and warns you not to share the file as redacted.
- **When balances are redacted**, the reconciliation uses the totals printed on the statement instead (for example "10 Total Deposits: $8,337.98"). The app's totals and item counts must match them, which shows every transaction was read.
- **Credit card statements** are recognized automatically. Charges, fees and interest are money out; payments and refunds are money in. The reconciliation checks previous balance + charges − payments = new balance.
- **Several monthly statements in one PDF** are split into separate statements by statement period.

## Banks it knows

Statements from any bank are read the same way, with no setup. 57 major US banks, credit unions and card issuers (Chase, Bank of America, Wells Fargo, Citi, Capital One, American Express, Navy Federal and others; full list in `bank_directory.py`) are also labelled by name when the name is printed as text near the top of the statement. That label is the only thing the list does.

The reader handles these common layouts:

- money in and money out in separate columns with no minus signs (read from the column each amount sits under);
- a balance printed only on the last line of each day (each day's lines are checked against it);
- section headings such as "Deposits and other additions" and "Withdrawals and other subtractions", with section totals;
- credit card statements with payments printed as negatives.

What has been tested:

- **Real statements:** a scanned, redacted credit-union statement (3 months, 2 accounts; every account agrees with the statement's printed totals) and the two samples in this folder.
- **Public synthetic US-style statements with published correct answers** (fictional banks, no real data; from [robin421/bank-statement-to-excel](https://github.com/robin421/bank-statement-to-excel) and the [bankstatemently benchmark](https://github.com/bankstatemently/bank-statement-parsing-benchmark)): Chase-, Bank of America- and Wells Fargo-style checking, a savings statement with no balance column, a credit union with negatives in parentheses, a 3-page business statement with debit/credit columns, and a credit card. All 141 transactions with published answers were read exactly right, and every statement that prints balances or totals reconciles.
- No real statements from the 57 named banks have been tested yet. The Bank Reconciliation tab shows a variance if a statement wasn't read correctly.

## Adding a new bank

You don't need to add a bank to use it. Saving a bank in the **Add a New Bank** tab only labels its statements by name: upload one statement, check the preview, and click **Save this bank**. If a statement doesn't reconcile, saving the bank won't fix it; that needs a change to the reader.

## Excel workpaper tabs
- `Summary`
- `Transactions`
- `Risk_Summary`
- `Flags_For_Review`
- `Raw_Text` (optional)

## Files

| File | What it does |
| --- | --- |
| `app.py` | The app's screens |
| `auto_parser.py` | Reads statements from any bank without a template, including credit card and redacted statements |
| `pdf_text.py` | Gets the text out of each PDF page; hides text under black redaction boxes |
| `ocr.py` | Reads scanned pages on your own computer |
| `statement_parser.py` | Picks a reader for each statement; built-in bank layouts; risk scoring and flags |
| `dashboard.py` | Dashboard charts and exports |
| `bank_directory.py` | Built-in list of banks and card issuers recognized by name |
| `template_manager.py` | Saves and recognizes the banks you add |
| `workpaper_export.py`, `financial_statements.py` | Excel exports |
| `index.html`, `web_app.py` | The in-browser version |

## Trying it without a statement

Click **Try it with sample statements** under the upload box. It loads the two sample PDFs in this folder.

## Branding

- **Logo:** save the organization's logo as `assets/logo.png` (or `logo.svg` / `logo.jpg`). Both versions pick it up automatically.
- **Name and colors:** set at the top of `app.py` (`APP_NAME`, `ORG_NAME`, `NAVY`, `BLUE`, `TAUPE`, `LIGHT`), in `.streamlit/config.toml`, and in `index.html`.
