import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import ui_ref_cli
import ui_ref_design


class UiRefDesignPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.run_cli("init", "--project-name", "Test Game")
        self.run_cli("spec", "init", "--project-name", "Test Game", "--locale", "ko")
        self.design = self.root / "ui_design"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ui_ref_cli.main(["--project-root", str(self.root), *arguments])
        return result, output.getvalue()

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def save_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def make_complete_screen(self, screen_id: str = "main-menu") -> Path:
        self.run_cli("spec", "add-screen", "Main Menu", "--id", screen_id, "--wireframe")
        path = self.design / "screens" / f"{screen_id}.json"
        screen = self.load_json(path)
        screen.update(
            {
                "purpose": "Start a new run or leave the game.",
                "player_goal": "Start play without ambiguity.",
                "entry_conditions": [{"source": "boot", "condition": "menu_ready"}],
                "exit_exception": "Runtime destination is owned by the game-flow contract in this isolated fixture.",
                "edge_cases": ["Start is unavailable while save data is loading."],
                "evidence_exception": "Original interaction pattern; reference review pending.",
                "elements": [
                    {
                        "id": "A1",
                        "name": "Start",
                        "type": "button",
                        "rect": {"x": 720, "y": 420, "width": 480, "height": 96},
                        "text": "Start",
                        "ux_intent": "Make the safest primary action unmistakable without relying on color.",
                        "states": {
                            "default": {"visible": True},
                            "hover": {"outline": True},
                            "focused": {"focus_ring": True},
                            "pressed": {"scale": 0.98},
                            "selected": {"applicable": False, "reason": "The action is momentary."},
                            "disabled": {"reason": "Unavailable"},
                            "locked": {"applicable": False, "reason": "The main action is never progression-locked."},
                            "loading_entry": {"applicable": False, "reason": "Entry transition is screen-level."},
                            "loading_data": {"label": "Loading save data"},
                            "empty": {"applicable": False, "reason": "The action has no collection content."},
                            "error": {"label": "Could not load save data", "recovery": "Retry"},
                        },
                        "interactions": [{"input": "confirm", "action": "start_run", "devices": ["keyboard_mouse", "gamepad"]}],
                        "data_bindings": [{"path": "menu.can_start", "assumption": "UI proposal"}],
                        "accessibility": {"role": "button", "label": "Start game", "focus_order": 1, "non_color_cues": ["focus ring", "scale"]},
                        "acceptance": ["Given the menu is ready, when confirm is pressed, then start_run fires once."],
                        "reference_ids": [],
                    }
                ],
            }
        )
        self.save_json(path, screen)
        # Regenerate the deterministic source from the authored contract.
        self.run_cli("wireframe", "new", screen_id, "--force")
        return path

    def test_end_to_end_build_prototype_and_engine_handoff(self) -> None:
        self.make_complete_screen()
        for command in (
            ("spec", "validate", "--strict"),
            ("spec", "build"),
            ("prototype", "build"),
            ("export", "unity-uitoolkit"),
            ("export", "godot"),
            ("export", "unity-ugui"),
            ("export", "cocos"),
        ):
            with self.subTest(command=command):
                result, output = self.run_cli(*command)
                self.assertEqual(result, 0, output)

        self.assertTrue((self.design / "build" / "design.ir.json").is_file())
        self.assertTrue((self.design / "build" / "wireframes" / "main-menu.svg").is_file())
        prototype = (self.design / "build" / "prototype" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", prototype)
        self.assertIn("style-src 'self' 'unsafe-inline'", prototype)
        self.assertIn("--aspect:", prototype)
        self.assertIn("calc(78vh * var(--aspect))", (self.design / "build" / "prototype" / "prototype.css").read_text(encoding="utf-8"))
        self.assertNotIn("<script>", prototype)
        self.assertTrue((self.design / "build" / "exports" / "unity-uitoolkit" / "main-menu.uxml").is_file())
        self.assertTrue((self.design / "build" / "exports" / "godot" / "main-menu.tscn").is_file())

    def test_absolute_contract_geometry_becomes_parent_local_in_hierarchical_exports(self) -> None:
        path = self.make_complete_screen()
        screen = self.load_json(path)
        screen["elements"].insert(
            0,
            {
                "id": "P1",
                "name": "Menu Panel",
                "type": "panel",
                "rect": {"x": 700, "y": 400, "width": 600, "height": 300},
                "ux_intent": "Group the primary menu action.",
                "states": {"default": {"visible": True}},
                "interactions": [],
                "data_bindings": [],
                "accessibility": {"role": "group", "label": "Main actions"},
                "acceptance": [],
                "reference_ids": [],
            },
        )
        screen["elements"][1]["parent"] = "P1"
        screen["elements"][1]["rect"] = {"x": 750, "y": 450, "width": 480, "height": 96}
        self.save_json(path, screen)
        result, output = self.run_cli("wireframe", "new", "main-menu", "--force")
        self.assertEqual(result, 0, output)
        wire = (self.design / "wireframes" / "main-menu.uiwire").read_text(encoding="utf-8")
        self.assertIn("button A1 x=50 y=50", wire)
        self.assertIn("parent=P1", wire)

        result, output = self.run_cli("export", "unity-uitoolkit")
        self.assertEqual(result, 0, output)
        result, output = self.run_cli("export", "godot")
        self.assertEqual(result, 0, output)
        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 0, output)
        uxml = (self.design / "build" / "exports" / "unity-uitoolkit" / "main-menu.uxml").read_text(encoding="utf-8")
        godot = (self.design / "build" / "exports" / "godot" / "main-menu.tscn").read_text(encoding="utf-8")
        prototype = (self.design / "build" / "prototype" / "index.html").read_text(encoding="utf-8")
        self.assertIn("left:50.0px;top:50.0px", uxml)
        self.assertIn('parent="P1"', godot)
        self.assertIn("offset_left = 50.0", godot)
        self.assertLess(prototype.index('data-element="P1"'), prototype.index('data-element="A1"'))
        self.assertIn("--z:1", prototype)

    def test_conditional_elements_are_hidden_in_default_wireframe_and_switchable_in_prototype(self) -> None:
        path = self.make_complete_screen()
        screen = self.load_json(path)
        screen["elements"].extend(
            [
                {
                    "id": "M1",
                    "name": "Confirmation modal",
                    "type": "panel",
                    "rect": {"x": 560, "y": 280, "width": 800, "height": 520},
                    "states": {
                        "default": {"applicable": False, "reason": "Closed at rest."},
                        "open": {"applicable": True, "description": "Visible with a scrim."},
                    },
                    "interactions": [],
                    "data_bindings": [],
                    "accessibility": {"label": "Confirmation"},
                    "acceptance": [],
                    "reference_ids": [],
                },
                {
                    "id": "M1T",
                    "name": "Confirmation copy",
                    "type": "text",
                    "parent": "M1",
                    "rect": {"x": 620, "y": 340, "width": 680, "height": 120},
                    "states": {"default": {"applicable": True}},
                    "interactions": [],
                    "data_bindings": [],
                    "accessibility": {"label": "Confirmation copy"},
                    "acceptance": [],
                    "reference_ids": [],
                },
            ]
        )
        self.save_json(path, screen)

        result, output = self.run_cli("wireframe", "new", "main-menu", "--force")
        self.assertEqual(result, 0, output)
        wire = (self.design / "wireframes" / "main-menu.uiwire").read_text(encoding="utf-8")
        self.assertNotIn(" M1 ", wire)
        self.assertNotIn(" M1T ", wire)

        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 0, output)
        prototype_root = self.design / "build" / "prototype"
        prototype = (prototype_root / "index.html").read_text(encoding="utf-8")
        script = (prototype_root / "prototype.js").read_text(encoding="utf-8")
        self.assertIn('data-element="M1"', prototype)
        self.assertIn('value="open"', prototype)
        self.assertIn('&quot;default&quot;:false', prototype)
        self.assertIn('data-component-id=', prototype)
        self.assertIn("applyScenario", script)
        self.assertIn("element.hidden = !visible", script)
        self.assertIn("activeModal", script)
        self.assertIn("element.inert = routeUnavailable || suppressed", script)
        self.assertIn(":not([inert])", script)
        self.assertIn("baseScenario", script)
        self.assertIn("previousScenario", script)

    def test_default_scenario_and_rect_overrides_drive_wireframe_prototype_and_export(self) -> None:
        path = self.make_complete_screen()
        screen = self.load_json(path)
        screen["default_scenario"] = "expanded"
        screen["elements"][0]["states"]["expanded"] = {"applicable": True, "description": "Expanded layout."}
        screen["elements"][0]["rect_overrides"] = {
            "expanded": {"x": 300, "y": 240, "width": 900, "height": 180}
        }
        self.save_json(path, screen)

        result, output = self.run_cli("wireframe", "new", "main-menu", "--force")
        self.assertEqual(result, 0, output)
        wire = (self.design / "wireframes" / "main-menu.uiwire").read_text(encoding="utf-8")
        self.assertIn("x=300 y=240 w=900 h=180", wire)

        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 0, output)
        prototype = (self.design / "build" / "prototype" / "index.html").read_text(encoding="utf-8")
        self.assertIn('value="expanded" selected', prototype)
        self.assertIn('data-scenario="expanded"', prototype)
        self.assertIn('data-rect-map=', prototype)

        result, output = self.run_cli("export", "unity-ugui")
        self.assertEqual(result, 0, output)
        manifest = self.load_json(self.design / "build" / "exports" / "unity-ugui" / "main-menu.ugui.json")
        self.assertEqual(manifest["hierarchy"][0]["rectOverrides"]["expanded"]["x"], 300)

    def test_validation_rejects_unknown_default_transition_and_flow_scenarios(self) -> None:
        main_path = self.make_complete_screen("main-menu")
        options_path = self.make_complete_screen("options")
        options = self.load_json(options_path)
        options["default_scenario"] = "missing"
        self.save_json(options_path, options)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("scenario.unknown_default", output)

        options["elements"][0]["states"]["open"] = {"applicable": True, "description": "Open state."}
        options["default_scenario"] = "open"
        self.save_json(options_path, options)
        main = self.load_json(main_path)
        main["elements"][0]["interactions"][0].update({"target_screen": "options", "target_scenario": "missing"})
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("interaction.unknown_target_scenario", output)

        main["elements"][0]["interactions"][0]["target_scenario"] = "open"
        main["elements"][0]["interactions"][0]["target_scenario_by_mode"] = {"online": "missing"}
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("interaction.unknown_target_scenario", output)

        main["elements"][0]["interactions"][0]["target_scenario_by_mode"] = {"online": "open", "local_demo": "open"}
        self.save_json(main_path, main)
        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 0, output)
        prototype_root = self.design / "build" / "prototype"
        self.assertIn("data-target-scenario-by-mode=", (prototype_root / "index.html").read_text(encoding="utf-8"))
        self.assertIn("target_scenario_by_mode", (prototype_root / "prototype.js").read_text(encoding="utf-8"))

        flows = self.load_json(self.design / "flows.json")
        flows["flows"] = [{
            "id": "open-options",
            "entry_screen": "main-menu",
            "steps": [{"screen": "main-menu", "action": "start_run", "next_screen": "options", "target_scenario": "missing"}],
        }]
        self.save_json(self.design / "flows.json", flows)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("flow.unknown_target_scenario", output)

    def test_transition_scenarios_match_prototype_scenarios_and_require_a_target(self) -> None:
        main_path = self.make_complete_screen("main-menu")
        options_path = self.make_complete_screen("options")
        options = self.load_json(options_path)
        options["elements"][0]["states"]["open"] = {"applicable": True, "description": "Open state."}
        options["elements"][0]["rect_overrides"] = {"layout_only": {"x": 300}}
        self.save_json(options_path, options)

        main = self.load_json(main_path)
        interaction = main["elements"][0]["interactions"][0]
        interaction["target_scenario"] = "open"
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("target_scenario requires target_screen", output)

        interaction["target_screen"] = "options"
        interaction["target_scenario"] = "hover"
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("interaction.unknown_target_scenario", output)

        interaction["target_scenario"] = "layout_only"
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("interaction.unknown_target_scenario", output)

        interaction["target_scenario"] = "open"
        interaction["source_scenarios"] = ["missing"]
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("interaction.unknown_source_scenario", output)

        interaction["source_scenarios"] = ["default"]
        interaction["source_modes"] = ["offline"]
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("interaction.source_modes", output)

    def test_contract_id_is_portable_and_matches_its_filename(self) -> None:
        path = self.make_complete_screen()
        screen = self.load_json(path)
        screen["id"] = "Main_Menu"
        self.save_json(path, screen)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("screen.id", output)

        result, output = self.run_cli("spec", "add-screen", "설정 화면")
        self.assertEqual(result, 0, output)
        generated = [item for item in (self.design / "screens").glob("screen-*.json")]
        self.assertEqual(len(generated), 1)
        self.assertRegex(generated[0].stem, r"^screen-[0-9a-f]{8}$")

    def test_explicit_config_controls_the_design_workspace(self) -> None:
        custom_config = self.root / "custom-ui-ref.json"
        self.save_json(custom_config, {"design_workspace": "custom-design"})
        result, output = self.run_cli("--config", str(custom_config), "spec", "init", "--project-name", "Configured Game")
        self.assertEqual(result, 0, output)
        self.assertTrue((self.root / "custom-design" / "project.json").is_file())

    def test_generated_spec_and_prototype_keep_flows_tokens_and_components_traceable(self) -> None:
        main_path = self.make_complete_screen("main-menu")
        self.make_complete_screen("options")
        main = self.load_json(main_path)
        main.pop("exit_exception", None)
        main["exit_paths"] = [{"action": "open_options", "target_screen": "options"}]
        main["elements"][0]["interactions"][0]["target_screen"] = "options"
        self.save_json(main_path, main)
        self.run_cli("wireframe", "new", "main-menu", "--force")

        flows_path = self.design / "flows.json"
        flows = self.load_json(flows_path)
        flows["flows"] = [{
            "id": "menu-flow",
            "entry_screen": "main-menu",
            "steps": [{"screen": "main-menu", "action": "open_options", "next_screen": "options", "recovery": "return to main-menu"}],
        }]
        self.save_json(flows_path, flows)

        self.run_cli("spec", "add-component", "Primary Button", "--id", "primary-button")
        component_path = self.design / "components" / "primary-button.json"
        component = self.load_json(component_path)
        component["purpose"] = "Provide a consistent primary action treatment."
        component["interactive"] = True
        component["inputs"] = [{"input": "confirm", "action": "activate", "devices": ["keyboard_mouse", "gamepad"]}]
        component["accessibility"] = {"role": "button", "label_template": "{label}", "non_color_cues": ["focus ring"]}
        component["acceptance"] = [{"given": "the action is focused", "when": "confirm is pressed", "then": "activate fires once"}]
        self.save_json(component_path, component)

        result, output = self.run_cli("spec", "build")
        self.assertEqual(result, 0, output)
        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 0, output)
        markdown = (self.design / "build" / "design-spec.md").read_text(encoding="utf-8")
        prototype = (self.design / "build" / "prototype" / "index.html").read_text(encoding="utf-8")
        self.assertIn("## Design tokens", markdown)
        self.assertIn("color.accent.primary", markdown)
        self.assertIn("### Flow `menu-flow`", markdown)
        self.assertIn("### Primary Button (`primary-button`)", markdown)
        self.assertIn('data-target="options"', prototype)

    def test_flows_json_alone_drives_prototype_navigation_and_entry(self) -> None:
        self.make_complete_screen("main-menu")
        self.make_complete_screen("options")
        flows = self.load_json(self.design / "flows.json")
        flows["flows"] = [{
            "id": "menu-flow",
            "entry_screen": "main-menu",
            "steps": [{"screen": "main-menu", "action": "open_options", "next_screen": "options"}],
        }]
        self.save_json(self.design / "flows.json", flows)

        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 0, output)
        prototype_root = self.design / "build" / "prototype"
        prototype = (prototype_root / "index.html").read_text(encoding="utf-8")
        manifest = self.load_json(prototype_root / "prototype-manifest.json")
        self.assertIn('data-flow-id="menu-flow"', prototype)
        self.assertIn('data-entry-screen="main-menu"', prototype)
        self.assertEqual(manifest["entry_screen"], "main-menu")
        self.assertEqual(manifest["flows"], ["menu-flow"])

        main_path = self.design / "screens" / "main-menu.json"
        main = self.load_json(main_path)
        main["elements"][0]["interactions"][0]["action"] = "open_options"
        main["elements"][0]["interactions"][0]["target_screen"] = "main-menu"
        self.save_json(main_path, main)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("flow.conflict", output)

    def test_prototype_flow_helpers_reuse_source_visibility_and_preserve_route_context(self) -> None:
        main_path = self.make_complete_screen("main-menu")
        room_path = self.make_complete_screen("room")
        result_path = self.make_complete_screen("result")

        main = self.load_json(main_path)
        main.pop("exit_exception", None)
        main["exit_paths"] = [{"action": "start_run", "target_screen": "room"}]
        main["elements"][0]["states"]["local_demo"] = {"applicable": False, "reason": "Online-only action."}
        main["elements"][0]["interactions"][0]["target_screen"] = "room"
        self.save_json(main_path, main)

        room = self.load_json(room_path)
        room["default_scenario"] = "host"
        room["elements"][0]["states"]["host"] = {"applicable": True, "description": "Host fixture."}
        room.pop("exit_exception", None)
        room["exit_paths"] = [{"action": "show_result", "target_screen": "result"}]
        self.save_json(room_path, room)

        result = self.load_json(result_path)
        result["elements"][0]["states"]["host_result"] = {"applicable": True, "description": "Host result fixture."}
        self.save_json(result_path, result)

        flows = self.load_json(self.design / "flows.json")
        flows["flows"] = [{
            "id": "host-result",
            "entry_screen": "main-menu",
            "steps": [
                {"screen": "main-menu", "action": "start_run", "next_screen": "room", "target_scenario": "host"},
                {"screen": "room", "action": "show_result", "next_screen": "result", "target_scenario": "host_result"},
            ],
        }]
        self.save_json(self.design / "flows.json", flows)

        result_code, output = self.run_cli("prototype", "build")
        self.assertEqual(result_code, 0, output)
        prototype_root = self.design / "build" / "prototype"
        html_text = (prototype_root / "index.html").read_text(encoding="utf-8")
        js_text = (prototype_root / "prototype.js").read_text(encoding="utf-8")
        self.assertIn("_source_element", html_text)
        self.assertIn("_source_contexts", html_text)
        self.assertIn("sourceElementAvailable", js_text)
        self.assertIn("dataset.sourceScenario", js_text)
        self.assertIn("interaction.restore_history", js_text)

    def test_ordered_flow_must_start_at_entry_and_remain_connected(self) -> None:
        self.make_complete_screen("main-menu")
        self.make_complete_screen("options")
        flows = self.load_json(self.design / "flows.json")
        flows["flows"] = [{
            "id": "menu-flow",
            "entry_screen": "main-menu",
            "steps": [{"screen": "options", "action": "close", "next_screen": "main-menu"}],
        }]
        self.save_json(self.design / "flows.json", flows)

        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("flow.disconnected", output)
        result, output = self.run_cli("prototype", "build")
        self.assertEqual(result, 1)
        self.assertIn("flow.disconnected", output)

    def test_review_gate_rejects_empty_starter_contract(self) -> None:
        self.run_cli("spec", "add-screen", "Empty", "--id", "empty")
        result, output = self.run_cli("spec", "promote", "screen", "empty", "--to", "reviewed", "--by", "AI reviewer", "--note", "first pass")
        self.assertEqual(result, 1)
        self.assertIn("screen.purpose", output)
        self.assertEqual(self.load_json(self.design / "screens" / "empty.json")["status"], "draft")

    def test_invalid_quality_gate_type_cannot_bypass_promotion(self) -> None:
        path = self.make_complete_screen()
        project_path = self.design / "project.json"
        project = self.load_json(project_path)
        project["quality_gates"]["approved_requires_accessibility"] = "false"
        self.save_json(project_path, project)
        screen = self.load_json(path)
        screen["elements"][0]["accessibility"].pop("label")
        screen["elements"][0]["accessibility"].pop("non_color_cues")
        self.save_json(path, screen)

        result, output = self.run_cli(
            "spec", "promote", "screen", "main-menu", "--to", "reviewed",
            "--by", "Reviewer", "--note", "must not bypass gates",
        )
        self.assertEqual(result, 1)
        self.assertIn("quality_gates.boolean", output)
        self.assertEqual(self.load_json(path)["status"], "draft")
        self.assertEqual(self.load_json(self.design / "approvals.json")["approvals"], [])

    def test_unknown_quality_gate_key_is_rejected(self) -> None:
        self.make_complete_screen()
        project_path = self.design / "project.json"
        project = self.load_json(project_path)
        project["quality_gates"]["approved_requires_accessiblity"] = True
        self.save_json(project_path, project)

        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("quality_gates.unknown", output)

    def test_interactive_component_requires_actionable_input_mapping(self) -> None:
        self.run_cli("spec", "add-component", "Primary Button", "--id", "primary-button")
        path = self.design / "components" / "primary-button.json"
        component = self.load_json(path)
        component["purpose"] = "Provide the primary action consistently."
        component["interactive"] = True
        component["inputs"] = [{"devices": ["keyboard_mouse", "gamepad"]}]
        component["accessibility"] = {"role": "button", "non_color_cues": ["focus ring"]}
        component["acceptance"] = [{"given": "focused", "when": "activated", "then": "the action runs once"}]
        self.save_json(path, component)

        result, output = self.run_cli(
            "spec", "promote", "component", "primary-button", "--to", "reviewed",
            "--by", "Reviewer", "--note", "input contract check",
        )
        self.assertEqual(result, 1)
        self.assertIn("component.input.incomplete", output)
        self.assertEqual(self.load_json(path)["status"], "draft")

        result, output = self.run_cli("spec", "validate", "--strict")
        self.assertEqual(result, 1)
        self.assertIn("component.input.incomplete", output)

    def test_force_creation_cannot_erase_reviewed_contract_history(self) -> None:
        path = self.make_complete_screen()
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Reviewer", "--note", "reviewed")
        self.assertEqual(result, 0, output)
        before = path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "unreviewed draft"):
            self.run_cli("spec", "add-screen", "Replacement", "--id", "main-menu", "--force")
        self.assertEqual(path.read_bytes(), before)

        self.run_cli("spec", "add-component", "Primary Button", "--id", "primary-button")
        component_path = self.design / "components" / "primary-button.json"
        component = self.load_json(component_path)
        component["purpose"] = "Reusable primary action."
        component["accessibility"] = {"role": "button", "non_color_cues": ["focus ring"]}
        component["acceptance"] = [{"given": "it is visible", "when": "it is rendered", "then": "its label is readable"}]
        self.save_json(component_path, component)
        result, output = self.run_cli("spec", "promote", "component", "primary-button", "--to", "reviewed", "--by", "Reviewer", "--note", "reviewed")
        self.assertEqual(result, 0, output)
        before_component = component_path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "unreviewed draft"):
            self.run_cli("spec", "add-component", "Replacement", "--id", "primary-button", "--force")
        self.assertEqual(component_path.read_bytes(), before_component)

    def test_unknown_component_and_configured_open_question_gate_block_review(self) -> None:
        path = self.make_complete_screen()
        screen = self.load_json(path)
        screen["elements"][0]["component_id"] = "does-not-exist"
        self.save_json(path, screen)
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Reviewer", "--note", "review")
        self.assertEqual(result, 1)
        self.assertIn("component.unknown", output)

        screen["elements"][0].pop("component_id")
        screen["open_questions"] = ["Which animation curve should ship?"]
        self.save_json(path, screen)
        project = self.load_json(self.design / "project.json")
        project["quality_gates"]["approved_requires_no_open_questions"] = True
        self.save_json(self.design / "project.json", project)
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Reviewer", "--note", "review")
        self.assertEqual(result, 1)
        self.assertIn("questions.open", output)

    def test_corrupt_lifecycle_ledger_cannot_partially_change_contract(self) -> None:
        path = self.make_complete_screen()
        before = path.read_bytes()
        (self.design / "approvals.json").write_text("{broken", encoding="utf-8")
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Reviewer", "--note", "review")
        self.assertEqual(result, 1)
        self.assertIn("no files were changed", output)
        self.assertEqual(path.read_bytes(), before)

    def test_human_approval_is_hash_bound_and_dependency_changes_make_it_stale(self) -> None:
        path = self.make_complete_screen()
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Spec Agent", "--note", "contract complete")
        self.assertEqual(result, 0, output)
        with self.assertRaisesRegex(SystemExit, "--by must name"):
            self.run_cli("spec", "promote", "screen", "main-menu", "--to", "approved", "--by", "", "--note", "approved", "--human-confirmed")
        with self.assertRaisesRegex(SystemExit, "--note must explain"):
            self.run_cli("spec", "promote", "screen", "main-menu", "--to", "approved", "--by", "Lead", "--note", "", "--human-confirmed")
        self.assertEqual(self.load_json(path)["status"], "reviewed")
        with self.assertRaisesRegex(SystemExit, "Final approval is human-owned"):
            self.run_cli("spec", "promote", "screen", "main-menu", "--to", "approved", "--by", "Lead", "--note", "approved")
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "approved", "--by", "Lead", "--note", "approved", "--human-confirmed")
        self.assertEqual(result, 0, output)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 0, output)

        tokens = self.load_json(self.design / "tokens.json")
        tokens["spacing"]["md"] = 20
        self.save_json(self.design / "tokens.json", tokens)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("approval.stale_dependency", output)
        self.assertEqual(self.load_json(path)["status"], "approved")

    def test_uiwire_parser_rejects_unknown_parent_and_escapes_labels(self) -> None:
        invalid = "uiwire 1\ncanvas 1920 1080\nbutton A1 x=10 y=10 w=100 h=50 parent=missing label=Start\n"
        with self.assertRaisesRegex(ValueError, "parent 'missing' does not exist"):
            ui_ref_design._node_rects(ui_ref_design.parse_uiwire(invalid))

        source = 'uiwire 1\ncanvas 1920 1080\nbutton A1 x=10 y=10 w=100 h=50 label="<Start & Go>"\ncallout A1 side=right text="<unsafe>"\n'
        svg = ui_ref_design.render_uiwire_svg(ui_ref_design.parse_uiwire(source))
        self.assertIn("&lt;Start &amp;", svg)
        self.assertIn("Go&gt;", svg)
        self.assertNotIn("<unsafe>", svg)

        long_callout = "가" * 120
        long_source = f'uiwire 1\ncanvas 100 100\nrect A1 x=10 y=10 w=20 h=20 label=Box\ncallout A1 side=right text="{long_callout}"\n'
        long_svg = ui_ref_design.render_uiwire_svg(ui_ref_design.parse_uiwire(long_source))
        self.assertGreaterEqual(long_svg.count("<tspan"), 6)
        self.assertIn("가" * 10, long_svg)

        many_top = "uiwire 1\ncanvas 100 100\nrect A1 x=10 y=10 w=20 h=20 label=Box\n" + "".join(
            f'callout A1 side=top text="Callout {index}"\n' for index in range(6)
        )
        wide_svg = ui_ref_design.render_uiwire_svg(ui_ref_design.parse_uiwire(many_top))
        view_x, _, view_width, _ = map(float, wide_svg.split('viewBox="', 1)[1].split('"', 1)[0].split())
        self.assertGreaterEqual(view_x + view_width, 30 + 6 * 540)

        long_top_source = f'uiwire 1\ncanvas 100 100\nrect A1 x=10 y=10 w=20 h=20 label=Box\ncallout A1 side=top text="{long_callout}"\n'
        long_top_svg = ui_ref_design.render_uiwire_svg(ui_ref_design.parse_uiwire(long_top_source))
        _, view_top, _, _ = map(float, long_top_svg.split('viewBox="', 1)[1].split('"', 1)[0].split())
        self.assertLessEqual(view_top, -132)
        self.assertIn('y="-108.0"', long_top_svg)

        for malformed, expected in (
            ("uiwire 1\ncanvas 100 100\nrect A1 x=nan y=0 w=10 h=10\n", "must be finite"),
            ("uiwire 1\ncanvas 100 100\nrect A1 x=95 y=0 w=10 h=10\n", "outside"),
            ("uiwire 1\ncanvas 100 100\nrect A1 x=0 y=0 w=10 h=10 typo=1\n", "unknown rect attribute"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    document = ui_ref_design.parse_uiwire(malformed)
                    ui_ref_design._node_rects(document)

    def test_release_outputs_reject_unapproved_contracts(self) -> None:
        self.make_complete_screen()
        for command in (("prototype", "build", "--release"), ("export", "godot", "--release")):
            with self.subTest(command=command):
                result, output = self.run_cli(*command)
                self.assertEqual(result, 1)
                self.assertIn("release", output.lower())

    def test_release_outputs_reject_empty_workspace(self) -> None:
        for command in (("prototype", "build", "--release"), ("export", "godot", "--release")):
            with self.subTest(command=command):
                result, output = self.run_cli(*command)
                self.assertEqual(result, 1)
                self.assertIn("at least one approved screen", output)

    def test_generated_directory_refuses_to_replace_user_file(self) -> None:
        self.make_complete_screen()
        output = self.design / "build" / "prototype"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("USER DATA", encoding="utf-8")

        result, message = self.run_cli("prototype", "build")
        self.assertEqual(result, 1)
        self.assertIn("non-directory output path", message)
        self.assertTrue(output.is_file())
        self.assertEqual(output.read_text(encoding="utf-8"), "USER DATA")
        self.assertEqual(list(output.parent.glob(".prototype.backup-*")), [])

        explicit = self.root / "custom-output"
        explicit.write_text("MORE USER DATA", encoding="utf-8")
        result, message = self.run_cli("prototype", "build", "--output", str(explicit), "--force")
        self.assertEqual(result, 1)
        self.assertIn("non-directory output path", message)
        self.assertEqual(explicit.read_text(encoding="utf-8"), "MORE USER DATA")

        build_output = self.root / "custom-build-output"
        build_output.write_text("BUILD USER DATA", encoding="utf-8")
        result, message = self.run_cli("spec", "build", "--output", str(build_output), "--force")
        self.assertEqual(result, 1)
        self.assertIn("non-directory build output path", message)
        self.assertEqual(build_output.read_text(encoding="utf-8"), "BUILD USER DATA")

        capture = self.root / "capture.png"
        capture.write_bytes(b"analysis-input")
        analysis_output = self.root / "custom-analysis-output"
        analysis_output.write_text("ANALYSIS USER DATA", encoding="utf-8")
        result, message = self.run_cli("analyze", "media", str(capture), "--output", str(analysis_output), "--force")
        self.assertEqual(result, 1)
        self.assertIn("non-directory analysis output path", message)
        self.assertEqual(analysis_output.read_text(encoding="utf-8"), "ANALYSIS USER DATA")

    def test_malformed_document_shapes_return_validation_errors(self) -> None:
        project_path = self.design / "project.json"
        valid_project = self.load_json(project_path)
        project_path.write_text("[]\n", encoding="utf-8")
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("project.not_object", output)

        self.save_json(project_path, valid_project)
        flows_path = self.design / "flows.json"
        flows = self.load_json(flows_path)
        flows["flows"] = [{"id": ["not", "hashable"], "entry_screen": "missing", "steps": []}]
        self.save_json(flows_path, flows)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("flow.id", output)

    def test_reviewed_contract_remains_under_strict_completeness_checks(self) -> None:
        path = self.make_complete_screen()
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Reviewer", "--note", "complete")
        self.assertEqual(result, 0, output)
        contract = self.load_json(path)
        contract["purpose"] = ""
        self.save_json(path, contract)
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("screen.purpose", output)

    def test_check_fails_for_changed_generated_output_and_new_source(self) -> None:
        self.make_complete_screen()
        result, output = self.run_cli("spec", "build")
        self.assertEqual(result, 0, output)
        result, output = self.run_cli("spec", "check")
        self.assertEqual(result, 0, output)

        wireframe = self.design / "wireframes" / "main-menu.uiwire"
        wireframe.write_text(wireframe.read_text(encoding="utf-8").replace("x=720", "x=721"), encoding="utf-8")
        result, output = self.run_cli("spec", "check")
        self.assertEqual(result, 1)
        self.assertIn("contract geometry/type drift", output)
        self.run_cli("wireframe", "new", "main-menu", "--force")
        self.run_cli("spec", "build")

        generated = self.design / "build" / "design-spec.md"
        generated.write_text(generated.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")
        result, output = self.run_cli("spec", "check")
        self.assertEqual(result, 1)
        report = self.load_json(self.design / "build" / "check-report.json")
        self.assertIn("design-spec.md", report["build_drift"]["changed_outputs"])

        self.run_cli("spec", "build")
        self.run_cli("spec", "add-component", "New Component", "--id", "new-component")
        result, output = self.run_cli("spec", "check")
        self.assertEqual(result, 1)
        report = self.load_json(self.design / "build" / "check-report.json")
        self.assertIn("components/new-component.json", report["build_drift"]["stale_sources"])

    def test_contract_owned_wireframe_path_cannot_escape_workspace(self) -> None:
        path = self.make_complete_screen()
        contract = self.load_json(path)
        contract["wireframe"] = "../../escape.uiwire"
        self.save_json(path, contract)
        with self.assertRaisesRegex(SystemExit, "inside the design workspace"):
            self.run_cli("wireframe", "new", "main-menu", "--force")

    def test_analysis_numeric_limits_fail_before_media_processing(self) -> None:
        with self.assertRaisesRegex(SystemExit, "--interval"):
            self.run_cli("analyze", "media", "missing.mp4", "--interval", "0")
        with self.assertRaisesRegex(SystemExit, "--frame-limit"):
            self.run_cli("analyze", "media", "missing.mp4", "--frame-limit", "0")

    def test_analysis_import_is_bound_to_exact_packet_and_stays_draft(self) -> None:
        capture = self.root / "capture.png"
        capture_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (1920).to_bytes(4, "big") + (1080).to_bytes(4, "big")
        capture.write_bytes(capture_bytes)
        run = self.root / "analysis-run"
        result, output = self.run_cli("analyze", "media", str(capture), "--output", str(run))
        self.assertEqual(result, 0, output)
        packet_path = run / "analysis-packet.json"
        packet = self.load_json(packet_path)
        result_path = self.root / "analysis-result.json"
        analyzed = {
            "analysis_schema_version": "1.0",
            "provider": "fixture",
            "model": "vision-test",
            "prompt_version": packet["prompt_version"],
            "input_sha256": "0" * 64,
            "screens": [
                {
                    "id": "observed-menu",
                    "name": "Observed Menu",
                    "purpose": "Observed menu layout",
                    "player_goal": "Unknown",
                    "evidence_ids": ["evidence-0001"],
                    "claims": [{"classification": "observed", "claim": "A central panel is visible", "confidence": 1.0, "evidence_ids": ["evidence-0001"]}],
                    "elements": [{"id": "A1", "name": "Panel", "type": "panel", "rect": {"x": 100, "y": 100, "width": 800, "height": 600}, "states": {"default": {"visible": True}}, "data_bindings": [], "interactions": [], "accessibility": {}, "acceptance": []}],
                }
            ],
        }
        self.save_json(result_path, analyzed)
        result, output = self.run_cli("analyze", "import", str(result_path), "--packet", str(packet_path))
        self.assertEqual(result, 1)
        self.assertIn("input_sha256", output)

        analyzed["input_sha256"] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
        self.save_json(result_path, analyzed)
        capture.write_bytes(capture_bytes + b"changed-after-analysis")
        result, output = self.run_cli("analyze", "import", str(result_path), "--packet", str(packet_path))
        self.assertEqual(result, 1)
        self.assertIn("no longer matches the evidence file", output)

        capture.write_bytes(capture_bytes)
        result, output = self.run_cli("analyze", "import", str(result_path), "--packet", str(packet_path))
        self.assertEqual(result, 0, output)
        imported = self.load_json(self.design / "screens" / "observed-menu.json")
        self.assertEqual(imported["status"], "draft")
        self.assertEqual(imported["provenance"]["analysis"]["input_sha256"], analyzed["input_sha256"])

        imported["status"] = "reviewed"
        imported["review_history"] = [{"from": "draft", "to": "reviewed"}]
        imported_path = self.design / "screens" / "observed-menu.json"
        self.save_json(imported_path, imported)
        before = imported_path.read_bytes()
        result, output = self.run_cli("analyze", "import", str(result_path), "--packet", str(packet_path), "--force")
        self.assertEqual(result, 1)
        self.assertIn("unreviewed draft", output)
        self.assertEqual(imported_path.read_bytes(), before)

    def test_analysis_import_is_atomic_when_a_later_screen_is_invalid(self) -> None:
        evidence = self.root / "atomic-evidence.png"
        evidence.write_bytes(b"atomic-evidence")
        packet_path = self.root / "atomic-packet.json"
        packet = {
            "analysis_schema_version": "1.0",
            "run_id": "atomic-run",
            "generated_at": "2026-01-01T00:00:00Z",
            "prompt_version": "reverse-engineer/1.0",
            "evidence": [{
                "id": "evidence-0001", "path": str(evidence),
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                "width": 1920, "height": 1080,
            }],
        }
        self.save_json(packet_path, packet)

        def element(element_id: str, parent: str | None = None) -> dict:
            value = {
                "id": element_id, "name": element_id, "type": "panel",
                "rect": {"x": 100, "y": 100, "width": 400, "height": 300},
                "states": {"default": {"visible": True}}, "data_bindings": [],
                "interactions": [], "accessibility": {}, "acceptance": [],
                "reference_ids": ["evidence-0001"],
            }
            if parent:
                value["parent"] = parent
            return value

        result_path = self.root / "atomic-result.json"
        result_doc = {
            "analysis_schema_version": "1.0", "provider": "fixture", "model": "vision-test",
            "prompt_version": packet["prompt_version"],
            "input_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
            "screens": [
                {"id": "first", "name": "First", "evidence_ids": ["evidence-0001"], "claims": [], "elements": [element("A1")]},
                {"id": "second", "name": "Second", "evidence_ids": ["evidence-0001"], "claims": [], "elements": [element("B1", "MISSING")]},
            ],
        }
        self.save_json(result_path, result_doc)
        refs_before = (self.design / "references.json").read_bytes()

        result, output = self.run_cli("analyze", "import", str(result_path), "--packet", str(packet_path))
        self.assertEqual(result, 1)
        self.assertIn("element.parent", output)
        self.assertEqual((self.design / "references.json").read_bytes(), refs_before)
        self.assertEqual(list((self.design / "screens").glob("*.json")), [])
        self.assertEqual(list((self.design / "wireframes").glob("*.uiwire")), [])

    def test_analysis_reference_identity_cannot_alias_different_packets(self) -> None:
        created_ref_ids: list[str] = []
        for index in (1, 2):
            evidence = self.root / f"collision-{index}.png"
            evidence.write_bytes(f"different-evidence-{index}".encode())
            packet_path = self.root / f"collision-packet-{index}.json"
            packet = {
                "analysis_schema_version": "1.0", "run_id": "same-run",
                "generated_at": "2026-01-01T00:00:00Z", "prompt_version": "reverse-engineer/1.0",
                "evidence": [{
                    "id": "evidence-0001", "path": str(evidence),
                    "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    "width": 1920, "height": 1080,
                }],
            }
            self.save_json(packet_path, packet)
            screen_id = f"screen-{index}"
            result_path = self.root / f"collision-result-{index}.json"
            result_doc = {
                "analysis_schema_version": "1.0", "provider": "fixture", "model": "vision-test",
                "prompt_version": packet["prompt_version"],
                "input_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                "screens": [{
                    "id": screen_id, "name": screen_id, "evidence_ids": ["evidence-0001"], "claims": [],
                    "elements": [{
                        "id": "A1", "name": "Panel", "type": "panel",
                        "rect": {"x": 100, "y": 100, "width": 400, "height": 300},
                        "states": {"default": {"visible": True}}, "data_bindings": [], "interactions": [],
                        "accessibility": {}, "acceptance": [], "reference_ids": ["evidence-0001"],
                    }],
                }],
            }
            self.save_json(result_path, result_doc)
            result, output = self.run_cli("analyze", "import", str(result_path), "--packet", str(packet_path))
            self.assertEqual(result, 0, output)
            imported = self.load_json(self.design / "screens" / f"{screen_id}.json")
            created_ref_ids.append(imported["reference_ids"][0])

        self.assertNotEqual(created_ref_ids[0], created_ref_ids[1])
        refs = self.load_json(self.design / "references.json")["sources"]
        self.assertEqual(len(refs), 2)
        by_id = {item["id"]: item for item in refs}
        self.assertEqual(by_id[created_ref_ids[0]]["uri"], str(self.root / "collision-1.png"))
        self.assertEqual(by_id[created_ref_ids[1]]["uri"], str(self.root / "collision-2.png"))

    def test_reference_manifest_cannot_make_importer_read_outside_project(self) -> None:
        manifest = self.root / "ui_research" / "manifests" / "local_ui_refs_manifest.json"
        self.save_json(
            manifest,
            {
                "generated_at": "2026-01-01T00:00:00Z",
                "items": [{"path": "../outside.png", "filename": "outside.png", "collection": "bad", "category": "bad", "tags": []}],
            },
        )
        result, output = self.run_cli("spec", "import-references")
        self.assertEqual(result, 0, output)
        source = self.load_json(self.design / "references.json")["sources"][0]
        self.assertEqual(source["sync_state"], "invalid_path")
        self.assertEqual(source["sha256"], "")
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("reference.path_escape", output)

    def test_unsupported_reference_type_cannot_satisfy_evidence_gate(self) -> None:
        path = self.make_complete_screen()
        refs_path = self.design / "references.json"
        refs = self.load_json(refs_path)
        refs["sources"] = [{
            "id": "fake", "source_type": "bogus", "uri": "does-not-exist.png",
            "sync_state": "present", "sha256": "0" * 64,
        }]
        self.save_json(refs_path, refs)
        screen = self.load_json(path)
        screen.pop("evidence_exception", None)
        screen["reference_ids"] = ["fake"]
        self.save_json(path, screen)

        result, output = self.run_cli("spec", "validate", "--strict")
        self.assertEqual(result, 1)
        self.assertIn("reference.source_type", output)
        result, output = self.run_cli(
            "spec", "promote", "screen", "main-menu", "--to", "reviewed",
            "--by", "Reviewer", "--note", "evidence must be real",
        )
        self.assertEqual(result, 1)
        self.assertEqual(self.load_json(path)["status"], "draft")

    def test_reference_import_preserves_id_and_marks_deleted_source_missing(self) -> None:
        image = self.root / "references" / "ui" / "action" / "hud" / "shot.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"reference-evidence")
        self.run_cli("scan-local")
        self.run_cli("spec", "import-references")
        refs_path = self.design / "references.json"
        refs = self.load_json(refs_path)
        original_id = refs["sources"][0]["id"]
        refs["sources"][0]["annotation"] = "Keep this human note"
        self.save_json(refs_path, refs)

        screen_path = self.make_complete_screen()
        screen = self.load_json(screen_path)
        screen["reference_ids"] = [original_id]
        screen.pop("evidence_exception", None)
        self.save_json(screen_path, screen)
        result, output = self.run_cli("spec", "build")
        self.assertEqual(result, 0, output)
        markdown = (self.design / "build" / "design-spec.md").read_text(encoding="utf-8")
        html = (self.design / "build" / "design-spec.html").read_text(encoding="utf-8")
        self.assertIn("../../references/ui/action/hud/shot.png", markdown)
        self.assertIn(original_id, markdown)
        self.assertIn("references/ui/action/hud/shot.png", html)

        image.unlink()
        result, output = self.run_cli("spec", "validate")
        self.assertEqual(result, 1)
        self.assertIn("reference.stale_sync", output)
        self.run_cli("scan-local")
        self.run_cli("spec", "import-references")
        refreshed = self.load_json(refs_path)["sources"][0]
        self.assertEqual(refreshed["id"], original_id)
        self.assertEqual(refreshed["annotation"], "Keep this human note")
        self.assertEqual(refreshed["sync_state"], "missing")
        result, output = self.run_cli("spec", "promote", "screen", "main-menu", "--to", "reviewed", "--by", "Reviewer", "--note", "evidence check")
        self.assertEqual(result, 1)
        self.assertIn("evidence.unavailable", output)

    def test_duplicate_content_references_keep_distinct_ids_and_notes(self) -> None:
        first = self.root / "references" / "ui" / "action" / "hud" / "shot.png"
        second = self.root / "references" / "ui" / "action" / "menu" / "shot.png"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_bytes(b"same-reference-bytes")
        second.write_bytes(b"same-reference-bytes")
        self.run_cli("scan-local")
        result, output = self.run_cli("spec", "import-references")
        self.assertEqual(result, 0, output)
        refs_path = self.design / "references.json"
        refs = self.load_json(refs_path)
        self.assertEqual(len(refs["sources"]), 2)
        self.assertEqual(len({item["id"] for item in refs["sources"]}), 2)
        expected_notes = {}
        for index, item in enumerate(refs["sources"], start=1):
            item["annotation"] = f"NOTE-{index}"
            expected_notes[item["uri"]] = item["annotation"]
        self.save_json(refs_path, refs)

        self.run_cli("scan-local")
        result, output = self.run_cli("spec", "import-references")
        self.assertEqual(result, 0, output)
        refreshed = self.load_json(refs_path)["sources"]
        self.assertEqual({item["uri"]: item["annotation"] for item in refreshed}, expected_notes)
        self.assertEqual(len({item["id"] for item in refreshed}), 2)

    def test_malformed_reference_catalog_is_preserved_during_sync(self) -> None:
        image = self.root / "references" / "ui" / "action" / "hud" / "shot.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"reference")
        self.run_cli("scan-local")
        refs_path = self.design / "references.json"
        refs_path.write_text("{broken", encoding="utf-8")
        before = refs_path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "existing catalog is invalid"):
            self.run_cli("spec", "import-references")
        self.assertEqual(refs_path.read_bytes(), before)

    def test_filtered_engine_export_replaces_stale_screen_outputs(self) -> None:
        self.make_complete_screen("main-menu")
        self.make_complete_screen("options")
        result, output = self.run_cli("export", "godot")
        self.assertEqual(result, 0, output)
        export_root = self.design / "build" / "exports" / "godot"
        self.assertTrue((export_root / "options.tscn").is_file())

        result, output = self.run_cli("export", "godot", "--screen", "main-menu")
        self.assertEqual(result, 0, output)
        self.assertFalse((export_root / "options.tscn").exists())
        self.assertFalse((export_root / "options.bindings.json").exists())
        manifest = self.load_json(export_root / "export-manifest.json")
        self.assertFalse(any(name.startswith("options.") for name in manifest["outputs"]))

    def test_capability_report_names_preserved_but_manual_engine_work(self) -> None:
        path = self.make_complete_screen()
        self.run_cli("spec", "add-component", "Primary Button", "--id", "primary-button")
        screen = self.load_json(path)
        screen["elements"][0]["asset_ref"] = "ui/main/start-button"
        screen["elements"][0]["component_id"] = "primary-button"
        self.save_json(path, screen)
        result, output = self.run_cli("export", "unity-uitoolkit")
        self.assertEqual(result, 0, output)
        export_root = self.design / "build" / "exports" / "unity-uitoolkit"
        report = self.load_json(export_root / "capability-report.json")
        features = {item["feature"] for item in report["manual_or_lossy"]}
        self.assertIn("runtime state styling and transitions", features)
        self.assertIn("accessibility semantics and focus behavior", features)
        self.assertIn("project asset resolution", features)
        self.assertIn("reusable component instantiation", features)
        bindings = self.load_json(export_root / "main-menu.bindings.json")["entries"][0]
        self.assertEqual(bindings["asset_ref"], "ui/main/start-button")
        self.assertEqual(bindings["component_id"], "primary-button")


if __name__ == "__main__":
    unittest.main()
