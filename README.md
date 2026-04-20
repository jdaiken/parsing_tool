# Statement Workpaper Parser

Basic Streamlit app for converting bank statement PDFs into a forensic accounting workpaper in Excel. This app right now only uses two very simple statements. Additional statements can be added later.

## Features
- Upload one or more statement PDFs
- Parse transactions from supported layouts
- Auto-flag potentially interesting transactions
- Export formatted `.xlsx` workpaper with review tabs

## Quick Start
1. Create and activate a Python virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Run the app:
   - `streamlit run app.py`

## Output Tabs
- `Summary`
- `Transactions`
- `Flags_For_Review`
- `Raw_Text` (optional)
