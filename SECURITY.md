# Security

Bank Statement Analyzer is used on real fraud cases, so statements must stay private. This page
summarizes how the app protects them and how to report a problem. The full guide, including what
the people handling cases must do, is [docs/SECURITY_AND_DATA_HANDLING.md](docs/SECURITY_AND_DATA_HANDLING.md).
Hosting instructions for universities and organizations are in
[docs/UNIVERSITY_DEPLOYMENT.md](docs/UNIVERSITY_DEPLOYMENT.md).

## How statements are protected

- **They stay on the user's computer.** The version that runs on a computer (`start.bat` /
  `start.sh`) only accepts connections from that computer and sends no usage statistics. The
  browser version analyzes statements inside the browser tab; they are never uploaded.
- **No outside connections in the offline build.** The self-contained browser build
  (`tools/build_offline.py`, or the `deploy/browser` image) loads everything from its own
  server, and its Content Security Policy forbids the page from loading from or connecting to
  any other address. Fonts are embedded, so even the regular versions call no font service.
- **Projects are encrypted at rest.** Everything in a project (statements, their file names,
  notes, and the case log) is encrypted with AES-256-GCM, using a key derived from the
  project's password with scrypt (N=2^15, r=8, p=3). Only the project's name is stored
  unencrypted, so it can be listed. Downloaded projects (`.bsacase` files) are encrypted the same
  way with their own password. A lost password cannot be recovered.
- **Evidence integrity.** Every analysis records each statement's SHA-256 fingerprint, and every
  transaction row names its file, page and line, along with the app version, the analyst and the
  time. The app never changes the original files.
- **Supply chain.** Python packages are pinned to exact versions and fingerprints
  (`requirements-lock.txt`, installed with `--require-hashes`). The offline build checks every
  downloaded file against a pinned fingerprint. Docker base images and GitHub Actions are pinned
  to exact digests. Dependabot proposes updates weekly.
- **Hosted copies are labelled.** When the app runs on a server that hasn't been approved for case
  data (for example Streamlit Community Cloud), it shows a warning not to upload real statements.

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use **Report a vulnerability**
on the repository's **Security** tab (the repository owner turns this on under Settings → Code
security → Private vulnerability reporting). Include what you found, how to reproduce it, and its
impact. You'll get a reply as soon as possible, and fixes are released as a new version.

## Supported versions

Security fixes go into the latest release. Universities and organizations hosting the app should
update when a new release is published (see the deployment guide).
