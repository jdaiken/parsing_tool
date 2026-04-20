from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber


TEMPLATES_PATH = Path(__file__).with_name("statement_templates.json")
ALLOWED_PARSE_STYLES = {"slash_leading_amount_balance", "date_dash_last_amount"}
ALLOWED_DIRECTIONS = {"credit", "debit"}


def _normalize_keywords(raw_keywords: List[str]) -> List[str]:
    cleaned = [kw.strip().lower() for kw in raw_keywords if str(kw).strip()]
    deduped = sorted(set(cleaned))
    return deduped


def _validate_template(template: Dict) -> Tuple[bool, str]:
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

    TEMPLATES_PATH.write_text(json.dumps(templates, indent=2), encoding="utf-8")
    if existing_idx is None:
        return True, "Template saved."
    return True, "Template updated."


def delete_template(template_name: str) -> Tuple[bool, str]:
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
    text = (full_text or "").lower()
    for template in templates:
        keywords = template.get("detection_keywords", [])
        if keywords and all(keyword in text for keyword in keywords):
            return template
    return None


def extract_preview_text(file_bytes: bytes, max_lines: int = 120) -> str:
    pages: List[str] = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    merged = "\n".join(pages)
    lines = [line for line in merged.splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])
