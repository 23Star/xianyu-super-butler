"""Utilities for parsing and comparing Xianyu product specifications."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Tuple


DEFAULT_SPEC_KEY = "__default__"

_PAIR_SEPARATOR_RE = re.compile(r"\s*(?:[|;,\n\r、]+|\+)\s*")
_KEY_VALUE_RE = re.compile(r"^\s*([^=:]+?)\s*[=:]\s*(.+?)\s*$")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_component(value: Any) -> str:
    """Normalize a specification dimension or value for stable comparison."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text.casefold()


def parse_specification(
    value: Any = None,
    *,
    spec_name: Optional[str] = None,
    spec_value: Optional[str] = None,
) -> Dict[str, str]:
    """Parse structured or textual specification data into normalized pairs."""
    raw_pairs: List[Tuple[Any, Any]] = []

    if isinstance(value, Mapping):
        raw_pairs.extend(value.items())
    elif isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip()
        if text:
            if text.startswith("{"):
                try:
                    decoded = json.loads(text)
                    if isinstance(decoded, Mapping):
                        raw_pairs.extend(decoded.items())
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

            if not raw_pairs:
                for segment in _PAIR_SEPARATOR_RE.split(text):
                    segment = segment.strip()
                    if not segment:
                        continue
                    match = _KEY_VALUE_RE.match(segment)
                    if match:
                        raw_pairs.append((match.group(1), match.group(2)))

    if spec_name and spec_value and not raw_pairs:
        raw_pairs.append((spec_name, spec_value))

    normalized: Dict[str, str] = {}
    for key, raw_value in raw_pairs:
        normalized_key = normalize_component(key)
        normalized_value = normalize_component(raw_value)
        if normalized_key and normalized_value:
            existing_value = normalized.get(normalized_key)
            if existing_value is not None and existing_value != normalized_value:
                return {}
            normalized[normalized_key] = normalized_value
    return normalized


def canonicalize_specification(
    value: Any = None,
    *,
    spec_name: Optional[str] = None,
    spec_value: Optional[str] = None,
    allow_default: bool = False,
) -> Tuple[str, Dict[str, str]]:
    """Return a stable specification key and normalized payload."""
    payload = parse_specification(
        value,
        spec_name=spec_name,
        spec_value=spec_value,
    )
    if not payload:
        return (DEFAULT_SPEC_KEY if allow_default else ""), {}

    key = "|".join(f"{name}={payload[name]}" for name in sorted(payload))
    return key, payload


def specification_text(payload: Mapping[str, Any]) -> str:
    """Format a specification payload for logs and UI."""
    parts = []
    for key, value in payload.items():
        clean_key = str(key or "").strip()
        clean_value = str(value or "").strip()
        if clean_key and clean_value:
            parts.append(f"{clean_key}={clean_value}")
    return " | ".join(parts)


def combine_legacy_specification(spec_name: Any, spec_value: Any) -> str:
    """Combine legacy single-pair fields without losing an existing multi-pair value."""
    name = str(spec_name or "").strip()
    value = str(spec_value or "").strip()
    if not name or not value:
        return ""
    return f"{name}={value}"
