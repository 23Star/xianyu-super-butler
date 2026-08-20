import base64
import unittest

import msgpack

from utils.im_media import parse_ffmpeg_probe, resolve_media


def encode_media_id(prefix, metadata):
    encoded = base64.urlsafe_b64encode(msgpack.packb(metadata, use_bin_type=True)).decode().rstrip("=")
    return prefix + encoded, encoded


class ImMediaTests(unittest.TestCase):
    def test_resolves_plain_media_id(self):
        media_id, encoded = encode_media_id("@", [6, 1000, 720, 1280])

        resource = resolve_media(media_id, "https://media.test/path")

        self.assertEqual(resource, {
            "url": f"https://media.test/media/{encoded}_1280_720.mp4",
            "width": 1280,
            "height": 720,
            "fileType": "mp4",
        })

    def test_resolves_authenticated_media_id(self):
        media_id, encoded = encode_media_id("$", {2: "ogg", 3: 0, 4: 0, 5: 0})

        resource = resolve_media(media_id, "media.test")

        self.assertEqual(resource, {
            "url": f"https://media.test/ddmedia/{encoded}.ogg",
            "width": None,
            "height": None,
            "fileType": "ogg",
        })

    def test_keeps_direct_media_url(self):
        self.assertEqual(resolve_media("http://media.test/a.jpg")["url"], "https://media.test/a.jpg")

    def test_parse_ffmpeg_probe(self):
        info = parse_ffmpeg_probe(
            "Duration: 00:00:03.20, start: 0.000000, bitrate: 128 kb/s\n"
            "Stream #0:0: Video: h264 (High), yuv420p, 1280x720, 25 fps"
        )
        self.assertEqual(info["durationMs"], 3200)
        self.assertEqual(info["width"], 1280)
        self.assertEqual(info["height"], 720)
