# Contributing

Thanks for helping improve evidence-backed game UX/UI work.

## Development setup

```bash
python -m pip install -e .
python -m py_compile ui_ref_cli.py ui_ref_design.py
python -m unittest discover -s tests -v
```

The core workflow deliberately has no runtime dependency. Keep optional browser or document tooling behind explicit extras or companion scripts.

## Change guidelines

- Preserve compatibility for `init`, `scan-local`, and `collect` unless a documented major release changes them.
- Treat `ui_design/` JSON and `.uiwire` files as canonical; generated IR, documents, prototypes, and engine handoffs must be reproducible from them.
- Keep screen, component, element, reference, and decision IDs stable. Migrations must preserve human notes and approval history.
- Never let AI output self-approve. Reviewed/approved gates must retain exact evidence and dependency traceability.
- Add a focused regression test for every bug fix and an end-to-end test for each new command path.
- Keep generated HTML/SVG escaped and protected by a restrictive content-security policy.
- Do not commit third-party captures unless their redistribution rights are clear.

Before opening a pull request, run the commands above and `git diff --check`. Explain user-visible behavior, compatibility impact, and any capability that remains intentionally manual or lossy.
