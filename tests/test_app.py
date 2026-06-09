import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app


class DummyHandler:
    def __init__(self):
        self.sent = None

    def send_html(self, content, status=200):
        self.sent = (content.decode("utf-8"), status)


class CleanupTests(unittest.TestCase):
    def test_clear_generated_files_deletes_contents_and_keeps_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload_dir = root / "uploads"
            output_dir = root / "output"
            extract_dir = root / "extracted"

            (upload_dir / "jpg").mkdir(parents=True)
            (upload_dir / "jpg" / "source.jpg").write_bytes(b"jpg")
            output_dir.mkdir()
            (output_dir / "hidden.jpg").write_bytes(b"hidden")
            (extract_dir / "extract_1").mkdir(parents=True)
            (extract_dir / "extract_1" / "file.txt").write_text("payload", encoding="utf-8")

            result = app.clear_generated_files([upload_dir, output_dir, extract_dir])

            self.assertEqual(result["deleted_count"], 3)
            self.assertEqual(result["failed"], [])
            self.assertTrue(upload_dir.exists())
            self.assertTrue(output_dir.exists())
            self.assertTrue(extract_dir.exists())
            self.assertEqual(list(upload_dir.iterdir()), [])
            self.assertEqual(list(output_dir.iterdir()), [])
            self.assertEqual(list(extract_dir.iterdir()), [])

    def test_clear_generated_files_handles_empty_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = [root / "uploads", root / "output", root / "extracted"]

            result = app.clear_generated_files(dirs)

            self.assertEqual(result["deleted_count"], 0)
            self.assertEqual(result["failed"], [])
            for directory in dirs:
                self.assertTrue(directory.exists())

    def test_clear_files_route_returns_success_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dirs = (app.UPLOAD_DIR, app.OUTPUT_DIR, app.EXTRACT_DIR)
            try:
                app.UPLOAD_DIR = Path(tmp) / "uploads"
                app.OUTPUT_DIR = Path(tmp) / "output"
                app.EXTRACT_DIR = Path(tmp) / "extracted"
                app.OUTPUT_DIR.mkdir(parents=True)
                (app.OUTPUT_DIR / "hidden.jpg").write_bytes(b"hidden")

                handler = DummyHandler()
                handler.path = "/clear-files"

                app.Handler.do_POST(handler)

                body, status = handler.sent
                self.assertEqual(status, 200)
                self.assertIn("已清理 1 项系统生成文件", body)
                self.assertEqual(list(app.OUTPUT_DIR.iterdir()), [])
            finally:
                app.UPLOAD_DIR, app.OUTPUT_DIR, app.EXTRACT_DIR = original_dirs


if __name__ == "__main__":
    unittest.main()
