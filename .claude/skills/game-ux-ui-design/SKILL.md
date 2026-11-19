---
name: game-ux-ui-design
description: >-
  Design and build game UI that reaches the quality of shipped games: HUDs, menus, inventory,
  shop, results, settings, and any other game screen, in HTML or in an engine. Anchors each
  screen on one shipped game's screen, builds at full fidelity, and iterates by comparing
  screenshots against that anchor. Use whenever the user asks to design, mock up, build,
  restyle, or critique a game screen or HUD, or hands over a game screenshot as a reference.
  Also covers game UI specifications, wireframes, and engine handoff documents on request.
  Not for non-game product UI.
---

# game-ux-ui-design

A screen built from one strong shipped reference beats a screen built from a blend of many
references and a long specification. A screenshot of a shipped game carries hundreds of
decisions that were tuned together: proportion, density, type rhythm, material, where the eye
lands. Averaging several references, or translating them into abstract contracts first, throws
that coupling away and what comes back is plausible and generic.

So the default path is short: pick one anchor, read it closely, build the real thing, look at
the render next to the anchor, fix, repeat.

## Pick the smallest path that fits

| The user wants | Do |
| --- | --- |
| A screen or HUD designed or built | The anchor loop below |
| An existing screen reviewed or improved | Steps 4–5 of the loop against an anchor, or a critique with `references/game-ui-tells.md` |
| A spec, design document, flow prototype, approval trail, or engine handoff | The anchor loop first if the screen does not exist yet, then `references/spec-pipeline.md` |
| A reverse-engineered description of screenshots or video | `references/spec-pipeline.md`, OBSERVE stage |

Do not run the spec pipeline to make a screen look good. It records decisions; it does not
make them.

## The anchor loop

### 1. Brief — five lines, no more

Game and its fiction in one sentence. The screen and the one thing the player does on it.
Platform, input, and viewing distance. Engine or medium of the build. What the user already
decided. If one of these is missing and it changes the result, ask once; otherwise assume and
say so.

Classify the screen, because it sets how loud the design may be:

- **Operate** — in-play HUD, combat overlays. Restraint. The game is the picture; the UI
  borders it.
- **Manage** — inventory, shop, skills, map, settings. Density and scan speed.
- **Experience** — title, rewards, results, level-up, story beats. Commit to the fantasy.

### 2. Anchor — one hero per screen

The hero anchor is one screenshot of one shipped game's screen that does the same job as
yours, at the quality you want. If the user supplied one, use it. If not, propose two or three
candidates by game and screen, say what each would give, recommend one, and ask the user to
capture it. `references/finding-anchors.md` covers how to choose, where to look, and what you
may and may not do with gallery sites.

```bash
ui-ref anchor add captures/hades-boon.png --screen level-up --game "Hades" \
  --source-url "<where it came from>" --capture own-capture
```

One hero. A second image is allowed only as a support that fills one named gap
(`--role support --borrow "rarity frame treatment"`), at most two. If you want a third, the
hero is wrong: change it.

Without the CLI, do the same by hand: one image, one folder, the anatomy file below.

### 3. Read — fill in `ANATOMY.md` from the pixels

`anchor add` writes `ui_anchor/<screen>/ANATOMY.md` and, when the browser extra is installed,
extracts the real palette. Open the anchor image and fill the file in. Measure: region sizes
as a share of the screen, type sizes in pixels, the number of distinct sizes, the accent's
share of the frame, corner radii, stroke weights. Then state why it works, as mechanisms tied
to visible features.

Then translate. **Keep** structure and mechanisms: proportions, hierarchy, density, rhythm,
the way states are shown. **Change** identity: palette, typeface, material, ornament, icons,
all content. Your game's palette and materials come from its own fiction, not from the anchor.
**Drop** what only the anchor's game needs.

End with the plan: four to six named colours with roles, type roles, an ASCII layout at your
proportions, the one place the design spends its boldness. Ask whether this plan would fit any
similar game unchanged. If it would, it is a default, not a choice; revise.
`references/anchor-workflow.md` has a worked example and the common misreadings.

### 4. Build — the real screen, at full fidelity

Build in the medium the user asked for. If none was named, a single HTML file is the fastest
thing to iterate on and screenshot. Use real content from the game: real item names, real
numbers at their largest plausible width, real states. No grey boxes, no lorem ipsum.

Before building, read `references/game-ui-tells.md` once. It lists what model-made game UI
converges on. Each item is a default, not a rule: the anchor and the brief win.

Use `references/platform-numbers.md` for text size, safe area, and target size floors, and
`references/feel-and-states.md` for timing, focus, and state behaviour.

### 5. Compare — look at the render, next to the anchor

```bash
ui-ref shot build/level-up.html --screen level-up      # screenshot + start a round
ui-ref compare captures/unity-levelup.png --screen level-up   # or bring an engine capture
ui-ref audit build/level-up.html --platform tv         # floors: text, contrast, safe area
```

Each round writes `compare.html` (side by side, squint, values, guides, overlay) and a
`critique.md` with nine lenses. Look at both images. Fill in the critique with what you see,
pick the top three gaps, fix them together, and run the next round.

- Judge at the size and distance the screen ships at.
- If you can delegate, have a fresh reviewer who has not seen your reasoning compare the two
  images. Authors grade their own work generously.
- `audit` checks floors only. A pass means nothing is broken; it does not mean the screen is
  good. Report what it did not assess.
- Three rounds is the usual cap. If the screen is still below the anchor after three, the
  anchor or the plan is wrong. Go back to step 2 or 3 instead of polishing.
- Closing the gap means matching the anchor's level of finish and clarity, not its look. A
  candidate that could be mistaken for the anchor's game has failed lens nine.

Show the user the latest candidate beside the anchor, state which gaps remain, and say what
was not assessed.

## Ground rules

- Anchors are for study. Keep the source with every capture, never ship or redistribute
  another game's assets, logos, fonts, or character art, and never reproduce a screen closely
  enough to be taken for the original.
- Respect each reference site's terms and robots rules. Game UI Database disallows AI agents
  and AI training in its robots.txt: do not fetch it or feed its images to a model. The user
  can browse it to discover which game to study, then capture that screen themselves. Details
  in `references/finding-anchors.md`.
- Report honestly. Say which checks ran, which did not, and where the candidate still falls
  short of the anchor.
- The user's direction outranks every default in this skill.

## Files

- `references/anchor-workflow.md` — choosing, reading, and translating an anchor; worked example.
- `references/finding-anchors.md` — where to find anchors, how to capture them, site terms.
- `references/game-ui-tells.md` — what generated game UI converges on, and the alternatives.
- `references/platform-numbers.md` — text size, safe area, contrast, target floors with sources.
- `references/feel-and-states.md` — timing, feedback, focus, and state behaviour.
- `references/ux-heuristics.md`, `references/screen-exemplars.md` — reasoning aids for UX
  rationale; the exemplars are roguelite-leaning, do not transplant them to other genres.
- `references/spec-pipeline.md` — optional contracts, wireframes, prototype, and engine handoff,
  with `design-structure.md`, `annotated-wireframe-svg.md`, `engine-binding.md`,
  `ui-ref-cli.md`, `art-concept-imagegen.md`, and `templates/`.
