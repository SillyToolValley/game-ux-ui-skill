# Finding and capturing anchors

## Where the image should come from

In order of preference:

1. **Your own capture** of a game you can run: native resolution, the exact state you need.
2. **Official material**: press kits, store-page screenshots, the publisher's own trailers.
3. **A frame from gameplay footage** you are entitled to view. Prefer high-bitrate sources and
   note the timestamp.

Record the source with `--source-url` and the kind with `--capture`. Keep anchors inside the
project for study; do not publish them as part of your own work.

## Gallery sites are for discovery

Use galleries to learn which game does a given screen best. Then capture that screen yourself.

**Game UI Database** (`gameuidatabase.com`) is the largest index: well over a thousand games
and tens of thousands of screens, browsable by screen type and by attributes.

- Its robots.txt, read in November 2026, disallows AI agents that fetch on a user's behalf
  (`Claude-User`, `ChatGPT-User`, `Perplexity-User` and others) and AI training crawlers
  (`GPTBot`, `ClaudeBot`, `CCBot` and others) from the whole site, and marks its content
  `search=yes, ai-train=no, use=reference` for everyone else. The site is also behind a bot
  challenge, and its owner has publicly objected to AI crawling.
- So: do not fetch it as an agent, do not scrape it, and do not feed images taken from it to
  a model. `ui-ref collect` refuses its URLs. Its human-facing terms page was not read when
  this was written; check it for anything stricter.
- What is fine: a person browsing it to decide which game and screen to study, and this
  skill naming a screen type for them to look up.

Its taxonomy is a useful vocabulary for describing what you are looking for, wherever you look:

| Axis | Values include |
| --- | --- |
| Screen type | Gameplay and HUD, maps, items and unlocks, shops, skill trees, results, rewards, dialogue, tutorials, settings, controls reference, title and main menu |
| Camera | First person, third person, top down, side view, isometric or grid |
| Game aesthetic | 2D art, 3D realistic, 3D stylised, low poly, retro |
| UI style | Flat, flat with texture, minimalist, skeuomorphic, hand-painted, pixel, art and vector |
| Elements | List menu, tile menu, tabs, radial menu, side menu, image grid, tooltip, diegetic, in 3D space |
| Material and pattern | Paper, wood, textile, grunge brush, halftone, art deco |
| Dominant colour | Named hue families |

**Interface In Game** (`interfaceingame.com`) is smaller and curated, with per-game pages and
clips. Check its terms before any automated use.

For any other site: read its terms, honour robots rules, and prefer linking over downloading.
`ui-ref collect` exists for sites that permit collection; it refuses private hosts, respects
robots.txt, and downloads nothing unless told to.

## Asking the user for an anchor

When the user has not supplied one, offer a short choice, not a survey:

> For the upgrade-choice screen I would anchor on one of these:
> 1. *Game A* boon selection — strongest at making three options the only thing on screen.
> 2. *Game B* level-up — strongest at showing the current build beside the choice.
> 3. *Game C* reward draft — strongest at dense stat deltas that still read fast.
>
> I recommend 1 because our choices are few and high-stakes. Can you capture that screen, or
> send any shot of it you are entitled to use?

Say when a candidate comes from memory. If the user cannot provide a capture, work from an
anchor they can provide before you work from none; if there is truly no image, say that the
comparison step will be weaker and proceed with the written anatomy of the screen as you
recall it, marked as recalled.
