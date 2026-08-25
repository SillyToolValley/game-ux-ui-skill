# Changelog

All notable changes to Game-UI-Reference-Cli are documented here. The project follows semantic versioning.

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

[0.4.0]: https://github.com/SillyToolValley/Game-UI-Reference-Cli/releases/tag/v0.4.0
