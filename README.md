# Bank Statement Analyzer

Turn bank statement PDFs into forensic accounting workpapers in minutes. Built for the Justice for Fraud Victims Project and for forensic accounting students.

Upload one or more statement PDFs and the app:
- reads the transactions automatically, even from banks it has never seen
- checks every running balance so you can see whether it read the statement correctly
- flags transactions worth a closer look (large, round-dollar, duplicates, check gaps, and more)
- runs a bank reconciliation for each account
- exports a formatted Excel workpaper and summary financial statements

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

## Adding a new bank

Most statements are read automatically. To make a bank's statements always recognized, open the **Add a New Bank** tab, upload one statement, check the preview, and click **Save this bank**. Nothing else to fill in.

Statements must be PDFs downloaded from online banking. Scanned paper statements can't be read.

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
| `auto_parser.py` | Reads statements from any bank without a template |
| `statement_parser.py` | Picks a reader for each statement; built-in bank layouts; risk scoring and flags |
| `template_manager.py` | Saves and recognizes the banks you add |
| `workpaper_export.py`, `financial_statements.py` | Excel exports |
| `index.html`, `web_app.py` | The in-browser version |

## Trying it without a statement

Click **Try it with sample statements** under the upload box. It loads the two sample PDFs in this folder.

## Branding

- **Logo:** save the organization's logo as `assets/logo.png` (or `logo.svg` / `logo.jpg`). Both versions pick it up automatically.
- **Name and colors:** set at the top of `app.py` (`APP_NAME`, `ORG_NAME`, `NAVY`, `GOLD`), in `.streamlit/config.toml`, and in `index.html`.
