import unittest

from utils.im_audio import AudioProxy, AudioProxyError


class ImAudioTests(unittest.IsolatedAsyncioTestCase):
    def test_audio_proxy_only_allows_known_https_media_domains(self):
        AudioProxy._validate_url("https://gw.alicdn.com/voice.amr")
        AudioProxy._validate_url("https://xianyu-audio.oss-cn-hangzhou.aliyuncs.com/voice.amr")
        AudioProxy._validate_url("https://down.im.dingtalk.cn/media/voice.amr")

        with self.assertRaises(AudioProxyError) as insecure:
            AudioProxy._validate_url("http://gw.alicdn.com/voice.amr")
        with self.assertRaises(AudioProxyError) as unknown:
            AudioProxy._validate_url("https://example.com/voice.amr")

        self.assertEqual(insecure.exception.status_code, 422)
        self.assertEqual(unknown.exception.status_code, 422)

    async def test_audio_proxy_transcodes_amr_and_keeps_other_audio(self):
        proxy = AudioProxy()

        async def download_amr(url):
            return b"#!AMR\nsource", "audio/amr"

        async def transcode(content):
            self.assertEqual(content, b"#!AMR\nsource")
            return b"RIFFplayable-wave"

        proxy._download = download_amr
        proxy._transcode_amr = transcode

        content, content_type = await proxy.get_playable_audio("https://gw.alicdn.com/a.amr")
        self.assertEqual(content, b"RIFFplayable-wave")
        self.assertEqual(content_type, "audio/wav")

        async def download_mp3(url):
            return b"ID3source", "audio/mpeg"

        proxy._download = download_mp3

        content, content_type = await proxy.get_playable_audio("https://gw.alicdn.com/a.mp3")
        self.assertEqual(content, b"ID3source")
        self.assertEqual(content_type, "audio/mpeg")

    def test_audio_proxy_finalizes_streamed_wave_sizes(self):
        wave = (
            b"RIFF"
            + b"\xff\xff\xff\xff"
            + b"WAVE"
            + b"fmt "
            + (16).to_bytes(4, "little")
            + b"\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00"
            + b"data"
            + b"\xff\xff\xff\xff"
            + b"\x00\x00\x00\x00"
        )

        result = AudioProxy._finalize_wave_header(wave)

        self.assertEqual(int.from_bytes(result[4:8], "little"), len(result) - 8)
        self.assertEqual(int.from_bytes(result[40:44], "little"), 4)
