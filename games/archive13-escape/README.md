# Archive 13 Escape

Godot 4.7 3D escape-room prototype for the AI Games repository.

## Premise

The player wakes inside Archive Room 13 during a reset loop. The room is a compact 3D space: objects change state, lights power on, projection clues appear, cabinets open, and the final door unlocks only after the player reconstructs the erased identity A-013.

## Run

From this worktree:

```bash
/home/fwd/.local/bin/godot --path games/archive13-escape
```

Headless validation:

```bash
/home/fwd/.local/bin/godot --headless --path games/archive13-escape --quit
/home/fwd/.local/bin/godot --headless --path games/archive13-escape --script res://test/smoke.gd
```

Expected smoke output:

```text
ARCHIVE13_SMOKE_PASS
```

## Controls

- `WASD`: move within the room.
- Hold right mouse and drag: look around.
- Left click: interact with highlighted 3D objects.
- `Space` or the on-screen button: look toward the current objective.
- Touch UI: on-screen movement arrows and turn buttons.
- On-screen choices: solve focused puzzle gates.

## Playable Loop

1. Turn on the desk lamp.
2. Read the calendar and numbering card.
3. Open the iron cabinet with code `217`.
4. Restore projector power with the spare fuse.
5. Reconstruct the deletion report from projected page shadows.
6. Use the photo-wall color order to open the memory cabinet.
7. Collect the memory core and authenticate the terminal as `A-013`.
8. Unlock the door and choose the recovery ending.

## Current Status

- Independent Godot project at `games/archive13-escape/`.
- Procedural 3D room with desk, cabinet, projector wall, archive shelving, floor cables, photo wall, memory cabinet, terminal, and door.
- Stage-based objective guidance, camera focus, inventory, clue log, feedback toasts, object labels, touch controls, procedural audio cues, and state animations.
- Interactive puzzle flow now mixes panels and direct room objects: digit wheels for `217`, clickable report fragments on the table, and clickable color buttons on the cabinet.
- Scripted smoke test covers wrong and correct paths for the cabinet, report, color lock, terminal, and ending.

## Known Gaps

- Visual assets are still procedural prototype geometry, not authored final art.
- Audio is procedural and only used for feedback cues; Android export presets are not implemented yet.
- Puzzle gates now have staged interaction and 3D state displays, with report fragments and color buttons clickable directly in the room. It still stops short of full drag-and-drop physical manipulation.
