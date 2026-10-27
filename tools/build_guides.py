"""
Render the branded guides in docs/guides/*.html to PDF (docs/*.pdf).

    python tools/build_guides.py

Needs Node.js with Playwright and its Chromium browser (npm install playwright; npx playwright
install chromium) and pdfplumber (already an app dependency). Each guide is rendered twice:
the first pass finds the page each chapter starts on, which is written into the table of
contents (in the HTML too, so the source stays in step), then the final PDF is rendered.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
GUIDES = {
    "user_guide.html": ("User Guide", ROOT / "docs" / "Bank_Statement_Analyzer_User_Guide.pdf"),
    "implementation_guide.html": ("Implementation Guide", ROOT / "docs" / "Bank_Statement_Analyzer_Implementation_Guide.pdf"),
}

# The cover is rendered on its own without the page footer, then put in front of the other pages.
RENDER_JS = r"""
const { chromium } = require('playwright');
const [src, out, title, coverOut] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + src, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({
    path: out, format: 'Letter', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: `<div style="width:100%;font-family:Helvetica,Arial,sans-serif;font-size:7.5pt;color:#5B6575;
      padding:0 0.75in;display:flex;justify-content:space-between;">
      <span>Bank Statement Analyzer · ${title}</span>
      <span>Justice for Fraud Victims Project · <span class="pageNumber"></span></span></div>`,
  });
  await page.pdf({ path: coverOut, format: 'Letter', printBackground: true, preferCSSPageSize: true, pageRanges: '1' });
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def render(src: Path, out: Path, title: str) -> None:
    """Render one guide to PDF: the body with page footers, the cover without, joined into one file."""
    with tempfile.TemporaryDirectory() as work:
        script, body, cover = Path(work) / "render.js", Path(work) / "body.pdf", Path(work) / "cover.pdf"
        script.write_text(RENDER_JS, encoding="utf-8")
        subprocess.run(["node", str(script), str(src), str(body), title, str(cover)], check=True)
        merged = pdfium.PdfDocument.new()
        merged.import_pages(pdfium.PdfDocument(cover), [0])
        rest = pdfium.PdfDocument(body)
        merged.import_pages(rest, list(range(1, len(rest))))
        merged.save(out)


def chapter_pages(pdf_path: Path, titles: list[str]) -> dict[int, int]:
    """Chapter number -> page its heading ("4. Reading the results") is on, wherever on the page it falls."""
    pages: dict[int, int] = {}
    with pdfplumber.open(pdf_path) as pdf:
        texts = [[line.strip() for line in (page.extract_text() or "").splitlines()] for page in pdf.pages]
    for number, title in enumerate(titles, start=1):
        heading = f"{number}. {title}"
        for page_number, lines in enumerate(texts, start=1):
            if page_number > 2 and heading in lines:
                pages[number] = page_number
                break
    return pages


def build(name: str, title: str, out: Path) -> None:
    """Render a guide, write the page each chapter starts on into its table of contents, and render it again."""
    src = ROOT / "docs" / "guides" / name
    render(src, out, title)
    html = src.read_text(encoding="utf-8")
    toc = html[html.index('<section class="toc">'):html.index("</section>", html.index('<section class="toc">'))]
    items = re.findall(r"<li>.*?</li>", toc)
    pages = chapter_pages(out, [re.sub(r"\s*<span>.*", "", item[4:]).replace("&amp;", "&") for item in items])
    new_toc = toc
    for index, item in enumerate(items, start=1):
        number = pages.get(index)
        if number:
            new_toc = new_toc.replace(item, re.sub(r"<span>\d*</span>", f"<span>{number}</span>", item), 1)
    if new_toc != toc:
        src.write_text(html.replace(toc, new_toc), encoding="utf-8")
        render(src, out, title)
    print(f"{out.relative_to(ROOT)}: {len(pdfplumber.open(out).pages)} pages; chapters start on {pages}")


def main() -> None:
    """Build every guide in GUIDES."""
    for name, (title, out) in GUIDES.items():
        build(name, title, out)


if __name__ == "__main__":
    sys.exit(main())
