# AI女友 Design Notes

## Core Loop

Explore a compact 2D space, notice a prompt from Linqi or the environment, move close enough to interact, then unlock a memory, ability, or new destination. The loop should stay readable on a phone: move, approach, interact, see an immediate relationship or quest change.

## First Session Arc

1. Start in the apartment beside Linqi.
2. Learn movement by walking to her.
3. Leave the apartment and pick up the paper plane.
4. Unlock dash and cross the street section.
5. Reach the park bench and fountain.
6. Unlock photo mode and return the memory to the room.

## Current Tuning Notes

- The project is structured like a lightweight Godot scene tree: root scene, world scene, and UI scene are separated in `src/scene-tree.js` and composed from `src/app.js`.
- The UI should stay quiet and compact. Large floating panels, oversized buttons, and decorative HUD blocks make the game feel like a prototype instead of a scene.
- Mobile layout is the priority. The touch controls, prompt bar, and dialogue sheet must not fight for the same lower-screen space.
- Chinese font fallback matters for screenshots and Android WebView; `src/styles.css` keeps CJK fonts ahead of generic system fonts.

## Playtest Rubric

- Visual composition: background, characters, HUD hierarchy, and empty space.
- Character presence: Linqi and the player must read clearly against the scene.
- Interaction clarity: the next action should be understandable without tutorial text.
- Mobile ergonomics: joystick, interact, dash, and photo controls should be reachable without blocking the scene.
- Technical reliability: `npm test` and Android `assembleRelease` should pass before packaging.
