"""Sensitive value redaction for application logs."""

from __future__ import annotations

import re
from typing import Any, MutableMapping


REDACTED = "<REDACTED>"

_SENSITIVE_KEYS = (
    "_m_h5_tk",
    "_m_h5_tk_enc",
    "accessToken",
    "access_token",
    "cookie2",
    "password",
    "refreshToken",
    "refresh_token",
    "sgcookie",
    "sign",
    "smToken",
    "token",
    "x5sec",
)

_KEY_PATTERN = "|".join(
    sorted((re.escape(key) for key in _SENSITIVE_KEYS), key=len, reverse=True)
)

_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)(\bauthorization\s*:\s*bearer\s+)[^\s,;]+"
)
_COOKIE_HEADER_PATTERN = re.compile(r"(?i)(\bcookie\s*[=:]\s*)[^\r\n]+")
_PAIR_PATTERN = re.compile(
    rf"(?i)\b(?P<key>{_KEY_PATTERN})\b"
    rf"(?P<separator>\s*[=:]\s*)"
    rf"(?P<value>[^\s,;\]\}}]+)"
)
_QUOTED_PATTERN = re.compile(
    rf"""(?ix)
    (?P<quote>["'])
    (?P<key>{_KEY_PATTERN})
    (?P=quote)
    (?P<separator>\s*:\s*)
    (?P<value>
        "(?:\\.|[^"\\])*"
        |
        '(?:\\.|[^'\\])*'
        |
        [^,\}}\]]+
    )
    """
)

_REDACTION_PATTERNS = (
    _AUTHORIZATION_PATTERN,
    _COOKIE_HEADER_PATTERN,
    _QUOTED_PATTERN,
    _PAIR_PATTERN,
)


def redact_sensitive_text(value: Any) -> str:
    """Return a log-safe representation without secret values."""
    text = str(value)
    for pattern in _REDACTION_PATTERNS:
        if pattern is _AUTHORIZATION_PATTERN or pattern is _COOKIE_HEADER_PATTERN:
            text = pattern.sub(rf"\1{REDACTED}", text)
            continue

        if pattern is _QUOTED_PATTERN:
            text = pattern.sub(
                lambda match: (
                    f"{match.group('quote')}{match.group('key')}{match.group('quote')}"
                    f"{match.group('separator')}\"{REDACTED}\""
                ),
                text,
            )
            continue

        text = pattern.sub(
            lambda match: (
                f"{match.group('key')}{match.group('separator')}{REDACTED}"
            ),
            text,
        )
    return text


def redact_log_record(record: MutableMapping[str, Any]) -> None:
    """Loguru patcher that sanitizes every emitted message."""
    record["message"] = redact_sensitive_text(record.get("message", ""))
