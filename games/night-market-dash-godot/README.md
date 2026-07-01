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
- Hold left mouse button: manual aim/fire toward cursor
- Release mouse: auto-fire targets the nearest enemy as a fallback
- `1`, `2`, `3`: choose an upgrade between waves
- `R`: restart

## Current Status

Playable first version with:

- Three-wave survival objective
- Dash movement with invulnerability, trail, and cooldown
- Manual charm-bolt shooting with auto-fire fallback
- Data-style wave plan with named waves
- Enemy spawn telegraphs before enemies appear
- Four enemy roles: drifter, runner, shooter, and final-wave brute
- Enemy projectiles from shooter masks
- Red hazard telegraphs
- Gold gem drops with attraction
- Between-wave upgrades that change fire rate, damage, magnet range, dash cooldown, and HP
- Win/loss states and fast restart

## Verified

```bash
godot --headless --path games/night-market-dash-godot --quit
```
