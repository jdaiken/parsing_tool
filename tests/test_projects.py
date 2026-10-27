"""Projects are encrypted at rest, open only with the password, and survive download and reopening."""

import io
import json
import zipfile

import pytest

import projects as P
from conftest import DEMO

PASSWORD = "blue heron at dawn"
PDF = (DEMO / "1_checking_2025-03.pdf").read_bytes()


@pytest.fixture
def project(tmp_path):
    slug, key = P.create_project("Case 2025-014", "Confidential description", PASSWORD, tmp_path)
    P.add_files(slug, [("Hartwell March.pdf", PDF)], tmp_path, key)
    meta = P.load_project(slug, tmp_path, key)
    meta["notes"] = "Secret case note"
    meta["txn_notes"] = {"1_checking_2025-03|1|20": "Ask the bank"}
    P.save_project(meta, tmp_path, key)
    return tmp_path, slug, key


def test_nothing_readable_on_disk(project):
    base, slug, _ = project
    stored = b"".join(p.read_bytes() for p in (base / slug).rglob("*") if p.is_file())
    for secret in (b"Hartwell", b"%PDF", b"Secret case note", b"Confidential", b"Ask the bank"):
        assert secret not in stored
    names = [p.name for p in (base / slug).rglob("*")]
    assert not any("Hartwell" in n or n.endswith(".pdf") for n in names)


def test_password_is_required(project):
    base, slug, key = project
    with pytest.raises(PermissionError):
        P.load_project(slug, base)
    with pytest.raises(ValueError):
        P.unlock(slug, "not the password", base)
    assert P.unlock(slug, PASSWORD, base) == key
    assert P.read_files(slug, base, key) == [("Hartwell March.pdf", PDF)]


def test_short_password_rejected(tmp_path):
    with pytest.raises(ValueError):
        P.create_project("Case 1", "", "short", tmp_path)


def test_tampering_is_detected(project):
    base, slug, key = project
    blob = next((base / slug / "statements").glob("*.enc"))
    data = bytearray(blob.read_bytes())
    data[-1] ^= 1
    blob.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        P.read_files(slug, base, key)


def test_download_and_reopen(project, tmp_path_factory):
    base, slug, key = project
    case = P.export_case(slug, "another long password", base, key)
    assert case.startswith(P.CASE_MAGIC) and b"Secret" not in case and b"%PDF" not in case
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    with pytest.raises(ValueError):
        P.import_case(case, "wrong password here", elsewhere)
    new_slug, new_key = P.import_case(case, "another long password", elsewhere)
    meta = P.load_project(new_slug, elsewhere, new_key)
    assert meta["notes"] == "Secret case note" and meta["txn_notes"] == {"1_checking_2025-03|1|20": "Ask the bank"}
    assert P.read_files(new_slug, elsewhere, new_key) == [("Hartwell March.pdf", PDF)]
    events = [e["event"] for e in meta["log"]]
    assert "Statement added" in events and events[-1] == "Project opened from a downloaded file"


def test_case_log_records_fingerprints(project):
    base, slug, key = project
    log = P.load_project(slug, base, key)["log"]
    assert any(e["event"] == "Statement added" and P.hashlib.sha256(PDF).hexdigest() in e["detail"] for e in log)


def test_older_unencrypted_project_can_be_protected(tmp_path):
    folder = tmp_path / "old"
    (folder / "statements").mkdir(parents=True)
    (folder / "statements" / "a.pdf").write_bytes(PDF)
    (folder / "project.json").write_text(json.dumps({"name": "Old case", "files": [{"name": "a.pdf", "added": "x", "sha256": "y"}]}))
    assert [p["encrypted"] for p in P.list_projects(tmp_path)] == [False]
    key = P.protect("old", PASSWORD, tmp_path)
    assert not (folder / "project.json").exists() and not (folder / "statements" / "a.pdf").exists()
    assert P.read_files("old", tmp_path, key) == [("a.pdf", PDF)]


def test_import_cannot_write_outside_its_folder(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("project.json", json.dumps({"name": "Evil", "files": [{"name": "../../../escape.pdf"}]}))
        zf.writestr("../../../escape.pdf", b"x")
    slug, _ = P.import_case(buffer.getvalue(), PASSWORD, tmp_path / "projects")
    assert not (tmp_path / "escape.pdf").exists()
    assert all(p.is_relative_to(tmp_path / "projects") for p in tmp_path.rglob("*") if p.name != "projects")
    with pytest.raises(ValueError):
        P.load_project("../x", tmp_path / "projects")
