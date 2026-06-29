# Night Market Dash Godot Design

## Core Loop

Move through a compact night market arena, dash through red warning zones, auto-fire at nearby enemies, collect gold gems, pick a small upgrade between waves, and survive three waves.

## Quality Target

This version is intentionally simple, but it must feel like a game rather than a moving dot. The key readability rules are cyan for player/actions, red for danger, gold for rewards, and one-key restart.

After playtest feedback, visual readability takes priority over spectacle. Background detail should stay low contrast, red should only mean real danger, and hit effects should confirm events without filling the screen.

## Playable Features

- Drifters pressure the player steadily.
- Runners close distance quickly and force dash timing.
- Shooters keep range and fire slow red projectiles.
- Hazards use a warning phase before becoming dangerous.
- Upgrade choices are immediate and persistent for the run:
  - Faster charms reduce fire cooldown.
  - Harder hits increase damage and gem magnet range.
  - Shorter dash reduces cooldown and heals one HP.

## Tuning Constants

- Player speed: `260`
- Dash speed: `820`
- Dash duration: `0.14`
- Base dash cooldown: `1.35`
- Base fire rate: `0.36`
- Bullet speed: `560`
- Starting HP: `5`
- Wave size after readability pass: `4 + wave * 2`
- Max simultaneous hazards: `2`
- Hazard warning time: `0.95`
- Hazard active time: `0.28`
- Shooter projectile speed: `240`

## Quality Pass

- Added screen shake, dash trail, hit particles, gem attraction, and hazard telegraphs.
- Added arena blockers so the scene has lanes and combat pockets.
- Added start, upgrade, win, loss, and restart states.
- Added a shooter enemy and enemy projectiles so later waves change behavior, not just enemy count.
- Made upgrades persist and show in the HUD.
- Reduced background grid contrast and frequency.
- Reduced room and stall border brightness so gameplay objects stand out.
- Limited hazard count and lowered hazard spawn rate.
- Reduced screen shake, particle count, particle lifetime, and enemy projectile size.
- Increased player radius for better readability.

## Validation

Passed:

```bash
godot --headless --path games/night-market-dash-godot --quit
```

## Next Pass

Replace script-drawn primitives with small authored sprites, add one boss-like exit encounter, and tune wave three after real playtesting.
