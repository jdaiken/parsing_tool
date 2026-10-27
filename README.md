# Bank Statement Analyzer

Turn bank statement PDFs into forensic accounting workpapers in minutes. Built for the Justice for Fraud Victims Project and for forensic accounting students.

Upload one or more statement PDFs and the app:
- reads the transactions automatically, even from banks it has never seen
- checks every running balance so you can see whether it read the statement correctly
- flags transactions worth a closer look (large, round-dollar, duplicates, check gaps, and more)
- looks for fraud patterns across all the statements together: cash kept under $10,000 (structuring), gambling, gift cards, new payees taking large sums, money in and straight back out, sudden jumps in cash, a draining balance, overdrafts, duplicate payments and card cash advances
- checks each file for signs it was edited (the **Document Check** tab)
- runs a bank reconciliation for each account
- exports a formatted Excel workpaper and summary financial statements

The **Dashboard** tab has interactive charts (cash flow over time, balances, transaction types, red flags, a risk timeline, top payees and day-of-week patterns). Filter by date, account, transaction type, direction, risk or a search word, then export exactly what you selected: Excel, CSV, or a self-contained interactive HTML dashboard. Each chart can also be saved as an image.

**Statements stay private.** The versions below read statements on your own computer; nothing is uploaded. Projects are encrypted with a password, and every workpaper records each statement's SHA-256 fingerprint. See [SECURITY.md](SECURITY.md) and the [security and data handling guide](docs/SECURITY_AND_DATA_HANDLING.md) before using it on real cases.

## Ways to use it

| | Where statements are read | For |
| --- | --- | --- |
| **On your computer** (below) | On your computer; includes OCR for scans | Real cases |
| **Hosted by your university or organization** ([deployment guide](docs/UNIVERSITY_DEPLOYMENT.md)) | In each person's browser (option 1), or on your organization's approved server behind its sign-in (option 2) | Real cases and classes |
| **Public demo** (Streamlit Community Cloud, GitHub Pages) | Streamlit Cloud uploads files to its servers | The fictional demo case only |

### Hosting it at a university or organization

Two options, both with Docker images and step-by-step instructions in [docs/UNIVERSITY_DEPLOYMENT.md](docs/UNIVERSITY_DEPLOYMENT.md):

1. **Browser version** (`deploy/browser`): a static website. Each person's browser runs the app and reads statements locally; the page is blocked from contacting any address but your server, so the server never holds case data. `python tools/build_offline.py` builds the self-contained folder (every downloaded part is checked against a pinned fingerprint), or use the nginx image.
2. **Server version** (`deploy/server`): the full app, including OCR, on your server behind your single sign-on (oauth2-proxy with Microsoft Entra ID, Google, Okta or any OpenID Connect provider). Each person sees only their own projects.

### Quick browser demo

`index.html` in this folder runs the app in a browser using public CDNs (handy for GitHub Pages: **Settings → Pages**, deploy from `main`, root folder). For real cases, use the self-contained build above instead. To try it locally: `python -m http.server`, then open http://localhost:8000.

## Run it on your computer

**Easiest:** install [Python](https://www.python.org/downloads/) (3.11 or newer; on Windows tick "Add python.exe to PATH"), then double-click `start.bat` (Windows) or run `./start.sh` (Mac/Linux). The first start installs what the app needs; after that it starts straight away.

**In VS Code:** in the app's sidebar, click **Open in VS Code** (copies the app from GitHub; needs VS Code and Git) or **Download the app (.zip)** and open the unzipped folder with **File → Open Folder**. Then choose **Terminal → Run Task → Start the app**. Once it has been set up, **Run → Start Debugging** (F5) also starts it, so you can set breakpoints.

**By hand:**

1. Install Python 3.11 or newer.
2. In this folder, create and activate a virtual environment:
   - Windows: `python -m venv .venv` then `.venv\Scripts\activate`
   - Mac/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
3. Install dependencies: `pip install --require-hashes -r requirements-lock.txt` (exact, fingerprint-checked versions)
4. Start the app: `streamlit run app.py`

It opens at http://localhost:8501. `.streamlit/config.toml` keeps it private: only this computer can open it, and no usage statistics are sent.

## Projects

A project keeps one case's statements and your notes together, encrypted with a password you choose. Create one in the sidebar (**New project**): give it a case number as its name (the name is the only thing stored unencrypted) and a password of at least 10 characters. A lost password can't be recovered, so keep it in a password manager. While it is open:

- statements you upload are saved in the project, and every statement in it is analyzed together;
- the **Project** tab holds your case notes and a note for each statement, and lets you remove a statement;
- the Transactions tab has a **Note** column for notes on single transactions;
- notes go into the Excel workpaper (a `Case_Notes` sheet and a Note column) and the dashboard exports;
- a **case log** records when statements were added (with their SHA-256 fingerprints) or removed, notes were saved and the project was downloaded.

**Lock project** (sidebar) closes it until the password is typed again. On the Project tab, **Download the project** saves everything in one encrypted `.bsacase` file with a password you type (send it separately from the file); **Open a project file** in the sidebar opens it again, on this computer or another. **Close case and erase** removes the project from the app. Projects made before encryption was added open as before, with a prompt to protect them with a password.

Where projects are kept:

- **On your computer:** in the `projects` folder next to the app. It is listed in `.gitignore`, so case files are never committed to git.
- **In-browser version:** in that browser's storage, on that computer only.
- **A hosted copy** (such as Streamlit Community Cloud): only until the tab is closed, because the server is shared. Download the project to keep it. For confidential statements, use one of the versions above.

## Spotting doctored statements

The **Document Check** tab looks at each file for the traces an edited statement usually leaves:

- the PDF was made or re-saved with an editing tool (iLovePDF, Smallpdf, Word, Canva and others), or saved again long after it was created;
- a few transaction lines use a different font from the rest;
- transactions dated outside the statement period, or out of date order;
- a line that says money came in ("payment from") while the balance went down;
- running balances that don't follow from the line before;
- summary totals that don't agree with the transactions;
- an amount formatted differently from the rest (for example no thousands comma).

A warning is a reason to get the statement directly from the bank; a clean result doesn't prove a statement is genuine. On a scanned copy the file details and fonts can't be checked, so fewer checks run. Day-first dates (31/01) aren't fully supported yet, so the date checks are skipped on those statements.

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
- `Summary` (with the app version, analyst, project and time zone)
- `Evidence` (each statement's SHA-256 fingerprint, pages, OCR, transactions, reconciliation and document check)
- `Case_Notes` and `Case_Log` (when a project is open)
- `Transactions` (each row names its source file, fingerprint, page and line)
- `Risk_Summary`
- `Flags_For_Review` (including the fraud patterns found)
- `Document_Checks`
- `Raw_Text` (optional)

## Files

| File | What it does |
| --- | --- |
| `app.py` | The app's screens |
| `auto_parser.py` | Reads statements from any bank without a template, including credit card and redacted statements |
| `pdf_text.py` | Gets the text out of each PDF page; hides text under black redaction boxes |
| `ocr.py` | Reads scanned pages on your own computer |
| `statement_parser.py` | Picks a reader for each statement; built-in bank layouts; risk scoring and flags |
| `fraud_rules.py` | Fraud patterns across all statements (structuring, gambling, new payees and more) |
| `authenticity.py` | Document checks for signs a statement was edited |
| `payees.py` | Short, consistent payee names ("ZELLE PAYMENT TO DANA PRUITT ..." becomes "Dana Pruitt") |
| `dashboard.py` | Dashboard charts and exports |
| `bank_directory.py` | Built-in list of banks and card issuers recognized by name |
| `template_manager.py` | Saves and recognizes the banks you add |
| `projects.py` | Encrypted project folders: statements, notes and the case log |
| `reconciliation.py` | Bank reconciliation against each statement's own figures |
| `version.py` | The app version printed on workpapers |
| `start.bat`, `start.sh`, `.vscode/` | One-click start, and VS Code run and debug settings |
| `workpaper_export.py`, `financial_statements.py` | Excel exports |
| `index.html`, `web_app.py` | The in-browser version (quick demo, loads from public CDNs) |
| `tools/build_offline.py` | Builds the self-contained browser version for hosting |
| `deploy/browser/`, `deploy/server/` | Docker images for the two hosting options |
| `requirements-lock.txt` | Exact, fingerprinted versions of every package |
| `tests/` | Automated tests (`python -m pytest`); they run on every push |
| `SECURITY.md`, `docs/` | Security policy, data handling guide, deployment guide |
| `demo/` | A fictional fraud case for demos and teaching, with an answer key |

## Trying it without a statement

The `demo/` folder holds a fictional elder-financial-exploitation case: three months of checking at a made-up bank, a credit card, a doctored "family copy" of one month, and a scanned, redacted copy. `demo/ANSWER_KEY.md` lists everything planted in it and where the app finds it.

- **Try it with sample statements** (under the upload box) loads the three checking statements and the credit card.
- **Try a doctored statement** loads a genuine month next to the doctored copy, so the Document Check tab can show the difference.
- To show OCR, drag `demo/6_checking_2025-05_scanned_redacted.pdf` into the version that runs on your computer.

## Tests

`python -m pytest` runs the tests: the demo statements reconcile, every planted fraud pattern and document edit is found, projects are unreadable without their password, and the two hosting options stay locked down. GitHub runs them on every push, and builds both Docker images. Dependabot proposes updates to packages, base images and GitHub Actions weekly.

## Branding

- **Logo:** save the organization's logo as `assets/logo.png` (or `logo.svg` / `logo.jpg`). Both versions pick it up automatically.
- **Name and colors:** set at the top of `app.py` (`APP_NAME`, `ORG_NAME`, `NAVY`, `BLUE`, `TAUPE`, `LIGHT`), in `.streamlit/config.toml`, and in `index.html`.
