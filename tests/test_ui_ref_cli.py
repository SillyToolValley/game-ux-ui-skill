import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ui_ref_cli


class UiRefLegacyCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ui_ref_cli.main(["--project-root", str(self.root), *arguments])
        return result, output.getvalue()

    def test_init_is_idempotent_and_preserves_unknown_metadata(self) -> None:
        result, _ = self.run_cli("init", "--project-name", "First")
        self.assertEqual(result, 0)
        config_path = self.root / "ui_ref_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["team_note"] = "keep me"
        config["default_delay_seconds"] = 1.25
        config_path.write_text(json.dumps(config), encoding="utf-8")

        result, _ = self.run_cli("init", "--project-name", "Renamed")
        self.assertEqual(result, 0)
        refreshed = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(refreshed["project_name"], "Renamed")
        self.assertEqual(refreshed["team_note"], "keep me")
        self.assertEqual(refreshed["default_delay_seconds"], 1.25)

    def test_scan_local_indexes_png_dimensions_and_provenance(self) -> None:
        self.run_cli("init")
        image = self.root / "references" / "ui" / "roguelite" / "hud" / "sample.png"
        image.parent.mkdir(parents=True)
        # Minimal PNG header is enough for the dependency-free dimension reader.
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (320).to_bytes(4, "big") + (180).to_bytes(4, "big"))

        result, _ = self.run_cli("scan-local")
        self.assertEqual(result, 0)
        manifest = json.loads((self.root / "ui_research" / "manifests" / "local_ui_refs_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_type"], "local_scan")
        self.assertEqual(manifest["items"][0]["width"], 320)
        self.assertEqual(manifest["items"][0]["height"], 180)
        self.assertIn("hud", manifest["items"][0]["tags"])
        self.assertEqual(len(manifest["items"][0]["sha256"]), 64)
        self.assertTrue(manifest["generated_at"].endswith("Z"))

    def test_configured_paths_cannot_escape_project_root(self) -> None:
        self.run_cli("init")
        config_path = self.root / "ui_ref_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["workspace"] = "../outside"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "inside the project root"):
            self.run_cli("scan-local")

    def test_private_and_unsafe_urls_are_rejected_without_network_access(self) -> None:
        cases = {
            "file:///etc/passwd": "unsupported-scheme",
            "http://localhost/test": "private-host",
            "http://127.0.0.1/test": "non-public-address",
            "http://[::1]/test": "non-public-address",
            "https://user:secret@example.com/test": "userinfo-not-allowed",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                allowed, reason = ui_ref_cli.is_public_http_url(url)
                self.assertFalse(allowed)
                self.assertIn(expected, reason)

    def test_collect_rejects_invalid_numeric_limits_before_fetching(self) -> None:
        self.run_cli("init")
        with self.assertRaisesRegex(SystemExit, "--max-pages must be >= 1"):
            self.run_cli("collect", "--url", "http://localhost", "--max-pages", "0")

    def test_static_fetch_rejects_non_html_and_keeps_final_url(self) -> None:
        class Headers(dict):
            def get_content_charset(self):
                return "utf-8"

        class Response:
            status = 200
            headers = Headers({"content-type": "image/png"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size=-1):
                return b"not html"

            def geturl(self):
                return "https://example.com/final"

        with mock.patch.object(ui_ref_cli, "safe_urlopen", return_value=Response()):
            result = ui_ref_cli.fetch_static("https://example.com/start", "test", 1)
        self.assertEqual(result.url, "https://example.com/final")
        self.assertIn("non-HTML", result.error)
        self.assertEqual(result.html, "")

    def test_contact_sheet_blocks_unsafe_link_schemes(self) -> None:
        output = self.root / "sheet.html"
        shown = ui_ref_cli.write_contact_sheet(
            output,
            "test",
            [{"downloaded_assets": [], "gallery_items": [{"title": "bad", "image_url": "javascript:alert(1)"}]}],
            self.root,
        )
        self.assertEqual(shown, 0)
        html = output.read_text(encoding="utf-8")
        self.assertNotIn("javascript:", html)
        self.assertIn('href="#"', html)


if __name__ == "__main__":
    unittest.main()
