# Spec pipeline — optional team handoff

Load this only when the user asks for a specification, design document, contract, approval
trail, clickable flow prototype, or engine handoff scaffold. It is not the way to make a screen
look and feel good: do that first with the anchor loop in `anchor-workflow.md`, then document
the result here. A contract written before a screen has been seen is a guess with a schema.

Paths below such as `references/...` and `templates/...` are relative to the skill directory.

Produce a game UI package that a mixed design, art, engineering, QA, and production team can
review without guessing. The canonical source is the structured JSON contract under
`ui_design/`; Markdown, HTML, SVG, prototypes, and engine files are generated views.

## Non-negotiable source model

- Keep reference images as separate files under `references/ui/` so their origin and hash
  remain traceable. Display those files inline in generated Markdown/PDF/DOCX through
  relative image paths. “Separate asset” and “inline display” are complementary rules.
- Treat a GDD statement, direct visual observation, inference, assumption, standard, and
  human decision as different provenance classes. Never present an inference as a fact.
- Use immutable screen, component, element, reference, and decision IDs. Retire IDs; do not
  silently reuse them.
- AI may create drafts and mark work reviewed. Only a named human may approve a revision.
  Never pass `--human-confirmed` unless the user has explicitly approved that exact revision.
- Approval is bound to the contract hash and its token/flow/reference/component dependency
  hashes. A dependency change makes the approval stale and blocks release output.
- Do not invent runtime field or event names and attribute them to the GDD. Mark new names as
  UI proposals or assumptions until the game contract adopts them.
- Every interactive element needs input, default/focused/pressed/disabled states,
  accessibility metadata, and measurable acceptance criteria before review.
- The engine exporters create handoff scaffolds, not finished production UI. Always surface
  `manual_or_lossy` and unsupported items from the capability report.

## Workflow — use these stable stage IDs in notes and handoffs

### ORIENT — understand the game and scope

Read the GDD/brief and identify the target platforms, aspect ratios, locales, input devices,
engine, screen list, core flow, game state per screen, and explicit exclusions. If there is no
brief, ask only for information that materially changes the result; otherwise record reasonable
assumptions in the contracts.

Initialize once:

```bash
ui-ref init --project-name "<game>"
ui-ref spec init --project-name "<game>" --locale <locale>
```

`ui-ref init` is idempotent and preserves existing configuration. `ui-ref spec init --force`
refreshes starter metadata without deleting authored screens, components, or human notes.

### EVIDENCE — collect, curate, and register references

Follow `references/ui-ref-cli.md`. Prefer first-party captures and stable, attributable source
pages. Keep collection runs small and honor robots/site terms. Curate selected evidence into
`references/ui/<collection>/<category>/`, then run:

```bash
ui-ref scan-local
ui-ref spec import-references
```

For every applied pattern, record what is directly visible, why it transfers to this game, and
where the transfer may fail. If no reference is available, use an explicit
`evidence_exception`; do not pretend an image exists.

### OBSERVE — optional screenshot/video reverse engineering

Use this only when media is an input. It extracts or indexes evidence and creates a bounded AI
analysis packet; it does not call an AI provider by itself.

```bash
ui-ref analyze media <screenshots-or-video> --interval 2 --frame-limit 120
```

Give `analysis-prompt.md`, `analysis-packet.json`, and `analysis-result.schema.json` to the
chosen vision model. The result must identify provider, model, prompt version, input hash,
evidence IDs, confidence, and one of `observed`, `inferred`, or `unknown` for every claim.
Import only after validating that result:

```bash
ui-ref analyze import <result.json> --packet <analysis-packet.json>
```

Imported screens remain `draft`. Unknown interaction facts—pause behavior, first focus,
cancel/back, destructive confirmation, missing/error behavior—become questions, not invented
answers.

### SPEC — author the canonical contract

Create stable starters, then edit their JSON contracts:

```bash
ui-ref spec add-screen "<name>" --id <screen-id> --wireframe
ui-ref spec add-component "<name>" --id <component-id>
```

Each screen must cover purpose/player goal, entry and exit, viewport/safe area, evidence,
elements and geometry, input interactions, complete states, data bindings with provenance,
accessibility, edge cases, open questions, and acceptance criteria. Use
`references/design-structure.md` and `templates/per-screen.md` as authoring checklists, not as
a second canonical source.

For plain-language `UX 설계 의도`, explain:

- what the player must notice first and why;
- how the layout prevents mistakes and supports mouse/keyboard/gamepad/touch as applicable;
- how feedback supports feel without hiding critical information;
- how first-time and repeat use differ;
- how non-color cues, focus, text scaling, reduced motion, and recovery work;
- the top risks and the cheapest test that could disprove the design.

Reason with `references/ux-heuristics.md`, but do not fill the deliverable body with framework
names or unexplained jargon.

### VALIDATE — make omissions machine-visible

```bash
ui-ref spec validate --strict
ui-ref wireframe lint ui_design/wireframes/<screen>.uiwire
ui-ref wireframe render ui_design/wireframes/<screen>.uiwire
ui-ref spec check --strict
```

`.uiwire` is the deterministic, AI-friendly wireframe source; SVG is generated. The older
`templates/wireframe-kit.svg` remains a manual fallback for highly customized redlines. If that
fallback is used, run `templates/validate_wireframe.py` and visually inspect the render.

Do not mark validation complete while there are contract errors, broken references, duplicate
IDs, out-of-bounds geometry, missing states/input/accessibility/acceptance, stale approvals, or
invalid wireframes. Warnings and open questions must be summarized for the reviewer.

### REVIEW — record review and human approval

First move complete work to reviewed:

```bash
ui-ref spec promote screen <screen-id> --to reviewed --by "<reviewer>" --note "<scope>"
```

Show the user the exact revision, remaining assumptions, evidence limits, and impact of manual
engine work. Only after that named human explicitly approves the revision may you run:

```bash
ui-ref spec promote screen <screen-id> --to approved --by "<human>" \
  --note "<approval scope>" --human-confirmed
```

Repeat for reusable components. If an approved artifact changes, deliberately move it back to
draft and re-review; never repair the approval ledger by hand.

### RENDER — build consistent human-readable outputs

```bash
ui-ref spec build
```

This compiles one Design IR and generates `design-spec.md`, readable `design-spec.html`,
annotated wireframe SVGs, and a build manifest under `ui_design/build/`. These files are
generated and should not be manually edited.

For wide meeting deliverables, convert the generated Markdown with:

```bash
pip install markdown python-docx
python .claude/skills/game-ux-ui-design/templates/build_pdf.py ui_design/build/design-spec.md --lang <lang>
python .claude/skills/game-ux-ui-design/templates/build_docx.py ui_design/build/design-spec.md --lang <lang>
```

Those paths are relative to the game project root and therefore work when the commands above
are run in the same directory as `ui_design/`. If the skill was installed elsewhere, replace
`.claude/skills/game-ux-ui-design` with that installed skill directory.
For DOCX, an SVG is rasterized through a sibling PNG, optional CairoSVG, or local Chrome/Edge;
if none is available, the document keeps an explicit fallback note instead of silently omitting it.

### PROTO — exercise flows and non-default states

```bash
ui-ref prototype build
ui-ref prototype build --release
```

The static prototype supports screen transitions, state scenarios, keyboard focus, basic
gamepad confirm/back, exit flows, safe-area preview, and a visible contract hash. Draft builds
are for exploration. `--release` requires current human approval for every included screen.

### EXPORT — generate explicit engine handoff scaffolds

```bash
ui-ref export unity-uitoolkit
ui-ref export unity-ugui
ui-ref export godot
ui-ref export cocos
```

Use `--screen <id>` for a slice and `--release` for approved-only output. Read
`capability-report.json` and `export-manifest.json` every time. UI Toolkit produces UXML/USS
and bindings; Godot produces Control-scene scaffolds and bindings; uGUI and Cocos currently
produce structured handoff manifests where reliable native serialization is not available.
Do not claim that generated scaffolds replace engine integration, localization, asset hookup,
performance profiling, or playtesting.

### VERIFY — close the loop

```bash
ui-ref spec trace screen <screen-id>
ui-ref spec check --strict
```

Verify the built-source hashes, evidence links, data bindings, focus order, state scenarios,
release gate, exporter capability notes, and measurable acceptance criteria. Run a visual check
of every wireframe/prototype at target ratios and re-test high-density readability in an engine
build. A wireframe alone cannot validate combat legibility or final feel.

## Deliverable language and honesty

- Lead with the player-facing decision and its evidence, not tool mechanics.
- Separate `observed`, `inferred`, `assumed`, and `approved` statements.
- Keep numbers sourced (GDD, standard, or decision ID) and include units.
- If evidence, fonts, engine version, or a human decision is missing, name the gap and its
  impact. Never fabricate completion.
- Do not redistribute harvested screenshots as an asset pack; preserve source attribution and
  usage notes.

## Fallback when `ui-ref` is unavailable

Produce a clearly labeled draft using `templates/design-skeleton.md`, `templates/per-screen.md`,
and `templates/wireframe-kit.svg`. Keep the same IDs, provenance distinctions, state/input/
accessibility/acceptance coverage, and inline-display/separate-asset rule. State that lifecycle
hashes, deterministic builds, prototypes, and engine exports remain pending until the CLI is
available.

## Relevant files

- `references/ui-ref-cli.md` — collection, curation, evidence import, and rights notes.
- `references/design-structure.md` — contract coverage and generated-document anatomy.
- `references/annotated-wireframe-svg.md` — `.uiwire` and manual SVG redline conventions.
- `references/engine-binding.md` — runtime integration/performance guidance.
- `references/ux-heuristics.md` and `references/screen-exemplars.md` — private reasoning aids.
- `references/art-concept-imagegen.md` — optional art-direction exploration; not contract truth.
- `templates/` — manual fallback and PDF/DOCX conversion tools.
