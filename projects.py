"""
Project folders: a case's statements and notes kept together, encrypted.

Each project is a folder. Everything in it is encrypted with a key made from the project's
password (scrypt, then AES-256-GCM): the statements, their file names, the case notes, the
notes on statements and transactions, and the case log. Only index.json is readable: the
project's name (so it can be listed; use a case number, not a person's name), its dates, and
what is needed to check the password. Without the password the folder is unreadable, and a
lost password can't be recovered.

On the version that runs on your computer the folders live in projects/ next to the app
(never committed to git); the browser version keeps them in browser storage. A project can
be downloaded as one encrypted .bsacase file and opened again later or on another computer.

Projects made before encryption was added (a plain project.json) still open; the Project tab
offers to protect them with a password.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

PROJECTS_DIR = Path(os.environ.get("STATEMENT_PROJECTS_PATH") or Path(__file__).with_name("projects"))
MAX_ZIP_BYTES = 200 * 1024 * 1024
MIN_PASSWORD = 10
KDF = {"name": "scrypt", "n": 2**15, "r": 8, "p": 1}
BLOB_MAGIC = b"BSA1"  # one encrypted file in a project folder
CASE_MAGIC = b"BSACASE1"  # a downloaded .bsacase file
CHECK_TEXT = b"bank-statement-analyzer project key"


# --- Encryption ------------------------------------------------------------------------


def check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Use a password of at least {MIN_PASSWORD} characters (a short phrase is easiest to remember).")


def derive_key(password: str, salt: bytes, kdf: Optional[Dict] = None) -> bytes:
    kdf = kdf or KDF
    if kdf.get("name") != "scrypt":
        raise ValueError("Unsupported key format.")
    return Scrypt(salt=salt, length=32, n=int(kdf["n"]), r=int(kdf["r"]), p=int(kdf["p"])).derive(password.encode("utf-8"))


def encrypt(key: bytes, data: bytes, label: str) -> bytes:
    """AES-256-GCM. `label` is bound to the data, so one encrypted file can't be swapped for another."""
    nonce = secrets.token_bytes(12)
    return BLOB_MAGIC + nonce + AESGCM(key).encrypt(nonce, data, label.encode("utf-8"))


def decrypt(key: bytes, blob: bytes, label: str) -> bytes:
    if not blob.startswith(BLOB_MAGIC):
        raise ValueError("Not an encrypted project file.")
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], label.encode("utf-8"))
    except InvalidTag:
        raise ValueError("Wrong password, or the file was damaged or changed.")


# --- Folders ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "project"


def _safe_file_name(name: str) -> str:
    name = Path(str(name)).name  # never a path
    name = re.sub(r"[^\w.\- ()]+", "_", name).strip(" .")
    return name or "statement.pdf"


def _folder(slug: str, base: Optional[Path] = None) -> Path:
    base = base or PROJECTS_DIR
    folder = (base / slug).resolve()
    if folder.parent != base.resolve():
        raise ValueError("Invalid project")
    return folder


def _index(slug: str, base: Optional[Path]) -> Dict:
    return json.loads((_folder(slug, base) / "index.json").read_text(encoding="utf-8"))


def is_encrypted(slug: str, base: Optional[Path] = None) -> bool:
    return (_folder(slug, base) / "index.json").exists()


def list_projects(base: Optional[Path] = None) -> List[Dict]:
    """Projects (name, dates, encrypted or not), most recently updated first. Needs no password."""
    base = base or PROJECTS_DIR
    if not base.exists():
        return []
    projects = []
    for folder in base.iterdir():
        for name, encrypted in (("index.json", True), ("project.json", False)):
            path = folder / name
            if path.exists():
                try:
                    meta = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    break
                projects.append({"slug": folder.name, "name": meta.get("name", folder.name), "created": meta.get("created", ""),
                                 "updated": meta.get("updated", ""), "encrypted": encrypted})
                break
    return sorted(projects, key=lambda m: m.get("updated", ""), reverse=True)


def _new_index(name: str, password: str) -> Tuple[Dict, bytes]:
    salt = secrets.token_bytes(16)
    key = derive_key(password, salt)
    index = {
        "name": name, "created": _now(), "updated": _now(), "format": 1,
        "kdf": dict(KDF, salt=base64.b64encode(salt).decode("ascii")),
        "check": base64.b64encode(encrypt(key, CHECK_TEXT, "check")).decode("ascii"),
    }
    return index, key


def _empty_meta(name: str, description: str) -> Dict:
    return {"name": name, "description": description.strip(), "created": _now(), "updated": _now(),
            "notes": "", "files": [], "file_notes": {}, "txn_notes": {}, "log": []}


def log_event(meta: Dict, event: str, detail: str = "") -> None:
    """Add a line to the project's case log (who did what is up to the people using it; the log records what and when)."""
    meta.setdefault("log", []).append({"time": _now(), "event": event, "detail": detail})


def create_project(name: str, description: str = "", password: str = "", base: Optional[Path] = None) -> Tuple[str, bytes]:
    """A new encrypted project. Returns (slug, key); the key unlocks it for this session."""
    base = base or PROJECTS_DIR
    name = name.strip()
    if len(name) < 2:
        raise ValueError("Give the project a name.")
    check_password(password)
    slug = _slug(name)
    candidate, n = slug, 2
    while (base / candidate).exists():
        candidate, n = f"{slug}-{n}", n + 1
    folder = base / candidate
    (folder / "statements").mkdir(parents=True)
    index, key = _new_index(name, password)
    (folder / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    meta = _empty_meta(name, description)
    log_event(meta, "Project created")
    meta["slug"] = candidate
    save_project(meta, base, key)
    return candidate, key


def unlock(slug: str, password: str, base: Optional[Path] = None) -> bytes:
    """The project's key, if the password is right."""
    index = _index(slug, base)
    kdf = index["kdf"]
    key = derive_key(password, base64.b64decode(kdf["salt"]), kdf)
    try:
        if decrypt(key, base64.b64decode(index["check"]), "check") != CHECK_TEXT:
            raise ValueError
    except ValueError:
        raise ValueError("That password doesn't open this project.")
    return key


def load_project(slug: str, base: Optional[Path] = None, key: Optional[bytes] = None) -> Dict:
    folder = _folder(slug, base)
    if is_encrypted(slug, base):
        if key is None:
            raise PermissionError("This project is locked.")
        meta = json.loads(decrypt(key, (folder / "project.enc").read_bytes(), "project"))
    else:
        meta = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    for name, default in (("notes", ""), ("files", []), ("file_notes", {}), ("txn_notes", {}), ("description", ""), ("log", [])):
        meta.setdefault(name, default)
    meta["slug"] = slug
    meta["encrypted"] = is_encrypted(slug, base)
    return meta


def save_project(meta: Dict, base: Optional[Path] = None, key: Optional[bytes] = None) -> None:
    meta = dict(meta)
    slug = meta.pop("slug")
    meta.pop("encrypted", None)
    meta["updated"] = _now()
    folder = _folder(slug, base)
    if is_encrypted(slug, base):
        if key is None:
            raise PermissionError("This project is locked.")
        (folder / "project.enc").write_bytes(encrypt(key, json.dumps(meta).encode("utf-8"), "project"))
        index = _index(slug, base)
        index.update(name=meta["name"], updated=meta["updated"])
        (folder / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    else:
        (folder / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _stored_name(entry: Dict) -> str:
    return entry.get("stored") or _safe_file_name(entry["name"])


def add_files(slug: str, files: List[Tuple[str, bytes]], base: Optional[Path] = None, key: Optional[bytes] = None) -> List[str]:
    """Copy statements into the project; files already in it (same content) are skipped. Returns names added."""
    meta = load_project(slug, base, key)
    folder = _folder(slug, base) / "statements"
    folder.mkdir(exist_ok=True)
    encrypted = meta["encrypted"]
    known = {f["sha256"] for f in meta["files"]}
    taken = {f["name"] for f in meta["files"]}
    added = []
    for name, data in files:
        digest = hashlib.sha256(data).hexdigest()
        if digest in known:
            continue
        safe = _safe_file_name(name)
        stem, suffix = Path(safe).stem, Path(safe).suffix or ".pdf"
        n = 2
        while safe in taken:
            safe, n = f"{stem} ({n}){suffix}", n + 1
        if encrypted:
            stored = f"{secrets.token_hex(8)}.enc"  # the real file name is only inside the encrypted metadata
            (folder / stored).write_bytes(encrypt(key, data, f"statement:{stored}"))
        else:
            stored = safe
            (folder / stored).write_bytes(data)
        meta["files"].append({"name": safe, "stored": stored, "added": _now(), "sha256": digest, "bytes": len(data)})
        log_event(meta, "Statement added", f"{safe} (SHA-256 {digest})")
        known.add(digest)
        taken.add(safe)
        added.append(safe)
    if added:
        save_project(meta, base, key)
    return added


def read_files(slug: str, base: Optional[Path] = None, key: Optional[bytes] = None) -> List[Tuple[str, bytes]]:
    meta = load_project(slug, base, key)
    folder = _folder(slug, base) / "statements"
    out = []
    for entry in meta["files"]:
        path = folder / _stored_name(entry)
        if not path.exists():
            continue
        data = path.read_bytes()
        if meta["encrypted"]:
            data = decrypt(key, data, f"statement:{entry['stored']}")
        out.append((entry["name"], data))
    return out


def remove_file(slug: str, name: str, base: Optional[Path] = None, key: Optional[bytes] = None) -> None:
    meta = load_project(slug, base, key)
    entry = next((f for f in meta["files"] if f["name"] == name), None)
    if entry is None:
        return
    meta["files"] = [f for f in meta["files"] if f["name"] != name]
    meta["file_notes"].pop(name, None)
    stem = Path(name).stem
    meta["txn_notes"] = {k: v for k, v in meta["txn_notes"].items() if not k.startswith(f"{stem}|") and not k.startswith(f"{stem} · ")}
    path = _folder(slug, base) / "statements" / _stored_name(entry)
    if path.exists():
        path.unlink()
    log_event(meta, "Statement removed", f"{name} (SHA-256 {entry.get('sha256', '')})")
    save_project(meta, base, key)


def delete_project(slug: str, base: Optional[Path] = None) -> None:
    shutil.rmtree(_folder(slug, base))


def protect(slug: str, password: str, base: Optional[Path] = None) -> bytes:
    """Encrypt a project made before encryption was added. Returns its key."""
    if is_encrypted(slug, base):
        raise ValueError("This project is already protected.")
    check_password(password)
    meta = load_project(slug, base)
    folder = _folder(slug, base)
    index, key = _new_index(meta["name"], password)
    index["created"] = meta.get("created", index["created"])
    plain_files = [(entry, (folder / "statements" / _stored_name(entry)).read_bytes()) for entry in meta["files"]
                   if (folder / "statements" / _stored_name(entry)).exists()]
    (folder / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    meta["files"] = []
    for entry, data in plain_files:
        stored = f"{secrets.token_hex(8)}.enc"
        (folder / "statements" / stored).write_bytes(encrypt(key, data, f"statement:{stored}"))
        (folder / "statements" / _stored_name(entry)).unlink()
        meta["files"].append(dict(entry, stored=stored, bytes=len(data)))
    log_event(meta, "Project protected with a password")
    save_project(meta, base, key)
    (folder / "project.json").unlink()
    return key


# --- Download and open -----------------------------------------------------------------


def _zip_project(meta: Dict, files: List[Tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    clean = {k: v for k, v in meta.items() if k not in ("slug", "encrypted")}
    clean["files"] = [{k: v for k, v in f.items() if k != "stored"} for f in clean["files"]]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(clean, indent=2))
        for name, data in files:
            zf.writestr(f"statements/{name}", data)
    return buffer.getvalue()


def export_case(slug: str, password: str, base: Optional[Path] = None, key: Optional[bytes] = None) -> bytes:
    """The whole project as one encrypted .bsacase file, readable only with `password`."""
    check_password(password)
    meta = load_project(slug, base, key)
    log_event(meta, "Project downloaded (encrypted)")
    save_project(meta, base, key)
    plain = _zip_project(meta, read_files(slug, base, key))
    salt = secrets.token_bytes(16)
    header = json.dumps(dict(KDF, salt=base64.b64encode(salt).decode("ascii"))).encode("utf-8")
    body = encrypt(derive_key(password, salt), plain, "case")
    return CASE_MAGIC + len(header).to_bytes(4, "big") + header + body


def _open_case(data: bytes, password: str) -> bytes:
    """The zip inside a .bsacase file, or a plain .zip from before encryption."""
    if data.startswith(CASE_MAGIC):
        size = int.from_bytes(data[8:12], "big")
        kdf = json.loads(data[12:12 + size].decode("utf-8"))
        return decrypt(derive_key(password, base64.b64decode(kdf["salt"]), kdf), data[12 + size:], "case")
    if data.startswith(b"PK"):
        return data
    raise ValueError("That isn't a project file saved from this app.")


def import_case(data: bytes, password: str, base: Optional[Path] = None) -> Tuple[str, bytes]:
    """
    Open a downloaded project as a new encrypted project protected by `password` (the file's
    password for a .bsacase file; a new password for an old unencrypted .zip). Returns (slug, key).
    """
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("That project file is too large.")
    check_password(password)
    plain = _open_case(data, password)
    try:
        zf = zipfile.ZipFile(io.BytesIO(plain))
        meta = json.loads(zf.read("project.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise ValueError("That isn't a project file saved from this app.")
    if sum(info.file_size for info in zf.infolist()) > MAX_ZIP_BYTES:
        raise ValueError("That project file is too large.")
    name = str(meta.get("name") or "").strip()
    slug, key = create_project(name if len(name) >= 2 else "Imported project", str(meta.get("description") or ""), password, base)
    files = []
    for entry in meta.get("files", []):
        try:
            files.append((_safe_file_name(entry.get("name", "")), zf.read(f"statements/{entry.get('name', '')}")))
        except KeyError:
            continue
    add_files(slug, files, base, key)
    imported = load_project(slug, base, key)
    imported["notes"] = str(meta.get("notes") or "")
    imported["file_notes"] = {str(k): str(v) for k, v in dict(meta.get("file_notes") or {}).items()}
    imported["txn_notes"] = {str(k): str(v) for k, v in dict(meta.get("txn_notes") or {}).items()}
    imported["created"] = str(meta.get("created") or imported["created"])
    earlier = [e for e in meta.get("log", []) if isinstance(e, dict)]
    imported["log"] = earlier + imported["log"]
    log_event(imported, "Project opened from a downloaded file")
    save_project(imported, base, key)
    return slug, key
