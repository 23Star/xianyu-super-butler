import base64
import re
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import msgpack


DEFAULT_MEDIA_HOST = "down.im.dingtalk.cn"
MEDIA_TYPES = {
    0: "jpg",
    1: "gif",
    2: "png",
    3: "bmp",
    4: "amr",
    5: "mp3",
    6: "mp4",
    7: "wav",
    29: "webp",
    30: "opus",
    31: "ogg",
}


def resolve_media(value: Any, media_host: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {"url": None, "width": None, "height": None, "fileType": None}
    if not value.startswith(("@", "$")):
        url = "https" + value[4:] if value.startswith("http:") else value
        return {"url": url, "width": None, "height": None, "fileType": None}

    prefix = value[0]
    encoded = value[1:]
    try:
        raw = base64.b64decode(
            encoded.replace("-", "+").replace("_", "/") + "=" * (-len(encoded) % 4)
        )
        metadata = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    except Exception:
        return {"url": None, "width": None, "height": None, "fileType": None}

    host = _normalize_host(media_host)
    if prefix == "@":
        file_type = MEDIA_TYPES.get(_value(metadata, 0), "file")
        height = _value(metadata, 2, 0) or 0
        width = _value(metadata, 3, 0) or 0
        suffix = f"_{width}_{height}.{file_type}"
        path = "media"
    else:
        file_type = str(_value(metadata, 2, "file")).lower()
        width = _value(metadata, 4, 0) or 0
        height = _value(metadata, 5, 0) or 0
        suffix = f".{file_type}"
        path = "ddmedia"

    return {
        "url": f"https://{host}/{path}/{encoded}{suffix}",
        "width": width or None,
        "height": height or None,
        "fileType": file_type,
    }


def binary_data_url(value: Any, mime_type: str) -> Optional[str]:
    raw = None
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, list) and all(isinstance(item, int) for item in value):
        raw = bytes(value)
    elif isinstance(value, dict):
        try:
            raw = bytes(value[key] for key in sorted(value, key=lambda item: int(item)))
        except (KeyError, TypeError, ValueError):
            raw = None
    if not raw:
        return None
    return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"


def _normalize_host(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_MEDIA_HOST
    parsed = urlsplit(value if "://" in value else f"//{value}")
    return parsed.netloc or parsed.path.split("/", 1)[0] or DEFAULT_MEDIA_HOST


def _value(container: Any, key: int, default: Any = None) -> Any:
    if isinstance(container, (list, tuple)):
        return container[key] if 0 <= key < len(container) else default
    if isinstance(container, dict):
        if key in container:
            return container[key]
        return container.get(str(key), default)
    return default


def parse_ffmpeg_probe(text: str) -> Dict[str, Any]:
    duration_ms = 0
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text or "")
    if match:
        duration_ms = int(
            (int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))) * 1000
        )
    width = height = 0
    video = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text or "")
    if video:
        width, height = int(video.group(1)), int(video.group(2))
    return {"durationMs": duration_ms, "width": width or None, "height": height or None}


async def probe_media(path: str) -> Dict[str, Any]:
    import asyncio

    import imageio_ffmpeg

    process = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-i",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, error = await asyncio.wait_for(process.communicate(), timeout=20.0)
    except TimeoutError:
        process.kill()
        await process.wait()
        return {"durationMs": 0, "width": None, "height": None}
    return parse_ffmpeg_probe(error.decode("utf-8", errors="replace"))
