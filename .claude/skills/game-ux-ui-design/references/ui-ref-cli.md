# Reference evidence with `ui-ref` (spec pipeline)

For the default anchor loop you need only `ui-ref anchor add`; see `anchor-workflow.md`. This
file covers the multi-reference evidence catalogue used by the optional spec pipeline.

`ui-ref` keeps research evidence separate from authored UI contracts:

```text
references/ui/     curated image files
ui_research/       URL lists, caches, source manifests, contact sheets
ui_design/         canonical contracts and generated outputs
```

An image is a separate, hashable file in `references/ui/`. A generated Markdown/PDF/DOCX
may display that file inline through a relative image path. Do not create a separate Markdown
page that becomes a dead local link in shared exports.

## 1. Initialize safely

```bash
ui-ref init --project-name "<game>"
```

This command is idempotent: re-running it preserves existing configuration and the URL file.
Configured workspace paths must stay inside the project root.

Local convention:

```text
references/ui/<collection>/<category>/*.png|jpg|jpeg|webp|gif
```

Use stable, descriptive filenames. Collection and category become searchable manifest fields.

## 2. Collect a small source set

Put one explicit source page per line in `ui_research/urls.txt`. Prefer first-party captures
and official pages. Collect only from sites whose terms allow it, avoid login walls, and do not
attempt to bypass access controls. Game UI Database disallows AI agents
and AI training in its robots.txt, and `ui-ref collect` refuses its URLs (see
`finding-anchors.md`).

For JavaScript-rendered pages:

```bash
pip install -e ".[browser]"
playwright install chromium
ui-ref collect --browser --scroll 6 --download-gallery-assets --download-asset-limit 2
```

For a plain HTML page, omit `--browser`. Use `--mode images` when a page has no recognized
gallery structure. The collector:

- checks public HTTP(S) URLs and robots policy;
- blocks localhost, private/link-local destinations, and unsafe redirects;
- uses bounded requests and conservative defaults;
- writes atomic caches and manifests with final URL and SHA-256 where available;
- does not download gallery assets unless explicitly requested.

Keep runs small. A successful fetch means only that evidence was collected, not that it may be
redistributed. Record the source URL and usage/rights note.

### Site reality

- SPA filters may not survive direct deep links; repeated identical results across categories
  usually indicate that a filter did not apply.
- Cloudflare or login-protected sites may reject automation. Do not bypass the protection.
- Per-game pages often yield better evidence than broad category pages.
- Covers and banners commonly appear before actual interface captures; curate them out.
- If the direct genre is absent, use adjacent references but write the transfer limitation.

## 3. Curate, then index

Review the generated contact sheet and copy only selected study references into
`references/ui/<collection>/<category>/`. Keep the original source page in your notes.

```bash
ui-ref scan-local
```

This writes:

```text
ui_research/manifests/local_ui_refs_manifest.json
ui_research/manifests/local_ui_refs_manifest.md
```

The manifest indexes files already present locally. It does not claim those files were fetched
by the collector.

## 4. Import evidence into the contract catalog

```bash
ui-ref spec init --project-name "<game>"
ui-ref spec import-references
```

The importer calculates SHA-256, creates stable reference IDs, preserves existing IDs and human
annotations, recovers a source URL from collection manifests when possible, and marks missing
files instead of silently deleting their evidence records.

Use the resulting `ui_design/references.json` IDs from screens, elements, and observations.
Record:

- what is directly visible;
- the exact source/capture;
- what design decision it supports;
- why the pattern should transfer;
- the known transfer limit;
- whether attribution/redistribution is verified.

## 5. Display references in human-readable output

The canonical relationship lives in JSON as `reference_ids`. In an authored fallback
Markdown document, display the separate local file inline and keep the source URL beside it:

```markdown
![Enemy health and cooldown reference](references/ui/action/hud/example.jpg)

**Observed:** Enemy health and cooldown remain near the play focus.
**Applied to:** `A6`, `A8`.
**Transfer limit:** The source game has lower simultaneous visual density.
**Source:** [original interface page](https://example.invalid/game)
```

Use paths relative to the Markdown file. Do not say an image is attached when it is missing.
If evidence is pending, use an explicit `evidence_exception` and list the planned capture.

## 6. Verification

```bash
ui-ref spec trace screen <screen-id>
ui-ref spec validate --strict
ui-ref spec check --strict
```

The trace report connects a screen to reference records, bindings, interactions, approvals,
and dependency hashes. Review it before approval and after any evidence replacement.
