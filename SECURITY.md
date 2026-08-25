# Security policy

## Supported versions

Security fixes are applied to the latest `0.4.x` release line. Older versions should be upgraded before reporting a reproducibility problem.

## Reporting a vulnerability

Use the repository's private GitHub Security Advisory flow when it is available. Include the affected command, operating system, minimal reproduction, expected impact, and whether a network request or untrusted project file is required. Do not publish secrets, private captures, or a working exploit in a public issue. If private advisories are unavailable, open a minimal issue asking the maintainer for a private reporting channel.

## Trust boundaries

- `collect` is intended for explicitly selected public HTTP(S) pages. It blocks private and local network destinations, credential-bearing URLs, and unsafe redirects, but it is not a general-purpose browser or crawler.
- Project contracts, downloaded pages, reference media, and AI-produced JSON are untrusted input. Keep the CLI and browser dependency current, review generated output before distribution, and do not put credentials in project configuration.
- AI analysis is evidence-bounded and imported only as `draft`. Human review remains responsible for product decisions, rights, accessibility, runtime bindings, and final approval.
- Engine exports are handoff scaffolds, not executable project logic. Review generated bindings and asset paths before importing them into a game project.

## Evidence and licensing

The collector records provenance; it does not grant redistribution or training rights. Verify the source terms for every reference and avoid committing proprietary or personal captures to a public repository.
