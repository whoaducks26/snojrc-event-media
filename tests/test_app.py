import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image
from werkzeug.datastructures import MultiDict


class EventMediaAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage = Path(cls.temp_dir.name)
        os.environ.update(
            {
                "ADMIN_PASSWORD": "admin-test-password",
                "ACCESS_PASSWORD": "viewer-test-code",
                "SECRET_KEY": "test-secret-key",
                "MEDIA_ROOT": str(cls.storage / "media"),
                "CACHE_ROOT": str(cls.storage / "cache"),
            }
        )

        import main

        cls.main = main
        cls.app = main.app
        cls.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        for root in (self.main.MEDIA_ROOT, self.main.CACHE_ROOT):
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True)
        self.client = self.app.test_client()

    def unlock_viewer(self):
        response = self.client.post(
            "/access",
            data={"password": "viewer-test-code", "next": "/"},
        )
        self.assertEqual(response.status_code, 302)

    def login_admin(self):
        response = self.client.post(
            "/admin/login",
            data={"password": "admin-test-password", "next": "/"},
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            return session["csrf"]

    @staticmethod
    def jpeg_bytes():
        output = io.BytesIO()
        Image.new("RGB", (40, 30), color=(10, 15, 121)).save(output, "JPEG")
        output.seek(0)
        return output

    @staticmethod
    def mp4_bytes():
        # Minimal ISO-BMFF header used to exercise the upload/type path.
        return io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)

    def test_gallery_is_protected_but_health_is_public(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/access", response.headers["Location"])

        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json(), {"status": "ok"})

        self.unlock_viewer()
        gallery = self.client.get("/")
        self.assertEqual(gallery.status_code, 200)
        self.assertIn(b"Competition galleries", gallery.data)
        self.assertIn("noindex", gallery.headers["X-Robots-Tag"])
        self.assertIn("frame-ancestors 'none'", gallery.headers["Content-Security-Policy"])

        with self.client.session_transaction() as session:
            csrf = session["csrf"]
        logged_out = self.client.post("/access/logout", data={"csrf": csrf})
        self.assertEqual(logged_out.status_code, 302)
        self.assertIn("/access", logged_out.headers["Location"])
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_admin_can_create_upload_browse_and_export_photo_and_video(self):
        csrf = self.login_admin()
        created = self.client.post(
            "/admin/mkdir/",
            data={"csrf": csrf, "name": "SNOJRC 2026"},
        )
        self.assertEqual(created.status_code, 302)

        photo_stream = self.jpeg_bytes()
        video_stream = self.mp4_bytes()
        payload = MultiDict(
            [
                ("csrf", csrf),
                ("media", (photo_stream, "jump-01.jpg")),
                ("media", (video_stream, "routine-01.mp4")),
            ]
        )
        uploaded = self.client.post(
            "/admin/upload/SNOJRC%202026",
            data=payload,
            content_type="multipart/form-data",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.get_json()["saved"], 2)
        uploaded.close()
        photo_stream.close()
        video_stream.close()

        gallery = self.client.get("/browse/SNOJRC%202026")
        self.assertEqual(gallery.status_code, 200)
        self.assertIn(b"jump-01.jpg", gallery.data)
        self.assertIn(b"routine-01.mp4", gallery.data)
        self.assertIn(b'data-kind="video"', gallery.data)

        video = self.client.get(
            "/media/SNOJRC%202026/routine-01.mp4",
            headers={"Range": "bytes=0-7"},
        )
        self.assertEqual(video.status_code, 206)
        self.assertEqual(video.data, b"\x00\x00\x00\x18ftyp")
        self.assertIn("private", video.headers["Cache-Control"])
        video.close()

        archive_response = self.client.get("/zip/SNOJRC%202026")
        self.assertEqual(archive_response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive_response.data)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["jump-01.jpg", "routine-01.mp4"])
        archive_response.close()

    def test_rejects_disguised_video_and_path_traversal(self):
        csrf = self.login_admin()
        self.client.post(
            "/admin/mkdir/",
            data={"csrf": csrf, "name": "Safe"},
        )
        rejected = self.client.post(
            "/admin/upload/Safe",
            data={
                "csrf": csrf,
                "media": (io.BytesIO(b"not a video"), "unsafe.mp4"),
            },
            content_type="multipart/form-data",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.get_json()["saved"], 0)
        self.assertTrue(rejected.get_json()["skipped"])

        traversal = self.client.get("/browse/%2e%2e/%2e%2e")
        self.assertEqual(traversal.status_code, 404)


if __name__ == "__main__":
    unittest.main()
