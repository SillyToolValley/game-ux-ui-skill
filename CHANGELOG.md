# Changelog

All notable changes to game-ux-ui-skill are documented here. The project follows semantic versioning.

## [0.5.0] - 2026-11-19

The default workflow changes from "collect many references, compile contracts, render wireframes" to an anchor loop: one shipped screen as the anchor, a full-fidelity build, and screenshot comparison against that anchor. In use, the contract-first path produced plausible but generic screens; a single strong reference handed to a capable model did better.

### Added

- `ui-ref anchor add` / `anchor show`: one hero anchor per screen with source, hash, size, and browser-extracted palette; at most two supports, each with a named `--borrow`; an `ANATOMY.md` template for measured anatomy, keep/change/drop translation, and a short plan.
- `ui-ref shot`: screenshot an HTML build or URL at the anchor's size and start a numbered comparison round.
- `ui-ref compare`: a dependency-free side-by-side sheet with squint, values, safe-area and thirds guides, overlay, and flicker, plus a nine-lens critique template. Accepts any screenshot, including engine captures.
- `ui-ref audit`: deterministic floor checks on an HTML build for `tv`, `desktop`, `handheld`, and `mobile` presets — text size, contrast, safe area, clipped text, touch targets, page overflow, initial focus — with an explicit list of what was not assessed.
- Skill references: `anchor-workflow.md`, `finding-anchors.md`, `game-ui-tells.md`, `platform-numbers.md`, `feel-and-states.md`.

### Changed

- `SKILL.md` is now a short router whose default path is the anchor loop. The previous contract workflow moved unchanged to `references/spec-pipeline.md` and is opt-in.
- Removed the `gameuidatabase` site preset, and `collect` now refuses gameuidatabase.com URLs: the site's robots.txt (checked November 2026) disallows AI agents and AI training crawlers and marks content `ai-train=no, use=reference`. Galleries are for a person to discover which game to study; captures are first-party.
- `screen-exemplars.md` is labelled as roguelite-leaning and no longer lists gallery deep links.
- READMEs lead with the anchor loop in all four languages.

### Renamed

- The project is now **game-ux-ui-skill** (formerly Game-UI-Reference-Cli; distribution formerly `ui-ref-cli`). The `ui-ref` command is unchanged and `game-ux-ui` is installed as an alias. Python module names and the contract schema `$id` are unchanged.

### Compatibility

- Every v0.4 command (`spec`, `wireframe`, `prototype`, `analyze`, `export`, `init`, `scan-local`, `collect`) is unchanged.
- The new commands add no core dependency. `shot`, `audit`, and palette extraction use the existing optional `browser` extra; set `UI_REF_BROWSER_PATH` to use a specific Chromium binary.

## [0.4.0] - 2026-08-25

### Added

- A canonical `ui_design/` contract workspace for projects, tokens, flows, references, decisions, approvals, screens, components, and deterministic `.uiwire` sources.
- Validation gates for immutable IDs, viewport geometry, hierarchy, evidence, state completeness, accessibility, input-device parity, Given/When/Then acceptance criteria, data-binding provenance, and flow targets.
- Hash-bound `draft` → `reviewed` → `approved` lifecycle transitions; final approval requires an explicitly named human and becomes stale when contract dependencies change.
- Engine-neutral Design IR plus reproducible Markdown, HTML, annotated SVG, and build manifests.
- A static clickable prototype with keyboard and gamepad navigation, scenarios, safe-area visualization, transition wiring, and a release approval gate.
- Explicit handoff exporters for Unity UI Toolkit, Unity uGUI, Godot, and Cocos, each with capability and hash manifests.
- Screenshot/video analysis packets, frame extraction and deduplication, evidence contact sheets, and draft-only multimodal-result import with exact packet and source-evidence hash checks.
- Automated tests and a Windows/Linux, Python 3.10/3.13 CI matrix.

### Changed

- The CLI is now described as an evidence-backed game UX/UI research and specification compiler.
- `init` is idempotent and preserves unknown configuration metadata while adding the structured-design workspace setting.
- Local manifests include SHA-256 provenance, timestamps, image dimensions, and a versioned format.
- Reference synchronization preserves stable IDs and human notes, and marks missing evidence instead of deleting records.
- Duplicate-content references retain separate URI identities, current evidence hashes are rechecked at validation time, and malformed catalogs are preserved instead of overwritten.
- Authored flows now drive prototype entry/navigation and conflicting action targets fail validation.
- Prototype routes honor source scenario/mode gates, hidden source controls, role provenance, exact replay history restoration, and role-preserving room returns.
- Modal previews now enforce inert backgrounds, deterministic initial focus, keyboard/gamepad cancel behavior, focus trapping, opener restoration, and a focusable authoritative waiting state.
- Navigation metadata validates source guards, mode-specific destinations, target scenarios, z-order, nested control contracts, and explicit history restoration.
- Conditional element applicability now controls default wireframes and live prototype scenarios, including hidden modal descendants.
- Screens can declare a `default_scenario`, and elements can declare validated `rect_overrides` so scenario-specific reflow is preserved in wireframes, prototypes, Design IR, and Unity uGUI handoff JSON.
- The bundled `game-ux-ui-design` companion skill now uses the canonical contracts and distinguishes AI review from human approval.

### Security and reliability

- Collection rejects private, loopback, link-local, credential-bearing, and unsafe redirect URLs; browser requests are guarded with the same public-network policy.
- Project-owned paths cannot escape the configured project/workspace roots, and local scanning ignores symlinks that resolve outside the reference root.
- Network and media limits are validated before work begins; response bodies, browser HTML, robots files, and error records are bounded.
- Generated pages use restrictive content-security policies and escape authored labels and metadata.
- Writes use atomic replacement to avoid partially written configuration, manifests, and generated artifacts.
- Lifecycle contract/approval/decision updates commit together; reviewed history cannot be erased by force creation or AI import.
- AI imports validate every proposed contract and wireframe before a single write, bind evidence IDs to the exact packet and content hash, and commit references/screens/wireframes as one rollback-safe transaction.
- Unsupported reference types, malformed quality gates/contracts, disconnected ordered flows, blank approval identities, and empty release sets fail closed with actionable diagnostics.
- Prototype and engine exports are staged and swapped as exact generated sets, preventing removed screens from lingering in manifests.
- Generated-directory commands refuse regular files and symbolic links at output paths, preserving user-owned data.

### Compatibility

- Existing `init`, `scan-local`, and `collect` workflows remain available.
- The structured-design workflow is additive. Existing projects can run `ui-ref init` and then `ui-ref spec init` to adopt it.

[0.5.0]: https://github.com/SillyToolValley/game-ux-ui-skill/releases/tag/v0.5.0
[0.4.0]: https://github.com/SillyToolValley/game-ux-ui-skill/releases/tag/v0.4.0
