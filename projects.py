"""
Project folders: a case's statements and notes kept together.

Each project is a folder holding project.json (name, description, case notes, a note per
statement and per transaction) and a statements/ folder with the PDFs. On the version that
runs on your computer the folders live in projects/ next to the app (never committed to
git); the browser version keeps them in browser storage. A project can also be downloaded
as one .zip file and opened again later or on another computer.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECTS_DIR = Path(os.environ.get("STATEMENT_PROJECTS_PATH") or Path(__file__).with_name("projects"))
MAX_ZIP_BYTES = 200 * 1024 * 1024


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


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


def list_projects(base: Optional[Path] = None) -> List[Dict]:
    """Projects, most recently updated first."""
    base = base or PROJECTS_DIR
    if not base.exists():
        return []
    projects = []
    for meta_path in base.glob("*/project.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta["slug"] = meta_path.parent.name
        projects.append(meta)
    return sorted(projects, key=lambda m: m.get("updated", ""), reverse=True)


def create_project(name: str, description: str = "", base: Optional[Path] = None) -> str:
    base = base or PROJECTS_DIR
    name = name.strip()
    if len(name) < 2:
        raise ValueError("Give the project a name.")
    slug = _slug(name)
    candidate, n = slug, 2
    while (base / candidate).exists():
        candidate, n = f"{slug}-{n}", n + 1
    folder = base / candidate
    (folder / "statements").mkdir(parents=True)
    meta = {"name": name, "description": description.strip(), "created": _now(), "updated": _now(),
            "notes": "", "files": [], "file_notes": {}, "txn_notes": {}}
    (folder / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return candidate


def load_project(slug: str, base: Optional[Path] = None) -> Dict:
    meta = json.loads((_folder(slug, base) / "project.json").read_text(encoding="utf-8"))
    for key, default in (("notes", ""), ("files", []), ("file_notes", {}), ("txn_notes", {}), ("description", "")):
        meta.setdefault(key, default)
    meta["slug"] = slug
    return meta


def save_project(meta: Dict, base: Optional[Path] = None) -> None:
    meta = dict(meta)
    slug = meta.pop("slug")
    meta["updated"] = _now()
    (_folder(slug, base) / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def add_files(slug: str, files: List[Tuple[str, bytes]], base: Optional[Path] = None) -> List[str]:
    """Copy statements into the project; files already in it (same content) are skipped. Returns names added."""
    meta = load_project(slug, base)
    folder = _folder(slug, base) / "statements"
    folder.mkdir(exist_ok=True)
    known = {f["sha256"] for f in meta["files"]}
    added = []
    for name, data in files:
        digest = hashlib.sha256(data).hexdigest()
        if digest in known:
            continue
        safe = _safe_file_name(name)
        stem, suffix = Path(safe).stem, Path(safe).suffix or ".pdf"
        n = 2
        while (folder / safe).exists():
            safe, n = f"{stem} ({n}){suffix}", n + 1
        (folder / safe).write_bytes(data)
        meta["files"].append({"name": safe, "added": _now(), "sha256": digest})
        known.add(digest)
        added.append(safe)
    if added:
        save_project(meta, base)
    return added


def read_files(slug: str, base: Optional[Path] = None) -> List[Tuple[str, bytes]]:
    meta = load_project(slug, base)
    folder = _folder(slug, base) / "statements"
    return [(f["name"], (folder / f["name"]).read_bytes()) for f in meta["files"] if (folder / f["name"]).exists()]


def remove_file(slug: str, name: str, base: Optional[Path] = None) -> None:
    meta = load_project(slug, base)
    meta["files"] = [f for f in meta["files"] if f["name"] != name]
    meta["file_notes"].pop(name, None)
    stem = Path(name).stem
    meta["txn_notes"] = {k: v for k, v in meta["txn_notes"].items() if not k.startswith(f"{stem}|") and not k.startswith(f"{stem} · ")}
    path = _folder(slug, base) / "statements" / _safe_file_name(name)
    if path.exists():
        path.unlink()
    save_project(meta, base)


def delete_project(slug: str, base: Optional[Path] = None) -> None:
    shutil.rmtree(_folder(slug, base))


def export_zip(slug: str, base: Optional[Path] = None) -> bytes:
    """The whole project as one .zip: project.json plus statements/."""
    folder = _folder(slug, base)
    meta = load_project(slug, base)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(folder / "project.json", "project.json")
        for f in meta["files"]:
            path = folder / "statements" / f["name"]
            if path.exists():
                zf.write(path, f"statements/{f['name']}")
    return buffer.getvalue()


def import_zip(data: bytes, base: Optional[Path] = None) -> str:
    """Open a project .zip made by export_zip as a new project. Returns its slug."""
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("That project file is too large.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        meta = json.loads(zf.read("project.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise ValueError("That isn't a project file saved from this app.")
    if sum(info.file_size for info in zf.infolist()) > MAX_ZIP_BYTES:
        raise ValueError("That project file is too large.")
    name = str(meta.get("name") or "").strip()
    slug = create_project(name if len(name) >= 2 else "Imported project", str(meta.get("description") or ""), base)
    files = []
    for entry in meta.get("files", []):
        name = _safe_file_name(entry.get("name", ""))
        try:
            files.append((name, zf.read(f"statements/{entry.get('name', '')}")))
        except KeyError:
            continue
    add_files(slug, files, base)
    imported = load_project(slug, base)
    imported["notes"] = str(meta.get("notes") or "")
    imported["file_notes"] = {str(k): str(v) for k, v in dict(meta.get("file_notes") or {}).items()}
    imported["txn_notes"] = {str(k): str(v) for k, v in dict(meta.get("txn_notes") or {}).items()}
    imported["created"] = str(meta.get("created") or imported["created"])
    save_project(imported, base)
    return slug
