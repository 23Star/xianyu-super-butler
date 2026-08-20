import asyncio
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx
import imageio_ffmpeg


MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_MEDIA_DOMAINS = (
    "alicdn.com",
    "aliyuncs.com",
    "dingtalk.cn",
    "dingtalk.com",
)


class AudioProxyError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class AudioProxy:
    async def get_playable_audio(self, url: str) -> tuple:
        content, content_type = await self._download(url)
        if self._is_amr(content, content_type):
            return await self._transcode_amr(content), "audio/wav"
        return content, content_type or "application/octet-stream"

    async def _download(self, url: str) -> tuple:
        current_url = url
        async with httpx.AsyncClient(timeout=20.0) as client:
            for _ in range(5):
                self._validate_url(current_url)
                try:
                    response = await client.get(current_url)
                except httpx.HTTPError as exc:
                    raise AudioProxyError("闲鱼语音下载失败") from exc
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise AudioProxyError("闲鱼语音重定向地址缺失")
                    current_url = urljoin(current_url, location)
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise AudioProxyError(
                        f"闲鱼语音下载失败: HTTP {response.status_code}"
                    ) from exc
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_AUDIO_BYTES:
                            raise AudioProxyError("闲鱼语音文件过大", status_code=413)
                    except ValueError:
                        pass
                if len(response.content) > MAX_AUDIO_BYTES:
                    raise AudioProxyError("闲鱼语音文件过大", status_code=413)
                content_type = response.headers.get("content-type")
                if content_type:
                    content_type = content_type.split(";", 1)[0].strip().lower()
                return response.content, content_type
        raise AudioProxyError("闲鱼语音重定向次数过多")

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        allowed = any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in ALLOWED_MEDIA_DOMAINS
        )
        if parsed.scheme != "https" or not allowed:
            raise AudioProxyError("不允许代理该语音地址", status_code=422)

    @staticmethod
    def _is_amr(content: bytes, content_type: Optional[str]) -> bool:
        return content.startswith((b"#!AMR\n", b"#!AMR-WB\n")) or content_type in {
            "audio/amr",
            "audio/amr-wb",
        }

    @staticmethod
    async def _transcode_amr(content: bytes) -> bytes:
        process = await asyncio.create_subprocess_exec(
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            "pipe:0",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "wav",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, error = await asyncio.wait_for(process.communicate(content), timeout=30.0)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AudioProxyError("闲鱼语音转码超时") from exc
        if process.returncode != 0 or not output:
            detail = error.decode("utf-8", errors="replace").strip()
            raise AudioProxyError(f"闲鱼语音转码失败: {detail or 'unknown error'}")
        return AudioProxy._finalize_wave_header(output)

    @staticmethod
    def _finalize_wave_header(content: bytes) -> bytes:
        if len(content) < 20 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            raise AudioProxyError("闲鱼语音转码结果不是有效 WAV")
        result = bytearray(content)
        result[4:8] = (len(result) - 8).to_bytes(4, "little")
        offset = 12
        while offset + 8 <= len(result):
            chunk_id = bytes(result[offset : offset + 4])
            chunk_size = int.from_bytes(result[offset + 4 : offset + 8], "little")
            if chunk_id == b"data":
                result[offset + 4 : offset + 8] = (len(result) - offset - 8).to_bytes(
                    4, "little"
                )
                return bytes(result)
            offset += 8 + chunk_size + (chunk_size % 2)
        raise AudioProxyError("闲鱼语音转码结果缺少 WAV 数据块")
