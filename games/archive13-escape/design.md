# Archive 13 Escape Design

## Concept

Working title: Archive 13 Escape.

Hook: explore a compact 3D archive room where every solved object changes the room and reveals that the player is the erased subject A-013.

Target player: mobile or desktop players who like short escape rooms, readable clue chains, and light narrative mystery. The prototype should teach through staged object focus, not a wall of instructions.

Platform and session: Godot 4 desktop first, Android/web export later. First-session target is 8-12 minutes.

## Experience Pillars

- Physical room first: the player should feel they are operating objects in a room, not reading a menu.
- One active goal: the room reveals and highlights only what matters for the current step.
- Visible consequence: lights, projection, cabinet doors, terminal color, and door access state must change after progress.
- Mystery escalation: each gate should explain a little more about A-013 and the reset loop.
- Fast recovery: wrong inputs teach a rule and keep the player moving.

## Level Structure

Map topology: single-room hub with four readable landmarks.

- Desk zone: lamp, calendar, numbering card, terminal.
- Cabinet zone: iron cabinet and fuse box.
- Projector zone: projector, screen, and report table.
- Memory zone: photo wall, color lock, memory cabinet, memory core.
- Exit zone: main door and access light.

Beat sequence:

1. Introduction: dark room, only the lamp is the obvious safe interaction.
2. Safe clue reading: calendar and numbering card teach the `217` code.
3. First gate: cabinet opens and adds the first physical reward.
4. State change: fuse restores projector power and makes the room visibly different.
5. Midpoint puzzle: projected page shadows guide the report reconstruction.
6. Combined test: photo-wall color order unlocks the memory cabinet.
7. Narrative reveal: terminal rejects an employee name, then accepts `A-013`.
8. Exit: door light turns green and the player chooses a recovery ending.

## UX Flow

First-time flow:

- Launch directly into the room.
- The guide panel names the current objective.
- `Space`/button focuses the camera on the target.
- Wrong or premature clicks give a short reason, not a generic failure.
- Inventory and clue log summarize what has been discovered.

HUD:

- Top: chapter title and reset timer.
- Bottom-left: current objective and focus button.
- Right: inventory and recent clue log.
- Center: crosshair for click targeting.
- Modal panel: only appears for focused puzzle decisions.

Controls:

- `WASD` movement and right-drag mouse look.
- Left click interaction.
- `Space` to reorient toward the current target.
- Touch fallback: on-screen movement arrows and turn buttons.

## Tuning Constants

- `LOOP_SECONDS`: 780 seconds. Atmospheric timer only for this prototype.
- `PLAYER_SPEED`: 3.2. Fast enough for a single room without feeling floaty.
- `MOUSE_SENS`: 0.004. Conservative default for desktop mouse.
- Camera focus blend: intentionally quick so players can recover orientation.

## Playtest Notes

Validated by scripted smoke:

- Full progress path reaches the ending.
- Calendar and rule card are both recorded before cabinet progression.
- Wrong cabinet input, report order, color order, and terminal input are all tested.
- Wrong terminal input teaches "权限主体不能删除外部对象".
- The terminal unlocks the door and final choice completes the chapter.

Current self-assessment:

- Correctness: 9.3. Headless scene load and scripted full playthrough pass with wrong-path coverage.
- Guidance clarity: 9.1. One active objective, object labels, camera focus, touch controls, and premature-click feedback are implemented.
- 3D game feel: 9.0. Movement, look, clicking, lighting, staged puzzle input, procedural audio cues, room-clickable fragments/buttons, and object-state changes exist; richer physical manipulation is the next bar.
- Visual quality: 8.6. Archive shelves, floor cables, warning strips, projector markings, lighting, and state displays improve room presence, but assets are still procedural.
- Fun and narrative pull: 8.9. The room develops through light, code, projection, report, memory core, terminal, and exit; puzzle tactility is better but not final.

Not accepted as a final 9+ game across every dimension yet. The next tuning pass should add drag/slot physical manipulation, export presets, and authored meshes/materials.
