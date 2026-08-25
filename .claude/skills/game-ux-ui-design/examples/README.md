# Examples

The repository does not redistribute a worked screenshot bundle because third-party captures
may have separate rights. Generate a local example from your own GDD and first-party or
properly attributed study references. Legacy local *Lucid Dawn* artifacts may exist in a
developer workspace, but they are not the canonical v0.4 contract example and must not be
modified or published automatically.

## What a generated design document looks like

Running the skill on a GDD produces, under your project:

```
ui_design/screens/*.json      # canonical screen contracts
ui_design/components/*.json   # canonical reusable components
ui_design/wireframes/*.uiwire # deterministic editable wireframe sources
ui_design/build/design-spec.md / .html
ui_design/build/wireframes/*.svg
ui_design/build/prototype/*   # generated interaction prototype
ui_design/build/exports/*     # engine handoff + capability reports
design.pdf / design.docx      # optional wide meeting shares (read / edit)
references/ui/<col>/<cat>/*   # reference screenshots harvested with `ui-ref`, embedded
                             #   INLINE in each screen's `#### 참조` section
```

## The bar this skill aims for

1. **References embedded inline** per screen (real image + the what/why) — no dead links.
2. **Every UI element numbered**, boxed/circled, with a leader line to a label outside the
   frame; full detail in the legend table beneath.
3. **Plain-language `UX 설계 의도`** a mixed team (기획·아트·개발·PM) can read — no framework
   jargon in the body (methodologies, if any, listed once in the appendix).
4. **Implementable:** immutable element codes, measurable criteria, full state matrices,
   data-bindings tied to verified GDD fields/events or explicit assumptions.
5. **Reviewable:** human-only final approval bound to revision, content hash, and dependencies.
6. **Honest handoff:** prototypes and engine adapters disclose manual/lossy work.

To generate one: copy this skill into your game project's `.claude/skills/`, then ask for
the UX/UI 디자인 문서 of the screens you want (see `../SKILL.md` for the process).
