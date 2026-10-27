"""
Banks saved by users ("templates"), from the Add a New Bank tab.

A saved bank is a name plus keywords that identify its statements (for example its web
address). When an uploaded statement contains every keyword, it is labelled with that bank's
name and read with the saved settings: the reading style, the default direction for amounts
with no sign, and words that mark money in. Saved banks are kept in statement_templates.json
next to the app (git-ignored), or in browser storage in the browser version.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pdf_text import extract_pdf


# The browser build points this at browser storage so saved templates survive a page reload.
TEMPLATES_PATH = Path(os.environ.get("STATEMENT_TEMPLATES_PATH") or Path(__file__).with_name("statement_templates.json"))
# "auto" uses the generic reader (auto_parser.py); the other two are older line-based layouts.
ALLOWED_PARSE_STYLES = {"auto", "slash_leading_amount_balance", "date_dash_last_amount"}
ALLOWED_DIRECTIONS = {"credit", "debit"}


def _normalize_keywords(raw_keywords: List[str]) -> List[str]:
    """Lower-case, trimmed, de-duplicated keywords in a stable order."""
    cleaned = [kw.strip().lower() for kw in raw_keywords if str(kw).strip()]
    deduped = sorted(set(cleaned))
    return deduped


def _validate_template(template: Dict) -> Tuple[bool, str]:
    """Check a template has every field and sensible values. Returns (ok, message for the user)."""
    required = {"template_name", "detection_keywords", "parse_style", "default_direction", "credit_keywords"}
    missing = [field for field in required if field not in template]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    name = str(template["template_name"]).strip()
    if len(name) < 3:
        return False, "Template name must be at least 3 characters."

    parse_style = str(template["parse_style"]).strip()
    if parse_style not in ALLOWED_PARSE_STYLES:
        return False, "Invalid parse style."

    default_direction = str(template["default_direction"]).strip().lower()
    if default_direction not in ALLOWED_DIRECTIONS:
        return False, "Default direction must be 'credit' or 'debit'."

    keywords = _normalize_keywords(list(template.get("detection_keywords", [])))
    if not keywords:
        return False, "Provide at least one detection keyword."

    return True, ""


def _read_templates_file() -> List[Dict]:
    """The saved templates as a list of dicts; an empty list if the file is missing or unreadable."""
    if not TEMPLATES_PATH.exists():
        return []
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def load_templates() -> List[Dict]:
    """Every saved bank, with fields cleaned up; entries without a name are skipped."""
    templates = _read_templates_file()
    normalized: List[Dict] = []
    for template in templates:
        normalized.append(
            {
                "template_name": str(template.get("template_name", "")).strip(),
                "detection_keywords": _normalize_keywords(list(template.get("detection_keywords", []))),
                "parse_style": str(template.get("parse_style", "slash_leading_amount_balance")).strip(),
                "default_direction": str(template.get("default_direction", "debit")).strip().lower(),
                "credit_keywords": _normalize_keywords(list(template.get("credit_keywords", []))),
            }
        )
    return [t for t in normalized if t["template_name"]]


def save_template(template: Dict) -> Tuple[bool, str]:
    """Validate and save a bank (replacing one with the same name). Returns (ok, message for the user)."""
    candidate = {
        "template_name": str(template.get("template_name", "")).strip(),
        "detection_keywords": _normalize_keywords(list(template.get("detection_keywords", []))),
        "parse_style": str(template.get("parse_style", "")).strip(),
        "default_direction": str(template.get("default_direction", "debit")).strip().lower(),
        "credit_keywords": _normalize_keywords(list(template.get("credit_keywords", []))),
    }
    ok, message = _validate_template(candidate)
    if not ok:
        return False, message

    # Saving a bank with an existing name (ignoring case) replaces it.
    templates = load_templates()
    existing_idx: Optional[int] = None
    for idx, current in enumerate(templates):
        if current["template_name"].lower() == candidate["template_name"].lower():
            existing_idx = idx
            break

    if existing_idx is None:
        templates.append(candidate)
    else:
        templates[existing_idx] = candidate

    TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(json.dumps(templates, indent=2), encoding="utf-8")
    if existing_idx is None:
        return True, "Template saved."
    return True, "Template updated."


def delete_template(template_name: str) -> Tuple[bool, str]:
    """Delete the saved bank with this name (ignoring case). Returns (ok, message for the user)."""
    name = str(template_name).strip().lower()
    if not name:
        return False, "Template name is required."

    templates = load_templates()
    kept = [tpl for tpl in templates if tpl["template_name"].strip().lower() != name]
    if len(kept) == len(templates):
        return False, "Template not found."

    TEMPLATES_PATH.write_text(json.dumps(kept, indent=2), encoding="utf-8")
    return True, "Template deleted."


def detect_template(full_text: str, templates: List[Dict]) -> Optional[Dict]:
    """The first saved bank whose keywords all appear in the statement's text, if any."""
    text = (full_text or "").lower()
    for template in templates:
        keywords = template.get("detection_keywords", [])
        if keywords and all(keyword in text for keyword in keywords):
            return template
    return None


def extract_preview_text(file_bytes: bytes, max_lines: int = 120) -> str:
    """The statement's first non-blank lines of text, shown as a preview when adding a bank."""
    merged = "\n".join(extract_pdf(file_bytes).pages)
    lines = [line for line in merged.splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])
