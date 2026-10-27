"""
Entry point for the in-browser version (index.html, powered by stlite).

Not used by `streamlit run app.py`. pdfplumber lists pypdfium2 as a dependency,
but pypdfium2 has no browser build and pdfplumber only needs it to render page
images, which this app never does. So pdfplumber is installed without it, then
the normal app runs unchanged.
"""

import runpy

try:
    import pdfplumber  # noqa: F401
except ImportError:
    import micropip

    await micropip.install("pdfplumber==0.11.10", deps=False)  # noqa: F704 (stlite allows top-level await)

runpy.run_path("app.py", run_name="__main__")
