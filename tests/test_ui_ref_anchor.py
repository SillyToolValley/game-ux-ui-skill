import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ui_ref_anchor
import ui_ref_cli


def png_stub(width: int, height: int) -> bytes:
    # A PNG signature plus IHDR size fields is enough for the dependency-free dimension reader.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + width.to_bytes(4, "big") + height.to_bytes(4, "big")


class AnchorWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "hero.png").write_bytes(png_stub(1920, 1080))
        (self.root / "other.png").write_bytes(png_stub(1280, 720) + b"x")
        # Tests never launch a browser: palette extraction reports the extra as missing.
        patcher = mock.patch.object(
            ui_ref_anchor, "extract_palette", side_effect=ui_ref_anchor.BrowserUnavailable("no browser")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ui_ref_cli.main(["--project-root", str(self.root), *arguments])
        return result, output.getvalue()

    def add_hero(self, *extra: str) -> tuple[int, str]:
        return self.run_cli("anchor", "add", "hero.png", "--screen", "Level Up", "--game", "Study Game", *extra)

    def test_add_hero_writes_metadata_and_anatomy_template(self) -> None:
        result, output = self.add_hero("--source-url", "https://example.com/press")
        self.assertEqual(result, 0)
        folder = self.root / "ui_anchor" / "level-up"
        meta = json.loads((folder / "anchor.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["hero"]["file"], "hero.png")
        self.assertEqual((meta["hero"]["width"], meta["hero"]["height"]), (1920, 1080))
        self.assertEqual(meta["hero"]["sha256"], ui_ref_cli.file_sha256(folder / "hero.png"))
        self.assertEqual(meta["hero"]["source_url"], "https://example.com/press")
        self.assertIsNone(meta["hero"]["palette"])
        anatomy = (folder / "ANATOMY.md").read_text(encoding="utf-8")
        self.assertIn("Study Game", anatomy)
        self.assertIn("keep, change, drop", anatomy)
        self.assertIn("Palette not extracted", output)

    def test_second_hero_is_refused_without_force(self) -> None:
        self.add_hero()
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("anchor", "add", "other.png", "--screen", "level-up")
        self.assertIn("already has a hero", str(raised.exception))

    def test_force_replaces_hero_and_keeps_previous_anatomy(self) -> None:
        self.add_hero()
        folder = self.root / "ui_anchor" / "level-up"
        (folder / "ANATOMY.md").write_text("my notes", encoding="utf-8")
        result, _ = self.run_cli("anchor", "add", "other.png", "--screen", "level-up", "--game", "Second", "--force")
        self.assertEqual(result, 0)
        self.assertEqual((folder / "ANATOMY.previous.md").read_text(encoding="utf-8"), "my notes")
        meta = json.loads((folder / "anchor.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["hero"]["game"], "Second")
        self.assertEqual(meta["hero"]["width"], 1280)

    def test_support_needs_hero_and_borrow_and_is_capped(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli("anchor", "add", "other.png", "--screen", "level-up", "--role", "support", "--borrow", "x")
        self.add_hero()
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("anchor", "add", "other.png", "--screen", "level-up", "--role", "support")
        self.assertIn("--borrow", str(raised.exception))
        for index in range(ui_ref_anchor.MAX_SUPPORTS):
            result, _ = self.run_cli("anchor", "add", "other.png", "--screen", "level-up", "--role", "support", "--borrow", f"gap {index}")
            self.assertEqual(result, 0)
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("anchor", "add", "other.png", "--screen", "level-up", "--role", "support", "--borrow", "one more")
        self.assertIn("supports", str(raised.exception))
        meta = json.loads((self.root / "ui_anchor" / "level-up" / "anchor.json").read_text(encoding="utf-8"))
        self.assertEqual([s["file"] for s in meta["supports"]], ["support-1.png", "support-2.png"])

    def test_compare_starts_numbered_rounds_with_sheet_and_critique(self) -> None:
        self.add_hero()
        (self.root / "build.png").write_bytes(png_stub(1920, 1080) + b"candidate")
        for expected in ("01", "02"):
            result, output = self.run_cli("compare", "build.png", "--screen", "level-up")
            self.assertEqual(result, 0)
            round_dir = self.root / "ui_anchor" / "level-up" / "rounds" / expected
            html = (round_dir / "compare.html").read_text(encoding="utf-8")
            self.assertIn('src="../../hero.png"', html)
            self.assertIn('src="candidate.png"', html)
            self.assertIn("Content-Security-Policy", html)
            self.assertTrue((round_dir / "critique.md").exists())
            self.assertEqual(json.loads((round_dir / "round.json").read_text(encoding="utf-8"))["round"], int(expected))
            self.assertIn(f"Round {expected}", output)

    def test_compare_flags_aspect_mismatch_and_round_cap(self) -> None:
        self.add_hero()
        (self.root / "tall.png").write_bytes(png_stub(1080, 1920))
        output = ""
        for _ in range(ui_ref_anchor.ROUND_SOFT_CAP + 1):
            _, output = self.run_cli("compare", "tall.png", "--screen", "level-up")
        self.assertIn("Aspect ratios differ", output)
        self.assertIn("exceeds the usual cap", output)

    def test_compare_escapes_game_title(self) -> None:
        self.run_cli("anchor", "add", "hero.png", "--screen", "hud", "--game", "<script>alert(1)</script>")
        (self.root / "build.png").write_bytes(png_stub(1920, 1080))
        self.run_cli("compare", "build.png", "--screen", "hud")
        html = (self.root / "ui_anchor" / "hud" / "rounds" / "01" / "compare.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_adhoc_compare_requires_output_inside_project(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli("compare", "hero.png", "--against", "other.png", "--out", "../outside.html")
        result, _ = self.run_cli("compare", "hero.png", "--against", "other.png", "--out", "review/sheet.html")
        self.assertEqual(result, 0)
        html = (self.root / "review" / "sheet.html").read_text(encoding="utf-8")
        self.assertIn('src="../other.png"', html)
        self.assertIn('src="../hero.png"', html)

    def test_show_reports_anatomy_progress(self) -> None:
        self.add_hero()
        _, output = self.run_cli("anchor", "show")
        self.assertIn("level-up", output)
        self.assertIn("TODO left", output)
        (self.root / "ui_anchor" / "level-up" / "ANATOMY.md").write_text("done", encoding="utf-8")
        _, output = self.run_cli("anchor", "show", "--screen", "level-up")
        self.assertIn("anatomy: complete", output)

    def test_missing_anchor_and_bad_inputs_fail_clearly(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("compare", "hero.png", "--screen", "nope")
        self.assertIn("No anchor registered", str(raised.exception))
        with self.assertRaises(SystemExit):
            self.run_cli("anchor", "add", "missing.png", "--screen", "hud")
        (self.root / "notes.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli("anchor", "add", "notes.txt", "--screen", "hud")
        with self.assertRaises(SystemExit):
            ui_ref_anchor.parse_viewport("wide")
        self.assertEqual(ui_ref_anchor.parse_viewport("1280x800"), (1280, 800))

    def test_browser_commands_explain_missing_extra(self) -> None:
        (self.root / "build.html").write_text("<p>hi</p>", encoding="utf-8")
        with mock.patch.object(ui_ref_anchor, "_with_page", side_effect=ui_ref_anchor.BrowserUnavailable("install the browser extra")):
            for command in (("shot", "build.html", "--out", "a.png"), ("audit", "build.html")):
                with self.assertRaises(SystemExit) as raised:
                    self.run_cli(*command)
                self.assertIn("install the browser extra", str(raised.exception))

    def test_audit_turns_raw_measurements_into_findings(self) -> None:
        raw = {
            "texts": 3, "small": [{"el": "div", "text": "HP", "size": 14}], "near": [], "contrast": [],
            "contrastUnknown": 2, "unsafe": [], "clipped": [], "targets": [], "interactive": 1, "focused": None,
            "pageOverflow": False, "viewport": [1920, 1080], "sizes": {"14": 1, "30": 2},
        }
        (self.root / "build.html").write_text("<p>hi</p>", encoding="utf-8")
        with mock.patch.object(ui_ref_anchor, "_with_page", return_value=raw):
            report = ui_ref_anchor.run_check("file:///x", "tv", (3840, 2160), 0, {})
            result, output = self.run_cli("audit", "build.html", "--platform", "tv")
        self.assertEqual(report["thresholds"]["minText"], 52)
        self.assertEqual({f["rule"] for f in report["failures"]}, {"text-size", "initial-focus"})
        self.assertTrue(any("over images" in line for line in report["not_assessed"]))
        self.assertEqual(result, 1)
        self.assertIn("FAIL text-size", output)
        self.assertIn("NOT ASSESSED", output)


if __name__ == "__main__":
    unittest.main()
