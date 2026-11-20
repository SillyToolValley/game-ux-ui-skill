# Anchor workflow — choosing, reading, translating

## Why one anchor

- A shipped screen is a set of decisions tuned against each other. Take the layout from one
  game, the palette from a second, and the card frame from a third, and none of them was tuned
  for the others. The result regresses to the average of the genre.
- A model that looks at one concrete image can match its level of finish. A model that reads
  a description of twelve images matches the description.
- One anchor gives the comparison step something to compare against. "Is this good?" has no
  answer; "is this as clear and as finished as that?" does.

## Choosing the hero

Choose for the job the screen does, not for the genre label or the art style.

1. **Same job.** A three-way upgrade choice under no time pressure is the same job in a
   roguelite, a city builder, and a card game. A HUD for a twin-stick shooter is not the same
   job as a HUD for a turn-based tactics game, even if both are "sci-fi".
2. **Same constraints.** Input device, viewing distance, aspect ratio, and information volume
   should be close. A mouse-driven PC inventory is a poor anchor for a gamepad inventory on TV.
3. **A game that shipped and was played.** Its UI survived playtests, patches, and real
   players. Concept art and portfolio mock-ups have survived nothing.
4. **Not your art style.** An anchor in a different visual genre makes the keep/change split
   easier and makes cloning less likely.
5. **Native capture.** Full resolution, no compression mush, no stream overlay, ideally in a
   non-default state (a long item name, a full inventory, low health).

Reject an anchor when you cannot say in one sentence what it does better than its peers.

When proposing candidates to the user, name the game, the exact screen, and the mechanism each
offers. Say plainly when you are recalling a screen from memory and have not seen the capture.

## Reading the anchor

Work from the image. Zoom in. Count.

- **Blocking.** Draw the regions as an ASCII map with each one's share of width and height.
  Note what is left empty and where the largest single element sits.
- **Reading order.** What is seen first, second, third, and what makes it so: size, value
  contrast, isolation, motion, or position.
- **Type.** Pixel height of the largest, the body, and the smallest text. How many distinct
  sizes there are (shipped screens usually use four to six). Weight steps, case, tracking,
  whether numerals are tabular or a different face.
- **Colour.** Assign each extracted colour a role. Estimate the accent's share of the frame;
  it is usually small. Note which colours carry meaning (rarity, team, danger) and whether a
  shape or icon repeats that meaning.
- **Shape and material.** Corner radius, stroke weight, whether fills are flat, graded, or
  textured, how panels end (hard edge, fade, ornament), how icons are constructed.
- **States visible in the capture.** Selected versus unselected, disabled, new, locked,
  affordable versus not. How much changes between states, and which property carries it.
- **Input surface.** Where button prompts sit, how focus is shown, what the default selection
  is.

Then write three to five mechanisms. A mechanism names a visible feature and the player
problem it solves:

- Weak: "clean and readable layout".
- Strong: "the three choices are the only saturated objects on a desaturated, darkened frame,
  so the decision is the only thing on screen that asks for attention".

## Translating

| Keep | Change | Drop |
| --- | --- | --- |
| Proportions and blocking | Palette (from your fiction) | Systems your game lacks |
| Reading order | Typeface | Ornament tied to the anchor's world |
| Density and spacing rhythm | Material, texture, edge treatment | Platform-specific furniture |
| How states differ | Icon construction and all icon art | Anything you cannot explain |
| Where prompts and focus sit | Every label, number, and name | |
| Motion structure, if observed | Ornament vocabulary | |

Derive the changed side from the game: what its world is made of, what its characters would
print, carve, or project, the vocabulary its factions use. A tavern management game and a
derelict-station horror game can share an anchor and end up with nothing visually in common.

**Worked example.** Screen: a post-match result for a four-player party game about throwing
things across school rooftops. Anchor: the results screen of a kart racer.

- Keep: ranked rows that take 60% of the width with the player's own row enlarged and offset;
  one celebratory element (the winner's portrait) breaking the frame at top left; the three
  actions in a single row along the bottom safe edge with glyph prompts; reward count-up to
  the right of each row.
- Change: racing-flag checker and chrome become notebook paper, tape, and marker strokes;
  the condensed italic racing type becomes a rounded hand-lettered display face with a plain
  sans for numbers; positions become club ranks.
- Drop: lap times and the track map inset.
- Boldness spent on: the winner's portrait tearing through a taped photo frame. Everything
  else stays quiet.

## Common misreadings

- **Copying the surface, missing the mechanism.** The same panel shapes with the anchor's
  hierarchy flattened. Check the reading order with the Values toggle.
- **Shrinking the anchor's density.** Shipped screens often hold more per screen than a first
  draft dares to. Count elements in both.
- **Web spacing.** Padding and corner radii carried over from product UI. Measure the
  anchor's actual gutters.
- **Keeping the anchor's palette.** If the extracted candidate palette sits within a few steps
  of the anchor's, the identity was not changed.
- **Anchoring a HUD on a menu, or the reverse.** The modes differ; see `SKILL.md` step 1.

## Several screens

Each screen gets its own hero, but a game needs one visual language. After the first screen
passes, treat your own approved screen as the style source for the rest: later screens take
structure from their own hero and identity from your first screen. Record the shared colours,
type roles, and shape rules once in a short `ui_anchor/STYLE.md`, and update it when the user
corrects something.
