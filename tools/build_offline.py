"""
Build the self-contained ("offline") browser version: one folder a university or organization
puts on its own web server.

Everything the page needs is inside the folder: the app, the in-browser Python engine
(Pyodide), Streamlit for the browser (stlite), the Python packages and the fonts. The page's
Content Security Policy only allows the browser to load from, and connect to, the server it
came from, so statements can't be sent anywhere, even by a bug or a tampered library.

Every downloaded file is checked against the SHA-256 (or npm SHA-512) fingerprint pinned
below; the build stops if any file differs. SHA256SUMS.txt in the output lists the
fingerprint of every file, so an IT team can verify the folder they deploy.

    python tools/build_offline.py                       # writes dist/offline/
    python tools/build_offline.py --pyodide-dir DIR     # use an already-downloaded Pyodide 0.29.3 distribution

Needs Python 3.10+ and internet access to registry.npmjs.org, cdn.jsdelivr.net (Pyodide
packages) and files.pythonhosted.org. The output works with no internet access at all.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STLITE = (
    "https://registry.npmjs.org/@stlite/browser/-/browser-1.10.0.tgz",
    "sha512-uDxUOgkWU97UI73AJ2NdziKeXkm4g7f9QYzK0Wv8l0cvsmn1fr2eASZ4hspDt4tSizwWwkAxKJ+Q/WUu7swXcQ==",
)
PYODIDE_CORE = (
    "https://registry.npmjs.org/pyodide/-/pyodide-0.29.3.tgz",
    "sha512-22UBuhOJawj7vKUnS7/F3xK+515LJdjiMAHoCfuS6/PbHiOrSQVnYwDe+2sbVwiOZ3sMMexdXICew6NqOMQGgA==",
)
PYODIDE_CORE_FILES = {
    "pyodide.mjs": "23213d27e9dacbda6f25f955fb38dabfc40ada082c04ee253047ea5dddcaa3b5",
    "pyodide.asm.js": "1263f02b5b26099b96112378156f242dd98b39a8201ba7765e5fe3d455c5ce91",
    "pyodide.asm.wasm": "e2f4ee75b325e35eb31bfb8c613d4dd5098f5502c156a97847686875b5025480",
    "python_stdlib.zip": "4298b6ee445cb724c3973437da47789752b9e6ff4e26619026b283ec801fc46b",
    "pyodide-lock.json": "3256ffc76388de0e37f4b34d42ab484268d1afc675179ff97b2a5bb14f84ccac",
}
PYODIDE_PACKAGES_URL = "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/"
# Pyodide packages the app loads (their fingerprints come from the pinned pyodide-lock.json).
PYODIDE_PACKAGES = [
    "altair", "anyio", "attrs", "cffi", "charset-normalizer", "cramjam", "cryptography", "fastparquet", "fsspec",
    "jinja2", "jsonschema", "jsonschema-specifications", "libopenssl", "markupsafe", "micropip", "narwhals", "numpy",
    "packaging", "pandas", "pillow", "pycparser", "pyodide-http", "pyrsistent", "python-dateutil", "pytz",
    "referencing", "rpds-py", "six", "sniffio", "ssl", "starlette", "typing-extensions",
]
# Pure-Python packages from PyPI that aren't part of Pyodide.
PYPI_WHEELS = [
    ("itsdangerous-2.2.0-py3-none-any.whl", "https://files.pythonhosted.org/packages/04/96/92447566d16df59b2a776c0fb82dbc4d9e07cd95062562af01e408583fc4/itsdangerous-2.2.0-py3-none-any.whl", "c6242fc49e35958c8b15141343aa660db5fc54d4f13a1db01a3f5891b98700ef"),
    ("blinker-1.9.0-py3-none-any.whl", "https://files.pythonhosted.org/packages/10/cb/f2ad4230dc2eb1a74edf38f1a38b9b52277f75bef262d8908e60d957e13c/blinker-1.9.0-py3-none-any.whl", "ba0efaa9080b619ff2f3459d1d500c57bddea4a6b424b60a91141db6fd2f08bc"),
    ("python_multipart-0.0.32-py3-none-any.whl", "https://files.pythonhosted.org/packages/e1/04/e8135ebd1ad02c56ec633277529b2602ff99ff634be76cdba5744cf554fd/python_multipart-0.0.32-py3-none-any.whl", "ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23"),
    ("protobuf-7.36.2-py3-none-any.whl", "https://files.pythonhosted.org/packages/e4/04/d52c7016b04b6c5108f26691f9d33ec82a9b65d041f1a9c771137693d618/protobuf-7.36.2-py3-none-any.whl", "bdb3a345d48db958e6ce1f18e508beb0cc981d64f24088427549c866cd039f1e"),
    ("pdfminer_six-20260107-py3-none-any.whl", "https://files.pythonhosted.org/packages/20/8b/28c4eaec9d6b036a52cb44720408f26b1a143ca9bce76cc19e8f5de00ab4/pdfminer_six-20260107-py3-none-any.whl", "366585ba97e80dffa8f00cebe303d2f381884d8637af4ce422f1df3ef38111a9"),
    ("pdfplumber-0.11.10-py3-none-any.whl", "https://files.pythonhosted.org/packages/a2/9a/07d658e1e7fad860f1c541ab941348125dbdab773be3a0afaf32361866c7/pdfplumber-0.11.10-py3-none-any.whl", "7741ea81bf165b474b153e6789d10d18e06b6ddcf3ec84289c3ef2fed6802580"),
    ("openpyxl-3.1.5-py2.py3-none-any.whl", "https://files.pythonhosted.org/packages/c0/da/977ded879c29cbd04de313843e76868e6e13408a94ed6b987245dc7c8506/openpyxl-3.1.5-py2.py3-none-any.whl", "5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2"),
    ("et_xmlfile-2.0.0-py3-none-any.whl", "https://files.pythonhosted.org/packages/c1/8b/5fe2cc11fee489817272089c4203e679c63b570a5aaeb18d852ae3cbba6a/et_xmlfile-2.0.0-py3-none-any.whl", "7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa"),
    ("plotly-7.1.0-py3-none-any.whl", "https://files.pythonhosted.org/packages/e5/7d/905a3a3d51087515719058c94cfbda2ff0fc14417c20d557ae3e82d8b250/plotly-7.1.0-py3-none-any.whl", "dbb7fa18afce40d0a8e80d1bf162eceb3faa0ce5a77fe741ad09a74cf78f53f3"),
]
# pdfplumber is installed without its dependencies: pypdfium2 has no browser build, and pdfplumber
# needs it only to render page images, which the app never does in the browser.
NO_DEPS_WHEEL = "pdfplumber-0.11.10-py3-none-any.whl"

APP_FILES = [
    "app.py", "authenticity.py", "auto_parser.py", "bank_directory.py", "dashboard.py", "financial_statements.py",
    "fraud_rules.py", "ocr.py", "payees.py", "pdf_text.py", "projects.py", "statement_parser.py", "template_manager.py",
    "version.py", "workpaper_export.py", "web_app.py",
    "assets/logo.png", "assets/fonts/inter-latin-wght-normal.woff2", "assets/fonts/jost-latin-wght-normal.woff2",
    "assets/fonts/cormorant-garamond-latin-wght-italic.woff2", "assets/fonts/LICENSE-Inter.txt",
    "assets/fonts/LICENSE-Jost.txt", "assets/fonts/LICENSE-CormorantGaramond.txt",
    "demo/1_checking_2025-03.pdf", "demo/2_checking_2025-04.pdf", "demo/3_checking_2025-05.pdf",
    "demo/4_credit_card_2025-05.pdf", "demo/5_checking_2025-04_family_copy.pdf",
    "demo/6_checking_2025-05_scanned_redacted.pdf", "demo/ANSWER_KEY.md", "demo/make_demo_case.py",
    "requirements.txt", "README.md", "SECURITY.md", "docs/SECURITY_AND_DATA_HANDLING.md", "docs/UNIVERSITY_DEPLOYMENT.md",
    "start.bat", "start.sh", ".streamlit/config.toml",
]

# Only this server; Python runs in a worker started from a blob: URL, which inherits this policy.
CSP = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval' blob:; worker-src 'self' blob:; "
    "connect-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "img-src 'self' data: blob:; media-src 'self' data: blob:; frame-src 'self' blob: data:; "
    "manifest-src 'self'; base-uri 'self'; form-action 'none'; object-src 'none'"
)
HEADERS = {
    "Content-Security-Policy": CSP + "; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def fetch(url: str) -> bytes:
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def check_sha256(data: bytes, expected: str, what: str) -> None:
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        sys.exit(f"Fingerprint mismatch for {what}: expected {expected}, got {actual}. Stopping.")


def check_npm(data: bytes, integrity: str, what: str) -> None:
    algorithm, expected = integrity.split("-", 1)
    actual = base64.b64encode(hashlib.new(algorithm, data).digest()).decode("ascii")
    if actual != expected:
        sys.exit(f"Fingerprint mismatch for {what}. Stopping.")


def npm_package(spec: tuple, cache: Path) -> tarfile.TarFile:
    url, integrity = spec
    cached = cache / url.rsplit("/", 1)[1]
    data = cached.read_bytes() if cached.exists() else fetch(url)
    check_npm(data, integrity, url)
    cached.write_bytes(data)
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def build(out: Path, pyodide_dir: Path | None, cache: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    vendor = out / "vendor"
    cache.mkdir(parents=True, exist_ok=True)

    print("stlite (Streamlit in the browser)")
    with npm_package(STLITE, cache) as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("package/build/")
            if member.isfile() and member.name.startswith("package/build/") and not name.endswith(".map"):
                target = vendor / "stlite" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
        license_member = tar.getmember("package/LICENSE") if "package/LICENSE" in tar.getnames() else None
        if license_member:
            (vendor / "stlite" / "LICENSE").write_bytes(tar.extractfile(license_member).read())

    print("Pyodide (Python in the browser)")
    pyodide_out = vendor / "pyodide"
    pyodide_out.mkdir(parents=True)
    with npm_package(PYODIDE_CORE, cache) as tar:
        for name, sha in PYODIDE_CORE_FILES.items():
            data = tar.extractfile(f"package/{name}").read()
            check_sha256(data, sha, name)
            (pyodide_out / name).write_bytes(data)
        for extra in ("LICENSE", "README.md"):
            if f"package/{extra}" in tar.getnames():
                (pyodide_out / extra).write_bytes(tar.extractfile(f"package/{extra}").read())
    lock = json.loads((pyodide_out / "pyodide-lock.json").read_text())
    for name in PYODIDE_PACKAGES:
        entry = lock["packages"][name]
        file_name = entry["file_name"]
        local = pyodide_dir / file_name if pyodide_dir else None
        data = local.read_bytes() if local and local.exists() else fetch(PYODIDE_PACKAGES_URL + file_name)
        check_sha256(data, entry["sha256"], file_name)
        (pyodide_out / file_name).write_bytes(data)

    print("Python packages from PyPI")
    wheels = vendor / "wheels"
    wheels.mkdir(parents=True)
    for file_name, url, sha in PYPI_WHEELS:
        cached = cache / file_name
        data = cached.read_bytes() if cached.exists() else fetch(url)
        check_sha256(data, sha, file_name)
        cached.write_bytes(data)
        (wheels / file_name).write_bytes(data)

    print("The app")
    for name in APP_FILES:
        source = ROOT / name
        if not source.exists():
            sys.exit(f"Missing app file: {name}")
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(ROOT / "docs" / "UNIVERSITY_DEPLOYMENT.md", out / "DEPLOY.md")

    write_pages(out)
    write_server_configs(out)
    write_checksums(out)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Done: {out} ({size / 1e6:.0f} MB). Serve the folder from any web server; see DEPLOY.md.")


def write_pages(out: Path) -> None:
    files = APP_FILES
    regular = [f for f, _, _ in PYPI_WHEELS if f != NO_DEPS_WHEEL]
    (out / "boot.js").write_text(
        f"""// Starts the app. Everything is loaded from this server (see the Content Security Policy in index.html).
import {{ mount }} from "./vendor/stlite/stlite.js";

const here = (path) => new URL(path, document.baseURI).href;
const files = {json.dumps(files, indent=2)};

mount(
  {{
    entrypoint: "web_app.py",
    pyodideUrl: here("vendor/pyodide/pyodide.mjs"),
    requirements: ["pandas", ...{json.dumps(regular)}.map((wheel) => here("vendor/wheels/" + wheel))],
    installs: [{{ requirements: [here("vendor/wheels/{NO_DEPS_WHEEL}")], options: {{ deps: false }} }}],
    files: Object.fromEntries(files.map((name) => [name, {{ url: here(name) }}])),
    // Saved banks and projects (encrypted) live in this browser's storage.
    idbfsMountpoints: ["/home/pyodide/saved"],
    env: {{
      STATEMENT_TEMPLATES_PATH: "/home/pyodide/saved/statement_templates.json",
      STATEMENT_PROJECTS_PATH: "/home/pyodide/saved/projects",
      BSA_OFFLINE_BUILD: "1",
    }},
    streamlitConfig: {{
      "browser.gatherUsageStats": false,
      "client.toolbarMode": "minimal",
      "theme.base": "light",
      "theme.primaryColor": "#1D2844",
      "theme.backgroundColor": "#FFFFFF",
      "theme.secondaryBackgroundColor": "#F4F6FA",
      "theme.textColor": "#1F2937",
      "theme.font": "sans serif",
    }},
  }},
  document.getElementById("root"),
);
""",
        encoding="utf-8",
    )
    (out / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <!-- The browser may load from and connect to this server only: statements can't be sent anywhere else. -->
    <meta http-equiv="Content-Security-Policy" content="{CSP}" />
    <meta name="referrer" content="no-referrer" />
    <title>Bank Statement Analyzer</title>
    <link rel="stylesheet" href="vendor/stlite/stlite.css" />
    <style>
      body {{ margin: 0; background: #F4F5F7; }}
      #loading {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 36rem; margin: 5rem auto; padding: 0 1rem; color: #374151; }}
      #loading .org {{ font-size: 0.75rem; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: #246094; margin: 0; }}
      #loading h1 {{ color: #1D2844; font-size: 1.7rem; margin: 0.2rem 0 0.6rem; }}
      #loading .bar {{ height: 4px; background: #e3e7ee; border-radius: 2px; overflow: hidden; margin: 1.2rem 0; }}
      #loading .bar::after {{ content: ""; display: block; height: 100%; width: 35%; background: #246094; animation: slide 1.4s ease-in-out infinite; }}
      @keyframes slide {{ from {{ transform: translateX(-100%); }} to {{ transform: translateX(300%); }} }}
    </style>
  </head>
  <body>
    <div id="root">
      <div id="loading">
        <img src="assets/logo.png" alt="Justice for Fraud Victims Project" style="height:64px">
        <p class="org">Justice for Fraud Victims Project</p>
        <h1>Bank Statement Analyzer</h1>
        <div class="bar"></div>
        <p>Loading… the first visit loads the app from this server and can take a minute. Everything then runs
        inside this browser tab: statements you open never leave your computer.</p>
      </div>
    </div>
    <script type="module" src="boot.js"></script>
  </body>
</html>
""",
        encoding="utf-8",
    )


def write_server_configs(out: Path) -> None:
    """The same policy as HTTP headers (stronger than the page's own tag): Apache, IIS and nginx."""
    apache = "\n".join(f'    Header always set {k} "{v}"' for k, v in HEADERS.items())
    (out / ".htaccess").write_text(
        "# Apache: security headers for Bank Statement Analyzer (needs mod_headers).\n"
        "<IfModule mod_headers.c>\n" + apache + "\n</IfModule>\n"
        "AddType application/wasm .wasm\nAddType text/javascript .mjs\n",
        encoding="utf-8",
    )
    iis = "\n".join(f'        <add name="{k}" value="{v}" />' for k, v in HEADERS.items())
    (out / "web.config").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- IIS: security headers for Bank Statement Analyzer. -->\n'
        "<configuration>\n  <system.webServer>\n    <httpProtocol>\n      <customHeaders>\n" + iis + "\n"
        "      </customHeaders>\n    </httpProtocol>\n    <staticContent>\n"
        '      <remove fileExtension=".wasm" /><mimeMap fileExtension=".wasm" mimeType="application/wasm" />\n'
        '      <remove fileExtension=".mjs" /><mimeMap fileExtension=".mjs" mimeType="text/javascript" />\n'
        '      <remove fileExtension=".whl" /><mimeMap fileExtension=".whl" mimeType="application/zip" />\n'
        '      <remove fileExtension=".woff2" /><mimeMap fileExtension=".woff2" mimeType="font/woff2" />\n'
        '      <remove fileExtension=".py" /><mimeMap fileExtension=".py" mimeType="text/plain" />\n'
        '      <remove fileExtension=".md" /><mimeMap fileExtension=".md" mimeType="text/plain" />\n'
        "    </staticContent>\n  </system.webServer>\n</configuration>\n",
        encoding="utf-8",
    )
    nginx = "\n".join(f'    add_header {k} "{v}" always;' for k, v in HEADERS.items())
    (out / "nginx.conf.example").write_text(
        "# nginx: put inside the server { } block that serves this folder.\n"
        "location / {\n" + nginx + "\n    types { application/wasm wasm; text/javascript mjs js; }\n}\n",
        encoding="utf-8",
    )


def write_checksums(out: Path) -> None:
    lines = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out).as_posix()}")
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "offline")
    parser.add_argument("--pyodide-dir", type=Path, help="An already-downloaded Pyodide 0.29.3 'full' distribution")
    parser.add_argument("--cache", type=Path, default=ROOT / "dist" / ".download-cache")
    args = parser.parse_args()
    build(args.out, args.pyodide_dir, args.cache)


if __name__ == "__main__":
    main()
