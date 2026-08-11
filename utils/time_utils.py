import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo


DB_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOCAL_DATE_FORMAT = "%Y-%m-%d"
UTC = timezone.utc
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def get_local_now() -> datetime:
    """返回当前北京时间。"""
    return datetime.now(LOCAL_TIMEZONE)


def parse_db_timestamp(value: str) -> Optional[datetime]:
    """将数据库时间字符串按 UTC 解析为 datetime。"""
    text = str(value or "").strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(text, DB_DATETIME_FORMAT)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def to_db_utc_string(value: datetime) -> str:
    """将 datetime 转成数据库使用的 UTC 时间字符串。"""
    if value.tzinfo is None:
        aware_value = value.replace(tzinfo=LOCAL_TIMEZONE)
    else:
        aware_value = value
    return aware_value.astimezone(UTC).strftime(DB_DATETIME_FORMAT)


def parse_local_datetime_text_to_db_utc(value: str) -> Optional[str]:
    """将中文/本地时间文本解析为数据库使用的 UTC 时间字符串。"""
    text = str(value or "").strip()
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
    match = re.search(
        r"(?P<year>\d{4})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})"
        r"\s*(?:日)?\s*(?:T|\s+)\s*(?P<hour>\d{1,2})\s*:\s*(?P<minute>\d{1,2})"
        r"(?:\s*:\s*(?P<second>\d{1,2}))?",
        normalized,
    )
    if not match:
        return None

    try:
        local_datetime = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second") or 0),
            tzinfo=LOCAL_TIMEZONE,
        )
    except ValueError:
        return None

    return to_db_utc_string(local_datetime)


def local_date_to_utc_start(date_str: str) -> Optional[str]:
    """将北京时间日期转成 UTC 起始时间字符串。"""
    text = str(date_str or "").strip()
    if not text:
        return None

    try:
        local_start = datetime.strptime(text, LOCAL_DATE_FORMAT).replace(tzinfo=LOCAL_TIMEZONE)
    except ValueError:
        return None
    return to_db_utc_string(local_start)


def local_date_to_utc_end_exclusive(date_str: str) -> Optional[str]:
    """将北京时间日期转成次日零点的 UTC 时间字符串。"""
    text = str(date_str or "").strip()
    if not text:
        return None

    try:
        local_start = datetime.strptime(text, LOCAL_DATE_FORMAT).replace(tzinfo=LOCAL_TIMEZONE)
    except ValueError:
        return None
    return to_db_utc_string(local_start + timedelta(days=1))


def utc_timestamp_to_local_date_string(value: str) -> Optional[str]:
    """将 UTC 时间字符串转换为北京时间日期字符串。"""
    parsed = parse_db_timestamp(value)
    if not parsed:
        return None
    return parsed.astimezone(LOCAL_TIMEZONE).strftime(LOCAL_DATE_FORMAT)


def utc_timestamp_to_local_datetime(value: str) -> Optional[datetime]:
    """将 UTC 时间字符串转换为北京时间 datetime。"""
    parsed = parse_db_timestamp(value)
    if not parsed:
        return None
    return parsed.astimezone(LOCAL_TIMEZONE)
