# Hosting Bank Statement Analyzer at your university or organization

There are two ways to host the app on your own domain (for example `fraudlab.youruniversity.edu`).
Both are free, open source and run on your own infrastructure. Read
[SECURITY_AND_DATA_HANDLING.md](SECURITY_AND_DATA_HANDLING.md) first; it explains what each
option protects.

| | **Option 1: Browser version** (recommended) | **Option 2: Server version** |
| --- | --- | --- |
| Where statements are analyzed | In each person's browser. Never uploaded. | On your server. Uploaded to it. |
| Case data on the server | None | Yes (projects encrypted with their passwords) |
| What the server does | Delivers static files | Runs the app |
| Sign-in | Optional (it holds no data) | Required (your single sign-on) |
| Scanned statements (OCR) | Not yet | Yes |
| Projects saved | In each browser (encrypted), or downloaded | On the server, per person (encrypted) |
| Approval effort | Low: a static website with no data | Higher: a system holding case data |
| Server size | Tiny (any web server, 85 MB of files) | 2 CPUs, 4 GB RAM, disk for case data |

Most schools should start with Option 1. Add Option 2 only if people need OCR without installing
anything, or projects that follow them between computers, and your organization approves the
server for case data.

---

## Option 1: Browser version

The server only hands out the app's files. Each person's browser runs the app and reads statements
locally. The page's security policy stops the browser from contacting any address except your
server, so statements can't be sent anywhere, even by a bug or a tampered library.

### 1a. With Docker

```bash
docker run -d --name bank-statement-analyzer -p 8080:8080 --read-only --tmpfs /tmp \
  --restart unless-stopped ghcr.io/jdaiken/bank-statement-analyzer-browser:<version>
```

Images are published with each release. To build it yourself instead:

```bash
git clone https://github.com/jdaiken/parsing_tool.git && cd parsing_tool
docker build -f deploy/browser/Dockerfile -t bank-statement-analyzer-browser .
```

On a network that inspects HTTPS, give the build your organization's CA certificate (used during
the build only, never stored in the image): `docker build --secret id=ca_bundle,src=ca.pem ...`

The container runs nginx as an unprivileged user on a read-only filesystem, serves only GET
requests and sends the security headers. Put it behind your HTTPS load balancer or reverse proxy.

### 1b. On an existing web server (no Docker)

1. Download `bank-statement-analyzer-offline-<version>.zip` from the repository's
   [Releases](https://github.com/jdaiken/parsing_tool/releases) page, or build it:
   `python tools/build_offline.py` (Python 3.11+) writes `dist/offline/`.
2. Check the zip against its published `.sha256` file, and the unzipped folder against the
   `SHA256SUMS.txt` inside it.
3. Copy the folder to a site served over HTTPS.
4. Turn on the security headers. The folder includes ready-made settings: `.htaccess` (Apache, needs
   `mod_headers`), `web.config` (IIS), and `nginx.conf.example` (nginx). They also set the right file
   types (`.wasm` must be served as `application/wasm`). The page carries the same policy in a
   `<meta>` tag, so it's protected even where headers can't be set, but headers are stronger and add
   `frame-ancestors 'none'`.

### What people see

The first visit loads about 85 MB from your server (cached afterwards), then the app runs in the
tab. Projects are saved encrypted in that browser; people should download projects they need to
keep, because clearing browser data erases them. For scanned statements, people use the computer
version (`start.bat` / `start.sh`), which includes OCR.

---

## Option 2: Server version

The full app (including OCR) runs on your server behind your single sign-on. Each signed-in person
sees only their own projects, which are also encrypted with their passwords. Use this only on a
server your organization has approved for case data.

### What's included

`deploy/server/docker-compose.yml` runs two containers:

- **signin**: [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/), which sends people to
  your identity provider (Microsoft Entra ID, Google Workspace, Okta, or any OpenID Connect
  provider; Shibboleth and other SAML-only systems through their OpenID Connect support) and passes the
  signed-in email to the app.
- **app**: the app, on an internal network with no published port and no internet route, so it
  can only be reached through sign-in. It runs as an unprivileged user on a read-only filesystem,
  with all Linux capabilities dropped. Case data lives in the `case-data` volume.

### Setup

1. **Register the app with your identity provider** as an OpenID Connect web application, with
   redirect URL `https://<your-host>/oauth2/callback`. Note the issuer URL, client ID and client
   secret. Limit which people or groups can sign in, at the provider.
2. **Configure:** `cp deploy/server/.env.example deploy/server/.env` and fill it in. Generate the
   cookie secret as shown in the file. Keep `.env` out of version control.
3. **Start:**
   ```bash
   docker compose -f deploy/server/docker-compose.yml --env-file deploy/server/.env up -d --build
   ```
4. **Put it behind HTTPS.** Point your reverse proxy or load balancer at `127.0.0.1:4180` (the
   sign-in container). Your reverse proxy must forward WebSocket connections (the app uses them).
5. **Pin the sign-in image** to a digest (`docker pull`, then `image: quay.io/oauth2-proxy/oauth2-proxy@sha256:...`).
6. **Store `case-data` on an encrypted disk**, include it in backups, and restrict who can log in
   to the server: administrators of this server are inside the trust boundary.

### How the app knows it's approved

Two settings in `docker-compose.yml` turn on server mode; set them only on an approved server:

- `BSA_APPROVED_SERVER=1`: removes the "demonstration copy" warning.
- `BSA_USER_HEADER=X-Forwarded-Email`: the header oauth2-proxy sets to the signed-in person. The
  app keeps one projects folder per person and refuses to run if the header is missing. Never
  expose the app container directly: the header is trusted only because sign-in is the only way in.

### Checks after setup

- Without signing in, the site redirects to your identity provider.
- Two different people don't see each other's projects.
- `docker compose logs app` shows no errors; the app logs don't contain statement contents.

---

## Updating

New versions are tagged releases. Each one attaches the offline package (with its SHA-256) and
publishes both images (`bank-statement-analyzer-browser` and `bank-statement-analyzer-server` on
`ghcr.io/jdaiken`). To update: pull the new image tag (or replace the folder) and restart. Projects
and case data carry over.

## Questions IT usually asks

- **Does it store or send data anywhere?** Option 1: no. The server holds no case data and the
  browser is blocked from contacting other addresses. Option 2: only to your server.
- **Third parties?** None at run time. The offline build and images contain everything.
- **Accounts?** Option 1 needs none. Option 2 uses your single sign-on.
- **Logs?** nginx access logs (Option 1) and the app's console log (Option 2) record requests, not
  statement contents.
- **Accessibility?** The app is a standard web page. A formal accessibility review hasn't been done
  yet; ask if your institution needs a VPAT.
- **Security review?** The code is open source for review. See [SECURITY.md](../SECURITY.md) to
  report a problem privately.
