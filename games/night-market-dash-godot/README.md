# Night Market Dash Godot

Godot 4.7 version of the neon night market top-down action prototype.

## Run

```bash
godot --path games/night-market-dash-godot
```

Headless validation:

```bash
godot --headless --path games/night-market-dash-godot --quit
```

## Controls

- `WASD` or arrows: move
- `Space`: dash
- Auto-fire targets the nearest enemy
- `1`, `2`, `3`: choose an upgrade between waves
- `R`: restart

## Current Status

Playable first version with:

- Three-wave survival objective
- Dash movement with invulnerability, trail, and cooldown
- Auto-fire charm bolts against the nearest enemy
- Three enemy roles: drifter, runner, and shooter
- Enemy projectiles from shooter masks
- Red hazard telegraphs
- Gold gem drops with attraction
- Between-wave upgrades that change fire rate, damage, magnet range, dash cooldown, and HP
- Win/loss states and fast restart

## Verified

```bash
godot --headless --path games/night-market-dash-godot --quit
```
