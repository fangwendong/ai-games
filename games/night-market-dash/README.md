# Night Market Dash

A small browser-playable prototype for the selected "neon night market top-down action roguelite" direction.

## Run

From this directory:

```bash
python3 -m http.server 4173
```

Then open `http://127.0.0.1:4173/`.

The game is also a single static HTML file, so opening `index.html` directly works in most browsers.

## Controls

- `WASD` or arrow keys: move
- `Space`: dash
- Auto-fire targets the nearest enemy
- `1`, `2`, `3`: choose an upgrade between waves
- `R`: restart

## Current Status

Playable first-pass prototype:

- Three waves
- Short dash with invulnerability and trail
- Auto-fire charm bolts
- Two enemy behaviors
- Red hazard telegraphs
- Gem pickups with attraction
- Between-wave upgrades
- Win/loss and fast restart
