# Game-UI tells — what generated game UI converges on

Each item below is a legitimate choice for some game. It becomes a tell when it appears
without a reason from the anchor, the fiction, or the brief. Read the list before building and
again as lens eight of every critique. The anchor and the brief win over this list.

## Borrowed from web and app UI

| Tell | Why it reads as generated | What shipped games do instead |
| --- | --- | --- |
| Dark navy or charcoal with cyan or violet glow, in any genre | The model's default for "game" | A palette derived from the world: its materials, light, printing, signage |
| Rounded cards with a translucent border and blur | Product-dashboard vocabulary | A panel language with its own edges: cut corners, torn paper, brackets, fades, frames, or no panel at all |
| A box around every stat | Dashboard habit | Unframed elements anchored to screen edges; value contrast and position separate them |
| One neutral sans for everything | Safe default | A display face with character, a workhorse face for body, numerals chosen to be read at speed |
| Generic line icons or emoji | Icon library | Icons drawn in one construction that match the world; filled silhouettes that read at small size |
| Gradient headline text, soft drop shadows, 12–16 px radii, generous padding | Landing-page finish | Hard value steps, outlines or plates where text sits on gameplay, tighter and deliberate spacing |
| Pill-shaped call-to-action buttons | Web button | Game buttons with a distinct focused state and a glyph prompt; often a list row or a plate, not a pill |
| Everything fades in over 300 ms, hover scales 1.05 | CSS habit | Motion with a role: snap for selection, overshoot for reward, none for information read under pressure |

## Missing what makes it a game

| Tell | What to do |
| --- | --- |
| No focus state, no default selection | Decide what is selected when the screen opens and make focus the strongest state on screen |
| No input prompts | Show glyphs for confirm, back, and screen-specific actions, where the anchor puts them |
| Only the default state drawn | Draw the stressed state: low health, full inventory, cannot afford, longest name, new item |
| Placeholder content: "Player1", "Sword of Power", round numbers | Use the game's real names and awkward real numbers |
| The centre of a gameplay HUD is occupied | Keep the middle of the frame for the game; momentary indicators only |
| Four corners filled with equal weight | Rank the information; let one cluster dominate and others recede or hide until needed |
| A HUD that never changes | Elements appear when relevant and quieten when not (out of combat, full health) |
| Rarity as white, green, blue, purple, orange with no second cue | Keep the convention if it helps, and add shape, frame, or icon so colour is not the only carrier |
| Stats as a table or chart panel | Stats as part of the object they describe; deltas next to the thing that changes |

## Flat hierarchy

- Many elements of similar size and weight. A shipped screen has one hero element, a few
  secondary ones, and the rest clearly subordinate. Check with the Squint and Values toggles.
- More than six text sizes, or sizes one or two pixels apart.
- Accent colour on a fifth of the frame. Accents are scarce by definition.
- Symmetry everywhere. Shipped layouts are often weighted to one side.

## No world

- Nothing on the screen could only belong to this game. Remove the title and ask whether the
  screen could be reskinned onto a different game by changing the logo. If yes, it has no
  identity yet.
- Texture, material, and shape language absent: every surface is a flat rectangle.
- Labels in generic UI language ("Inventory", "Confirm") where the game has its own words.
  Keep plain words for anything safety-critical; use the game's voice elsewhere.

## The check before building

State the plan, then ask: would I have produced this same plan for any game in this genre? If
so, find the one decision that only this game would make, and spend the design's boldness
there. Keep the rest quiet.
