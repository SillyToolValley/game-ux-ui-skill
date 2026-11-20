# Feel, focus, and states

The timings here are starting values drawn from common practice and from rules of thumb in
game-feel literature. They are not measured laws. If you have footage of the anchor, its
timings outrank this table. Tune the final values in the engine.

## Timing

| Event | Start at | Shape |
| --- | --- | --- |
| Response to any input | Under 100 ms; 50 ms reads as instant | Immediate state change, then decorate |
| Focus moving between items | 60–120 ms | Ease-out; never block the next input |
| Button press | 60–100 ms down, quick release | Scale or offset a little; sound on the down stroke |
| Panel or submenu opening | 150–250 ms | Ease-out; content usable before the animation ends |
| Full screen transition | 200–400 ms | Skippable on repeat visits |
| Reward or level-up beat | 600–1200 ms | Anticipation, overshoot, settle; skippable with confirm |
| Number count-up | 400–800 ms | Ease-out; confirm jumps to the final value |
| Toast or notification | About 2000 ms | Stack at most three; merge identical events that arrive within 500 ms |
| Hold to confirm a destructive action | 600–1000 ms | Visible progress; releasing cancels |
| Damage or hit flash on the HUD | 80–120 ms | Hard on, soft off |
| Gameplay HUD reveal in combat | 0 ms | Information under pressure does not animate in |
| Gameplay HUD fade when idle | After about 10 s | Slow fade; return instantly on any relevant event |

Rules of thumb: ease-out to arrive, overshoot to celebrate, ease-in only for anticipation or
leaving. Keep routine UI motion under 300 ms. Run UI animation on unscaled time so pause menus
still move when the game is paused. Offer a reduce-motion setting and make sure nothing needs
motion to be understood.

Ask of every animation: how often does the player see it? Something seen a hundred times an
hour gets almost no animation. Something seen once a session can take a second.

## Focus and navigation

- Every screen opens with something focused. The default is the action most players want
  next, never a destructive one.
- Focus is the strongest state on the screen and differs from "selected" and "hovered".
- Moving in a direction goes to the visually nearest item in that direction. Decide wrap
  behaviour per list and keep it consistent.
- Back always works and always returns to the opener with its focus restored.
- A modal traps focus, dims and disables what is behind it, and gives focus back when closed.
- Moving the mouse must not strand gamepad focus, and a gamepad input must bring focus back.
- Show prompts for the device used last, and switch them when the device changes.
- Keep a screen stack: opening pushes, back pops, and each screen remembers its last focus.

## States to draw

Draw these before calling a screen done. The default state is the least informative one.

| Screen kind | States that break layouts |
| --- | --- |
| Any | Focused, pressed, disabled, loading, empty, error, longest localised string |
| Lists and grids | Zero items, one item, a full page, more than a page, new-item markers, locked |
| Shop and upgrades | Cannot afford, already owned, maximum level, sold out, price with seven digits |
| HUD | Full, critical, zero, buffed and debuffed at once, boss present, objective changed, several notifications at once |
| Results | Win, loss, draw, new record, nothing earned, level-up during the count |
| Dialogue | Two-line and maximum-length lines, choices, speaker change, auto-advance |

## HUD specifics

- Give every element a reason to be on screen now. State when it appears, when it quietens,
  and when it hides.
- Set a visual budget: an estimate of how much of the frame the HUD may cover in the busiest
  state, taken from the anchor. Measure the candidate against it.
- Keep the centre of the frame for the game. Only momentary indicators live there.
- Classify each element as diegetic (in the world and the fiction), spatial (in the world, not
  the fiction), meta (in the fiction, on the screen plane), or non-diegetic (overlay). Choose
  per element by how fast it must be read against how much it should belong to the world
  (Fagerholt and Lorentzon, *Beyond the HUD*, 2009).
- Never let colour be the only carrier of a critical distinction.

## Implementation gotchas

- A pause menu driven by scaled time freezes with the game.
- Baking live values into art makes them unlocalisable and unscalable. Keep text as text.
- One scaling policy from one reference resolution; fractional scaling blurs pixel art.
- Anchoring to screen edges without the platform safe-area inset clips on TVs and notched
  phones.
- Updating HUD text every frame costs layout work. Update on change.
