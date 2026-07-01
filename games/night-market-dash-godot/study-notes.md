# Godot Reference Study Notes

## Selection Criteria

The reference project should be a high-star Godot project with enough complete game structure to learn from. I screened GitHub by current stars and source completeness, then focused on projects that expose real scene/script/resource organization.

## Projects Checked

| Project | Stars checked | Fit | Notes |
|---|---:|---|---|
| `gdquest-demos/godot-open-rpg` | 2847 | Strong for full-game structure | Complete RPG demo with field/combat separation, UI scenes, cutscene triggers, battle actions, and data resources. Less close mechanically because it is RPG/turn-based and older Godot style. |
| `nezvers/Godot-GameTemplate` | 1606 | Best gameplay fit | Complete top-down shooter reference with rooms, arena entry, enemy waves, spawn markers, projectile system, pickups, damage resources, UI, menus, pause, scene transitions, and pooled instances. |
| `Maaack/Godot-Game-Template` | 1511 | Strong for shell/polish | Godot 4.6 template with main menu, options, pause, credits, loading screen, level state, win/loss windows, and example scenes. Best reference for production shell rather than combat mechanics. |
| `quiver-dev/tiny-wizard-demo` | 46 | Too low for this request | Mechanically close, but star count is too low for the requested benchmark. |

## Main Reference

Primary gameplay reference: <https://github.com/nezvers/Godot-GameTemplate>

It is not just a one-file prototype. The project separates gameplay into reusable systems:

- `addons/top_down/scenes/levels/room_0.tscn`: room scene owns layout, spawn points, arena entry, and enemy manager.
- `addons/top_down/scenes/arena/enemy_manager.tscn`: composes wave manager, spawner, and drop manager.
- `addons/top_down/scripts/arena/SpawnQueueResource.gd`: stores wave lists as data.
- `addons/top_down/scripts/arena/SpawnWaveList.gd`: stores per-wave enemy count and enemy instance list.
- `addons/top_down/scripts/arena/EnemyWaveManager.gd`: advances waves through resources/signals instead of hardcoded if-else in one loop.
- `addons/top_down/scripts/arena/EnemySpawner.gd`: checks active enemy count, safe spawn positions, spawn telegraph VFX, then instantiates enemies.
- `addons/top_down/scripts/weapon_system/projectile/ProjectileSpawner.gd`: handles projectile instancing, spread angles, collision masks, and damage data.
- `addons/top_down/scripts/actor/MoverTopDown2D.gd`: movement is a component with acceleration, collision sliding, push impulses, and axis compensation.
- `addons/top_down/scripts/actor/DashAbility.gd`: dash is its own component with cooldown, active state, push impulse, and afterimage VFX.
- `addons/top_down/scripts/pickups/CollectingPoint.gd`: pickups use a small spawn tween, delayed collision enabling, then attraction/collection feedback.

## What They Do Better Than Our Prototype

1. Scene ownership is clear.
   Our current Godot game is mostly one large `main.gd`. The reference uses rooms, actors, weapons, projectiles, pickups, UI, and arena logic as separate scenes/components.

2. Waves are data-driven.
   Our waves are hardcoded with formulas. The reference uses `SpawnQueueResource` and `SpawnWaveList`, so designers can tune wave composition without editing gameplay code.

3. Spawning is readable.
   Enemies do not appear instantly. The reference creates a spawn mark first, then spawns the enemy after the telegraph exits. It also filters unsafe spawn positions.

4. Runtime state is observable.
   Resources like `fight_mode_resource`, `enemy_count_resource`, `wave_number_resource`, and `remaining_wave_count_resource` let UI and systems react to state changes without tight coupling.

5. Combat entities are compositional.
   Player/enemy behavior is built from components: input, movement, dash, damage, invulnerability visuals, weapons, projectiles, pickups, and VFX.

6. Feedback is intentional.
   Effects are separate instance resources, so impact, spawn mark, afterimage, pickup, and death feedback can be tuned independently.

7. Production shell matters.
   The Maaack template shows the missing outer layer: main menu, options, pause, loading, win/loss windows, credits, level state, and persistent settings.

## What To Apply To Night Market Dash

Next implementation pass should not add more features inside `main.gd`. It should split the prototype into a small but real Godot project structure:

```text
scenes/
  game/game.tscn
  rooms/night_market_room.tscn
  actors/player.tscn
  actors/enemies/drifter.tscn
  actors/enemies/runner.tscn
  actors/enemies/shooter.tscn
  projectiles/charm_bolt.tscn
  projectiles/enemy_bolt.tscn
  pickups/gem.tscn
  ui/hud.tscn
scripts/
  game/game_state.gd
  arena/wave_manager.gd
  arena/spawn_wave.gd
  arena/enemy_spawner.gd
  actors/top_down_mover.gd
  actors/dash_ability.gd
  combat/projectile.gd
  pickups/gem_pickup.gd
resources/
  waves/wave_01.tres
  waves/wave_02.tres
  waves/wave_03.tres
```

## Concrete Refactor Plan

1. Keep the current playable script as a backup reference.
2. Extract player movement and dash into `player.tscn` plus `player.gd`.
3. Extract projectiles into reusable projectile scenes instead of dictionaries.
4. Extract enemies into separate scenes with a shared base script and type-specific behavior.
5. Replace formula waves with resource-like wave definitions.
6. Add spawn telegraphs before enemies appear.
7. Move HUD drawing from `_draw()` into a real `CanvasLayer` UI scene.
8. Keep visual effects small and isolated as individual scenes/resources.
9. Add a minimal pause/restart/menu shell after the core loop is split.

## Immediate Quality Lesson

The high-star projects avoid a common prototype trap: drawing and simulating everything inside one script. Even if the game is small, Godot quality improves when gameplay objects are real scenes with clear responsibilities and tunable exported properties.
