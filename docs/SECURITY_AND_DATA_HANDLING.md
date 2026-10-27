# Security and data handling guide

For the Justice for Fraud Victims Project, partner universities, and anyone using Bank Statement
Analyzer on real cases. It covers what the app does to protect statements, what it can't do, and
the practices the people handling cases need to follow. Software alone doesn't make case data
safe: the protections below only hold when the handling rules are followed too.

This guide is not legal advice. Have your organization's counsel review your data-handling
policy, especially when findings may go to law enforcement or court.

## 1. Choosing a version

| Version | Where statements go | Use it for |
| --- | --- | --- |
| **On your computer** (`start.bat` / `start.sh`, or VS Code) | Nowhere: read on that computer. Includes OCR for scanned statements. | Real cases, by an investigator on an approved computer. |
| **Offline browser build**, hosted by your organization (`deploy/browser`) | Nowhere: read inside the browser tab. The page is blocked from contacting any other address. | Real cases and classes, with nothing to install. No OCR for scans yet. |
| **Server version**, hosted by your organization behind its sign-in (`deploy/server`) | Uploaded to your organization's server. | Only if your organization has approved that server for case data. |
| **Public demo** (Streamlit Community Cloud, GitHub Pages) | Streamlit Cloud: uploaded to Streamlit's servers. | The fictional demo case only. Never real statements. |

The app labels each one: "Private: runs on your computer", "Private: runs inside your browser",
"Runs on your organization's approved server", or a red **Demonstration copy** warning.

## 2. What the app does

**Keeps statements local.** The computer version accepts connections only from the same computer
(`.streamlit/config.toml`) and sends no usage statistics. The browser versions read statements in
the browser tab. Fonts are embedded, and the HTML dashboard export embeds its chart code, so
opening the app or a report calls no outside service.

**Blocks outside connections (offline build).** The page's Content Security Policy, also sent as
HTTP headers by the included nginx, Apache (`.htaccess`) and IIS (`web.config`) settings, only
lets the browser load from and connect to the server the app came from. That covers the Python
code that reads statements too, which runs in a worker that inherits the policy. In testing, the
complete app (samples, dashboard, exports, encrypted projects, notes) ran with every outside
request blocked, and a deliberate attempt to contact another site was refused by the browser.

**Encrypts projects.** A project's statements, their original file names, case notes, notes on
statements and transactions, and its case log are encrypted with AES-256-GCM. The key is derived
from the project password with scrypt (N=2^15, r=8, p=3, an OWASP-recommended setting). Each
encrypted file is bound to its purpose, so encrypted pieces can't be swapped, and any change to an
encrypted file is detected. Downloaded projects (`.bsacase` files) are encrypted the same way with
the password typed at download.

- Only the **project name** is stored unencrypted, so projects can be listed. Use a case number,
  never a person's name.
- A **lost password can't be recovered**, by anyone. Keep it in your organization's password
  manager.
- While a project is unlocked, its key is held in that browser session's memory. **Lock project**
  (sidebar), **Clear this session** or closing the tab forgets it.

**Records evidence.** Each statement's SHA-256 fingerprint is recorded when it's analyzed and when
it's added to a project. Every transaction row in the workpaper names its source file, fingerprint,
page and line. The workpaper also records the app version, the analyst, the project, the settings
and the time with its time zone. The project's case log lists when statements were added or
removed, notes were saved and the project was downloaded. The app never modifies the original files.

**Warns about leaky redactions.** If black boxes in a PDF still have readable text under them, the
app hides that text and warns that the file isn't safely redacted.

**Pins its supply chain.** Python packages install only at the exact versions and fingerprints in
`requirements-lock.txt`. The offline build checks every downloaded file against a pinned fingerprint
and lists every file's fingerprint in `SHA256SUMS.txt`. Docker base images and GitHub Actions are
pinned to exact digests, and Dependabot proposes security updates weekly.

## 3. What the app can't do

- **Workpapers and exports aren't encrypted.** Excel workpapers, CSV and HTML exports contain the
  transactions in full. Store them only in approved, encrypted storage. Excel's own password
  protection is weak; don't rely on it.
- **It can't protect a compromised computer.** Malware, a shared login, or a browser extension that
  can read web pages can see whatever is on screen. Use a dedicated browser profile with no
  extensions for case work, and never use a public or shared computer.
- **Browser storage belongs to the browser profile.** Projects saved in the browser version are
  encrypted, but anyone using the same browser profile can delete them, and clearing browser data
  erases them. Download projects you need to keep.
- **On a server, statements are on the server.** In the server version, statements are uploaded,
  held in the server's memory while they're analyzed, and stored (encrypted) on its disk. Server
  administrators are part of the trust boundary.
- **Its findings are leads, not conclusions.** Fraud patterns and document checks point to where to
  look. An investigator must verify every finding against the source documents before it goes into
  a report. A clean document check doesn't prove a statement is genuine: get statements directly
  from the bank, or by subpoena, when authenticity matters.

## 4. Rules for people handling cases

**Devices**
- Full-disk encryption on (BitLocker on Windows, FileVault on Mac), automatic screen lock, current
  operating system and browser updates, an individual (not shared) login.
- Run case work in the computer version or your organization's hosted copy, never the public demo.

**Files**
- Keep statements and workpapers only in storage your organization approves. No personal cloud
  accounts, USB drives or email.
- Share a project as a `.bsacase` file, and send its password separately: a different channel, never
  in the same email.
- Use case numbers for project and file names, not victims' names.

**Access**
- Only the case team. Students working on real cases do so under supervision, after signing a
  confidentiality agreement.
- Get written authorization from the victim (or appropriate legal authority) before reviewing their
  records, and keep it with the case file.

**Closing a case**
- Download the project if your retention policy requires keeping it, store it as above, then use
  **Close case and erase** on the Project tab.
- Delete exported workpapers from working folders according to your retention schedule.

**If something goes wrong** (a lost laptop, a file sent to the wrong person, a password exposed)
- Tell your supervisor and your organization's IT security office immediately.
- Note what data was involved: names, account numbers, which statements.
- State breach-notification laws may apply when names together with account numbers are exposed;
  your counsel decides.
- If a project password may be exposed, download the project and open it again with a new password,
  then erase the old copy.

## 5. Verifying a hosted copy (for IT)

1. **Check the files.** Compare the deployed folder against `SHA256SUMS.txt`, or the release zip
   against its published `.sha256` file.
2. **Check the headers.** `curl -sI https://your-host/index.html` should show the
   `Content-Security-Policy` header with `connect-src 'self' blob: data:`, plus `X-Content-Type-Options`,
   `Referrer-Policy` and `Permissions-Policy`.
3. **Check that nothing leaves.** Open the app with the browser's developer tools open (Network tab),
   load the sample statements and download a workpaper. Every request should go to your host (or be
   `blob:`/`data:`). Typing `fetch("https://example.com")` in the console should be refused with a
   Content Security Policy error.
4. **Check for uploads.** The browser version's server accepts only GET: `curl -X POST` returns 403.

## 6. Keeping it up to date

- Watch the repository's releases. Each release attaches the offline package (with its fingerprint)
  and publishes both Docker images.
- Review and merge Dependabot's weekly pull requests: the automated tests run on each one.
- Report security problems privately (see [SECURITY.md](../SECURITY.md)).
