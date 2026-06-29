# Night Market Dash Design Notes

## Core Loop

Move through a neon night market arena, dash through danger, auto-fire at nearby enemies, collect gems, choose one upgrade after each cleared wave, and survive three waves to open the exit.

## Quality Target

The first prototype should feel responsive before it feels deep. The player should understand red danger zones, cyan player attacks, gold rewards, and the restart flow without reading a long tutorial.

## First-Session Arc

1. Start in the market center.
2. Learn movement and dash while the first few enemies approach.
3. Notice red telegraphs and use dash invulnerability to escape.
4. Collect gems from defeated enemies.
5. Pick a simple upgrade after clearing a wave.
6. Survive wave three and win, or restart quickly with `R`.

## Tuning Constants

- Player speed: `255`
- Dash velocity: `760`
- Dash duration: `0.15`
- Dash cooldown: `1.5`
- Starting HP: `5`
- Fire rate: `0.42`
- Bullet speed: `520`
- Wave size: `5 + wave * 3`
- Hazard warning: `0.78`
- Hazard active time: `0.34`

## Quality Pass

- Added clear color roles: cyan player/safe actions, red danger, gold rewards.
- Added dash trail, hit bursts, screen shake, pickup attraction, and hit flash.
- Added readable arena blocks and lanes so movement is not an empty room.
- Added compact HUD and overlay states for start, upgrade, win, loss, and restart.

## Playtest Notes

Initial expected risk: wave three may become cluttered if hazard spawns overlap with multiple runners. Next tuning pass should check whether dash cooldown and HP make failures feel explainable rather than random.
