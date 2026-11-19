# Platform numbers — floors with sources

These are floors and starting points. The anchor shows where shipped games actually sit, which
is usually above the floor. Each row says where the number comes from and how well it was
verified when this file was written. Re-check primary sources before a certification
submission.

Status: **secondary** means read from a secondary citation or search-indexed text of the
primary source, not from the primary page itself. **convention** means common practice with no
single authority. **unverified** means recalled, not checked.

## Text size

| Context | Floor | Source | Status |
| --- | --- | --- | --- |
| Console at 1080p | 26 px | Xbox Accessibility Guideline 101 | secondary |
| Console at 4K | 52 px | XAG 101 | secondary |
| PC and VR at 1080p | 18 px | XAG 101 | secondary |
| PC and VR at 4K | 36 px | XAG 101 | secondary |
| Mobile or streaming | 18 px at 100 DPI, 36 px at 200 DPI, 72 px at 400 DPI | XAG 101 | secondary |
| Text inside a glyph or icon | 13 px console, 9 px PC | XAG 101 | secondary |
| Handheld PC at 1280x800 | 9 px minimum, 12 px recommended, readable at 30 cm | Steam Deck Verified review | secondary |
| Text scaling | Up to 200% without loss | XAG 101 | secondary |

Sizes scale linearly with vertical resolution. `ui-ref audit` measures CSS font size, which is
slightly larger than the glyph body height these guidelines describe, so treat an audit pass
near the floor as marginal. PlayStation and Nintendo publish their requirements to licensed
developers only; nothing here speaks for them.

## Contrast

| Rule | Value | Source | Status |
| --- | --- | --- | --- |
| Body text against its background | 4.5:1 | XAG 102, WCAG 2.x AA | secondary |
| Large text | 3:1 | XAG 102, WCAG 2.x AA | secondary |
| Text over gameplay | Give it a plate, outline, or shadow so the ratio holds over any frame | convention | — |

## Safe area

| Context | Value | Source | Status |
| --- | --- | --- | --- |
| TV, title-safe | Inner 90% (1728x972 at 1080p) | SMPTE ST 2046-1; Xbox guidance | secondary |
| TV, action-safe | Inner 93% | SMPTE ST 2046-1 | secondary |
| Phones | Read the device safe-area insets; never hard-code | Platform APIs | convention |
| Ultrawide | Keep the HUD within a 16:9 region or offer a HUD-width setting | convention | — |
| All platforms | Offer a HUD safe-area or scale setting where the platform allows | convention | — |

## Touch

| Rule | Value | Source | Status |
| --- | --- | --- | --- |
| Minimum target | 24x24 CSS px | WCAG 2.2 AA (2.5.8) | secondary |
| Comfortable target | 44x44 CSS px | WCAG 2.2 AAA (2.5.5) | secondary |
| Platform guidance | 44 pt (Apple), 48 dp (Android) | Platform HIGs | unverified |
| Reach | Primary actions in the lower corners in landscape; keep the top edge for status | convention | — |

## Localisation

| Rule | Value | Source | Status |
| --- | --- | --- | --- |
| Long strings | Allow about 30% growth | Attributed to IBM guidance | secondary |
| Short strings (under 10 characters) | Allow 100–200% growth | Attributed to IBM guidance | secondary |
| Working budget | 40% | Common studio practice | convention |
| CJK | Glyphs need more height than Latin at the same legibility; test at the floor size | convention | — |

## Sweep sizes

Screenshot every screen at least at: 1920x1080; 1280x720 or 1280x800; one ultrawide
(2560x1080); and, for mobile, one tall phone (for example 1080x2340). Check text scaling at
100%, 150%, and 200% where the game supports it.

## What `ui-ref audit` presets use

| `--platform` | Viewport | Text floor | Safe inset | Target floor | Initial focus required |
| --- | --- | --- | --- | --- | --- |
| `tv` | 1920x1080 | 26 px, scaled by height | 5% per edge | — | yes |
| `desktop` | 1920x1080 | 18 px, scaled by height | none | — | no |
| `handheld` | 1280x800 | 9 px (12 px recommended) | none | — | yes |
| `mobile` | 390x844 | 11 px (14 px recommended) | 4% per edge | 44 px | no |

The mobile text floor is this tool's working default in CSS px, not a platform rule. Override
any preset with `--min-text`, `--safe-area`, `--min-target`, and `--viewport`.
