---
name: godot-game-prototyper
description: Build and iterate playable Godot 4 game prototypes with GDScript, scenes, input, UI, restart flow, tuning constants, and playtest verification. Use when Codex needs to create a new Godot game, add mechanics to an existing Godot project, improve Godot game feel, structure one-game-per-directory projects, run Godot headless checks, or prepare a Godot prototype for desktop or web export.
---

# Godot Game Prototyper

## Overview

Use Godot 4 as the default engine for new AI Games repository prototypes unless the user requests another stack. The goal is a small but polished playable prototype, not a scene that merely launches. Prioritize a complete playable loop over feature count: control, challenge, feedback, failure or win, fast restart, and at least one tuning pass based on an actual first-minute playtest.

## Repository Placement

- Put each new game in `games/<game-id>/`.
- Put the Godot project root directly inside that game directory unless there is a strong reason to nest it.
- Include `README.md` with premise, controls, run command, and current status.
- Include `design.md` with core loop, first-session arc, tuning constants, and playtest notes.
- Extract reusable Godot workflows, checklists, or patterns into `skills/` instead of leaving them buried in one game.

## Workflow

1. Define the smallest loop before coding: player action, obstacle or decision, reward or loss, feedback, and restart.
2. Write a short quality target in `design.md`: the intended feel, visual read, difficulty curve, and what "good enough for a first playtest" means.
3. Create the Godot project with `project.godot`, `scenes/`, `scripts/`, and asset folders only when needed.
4. Implement one playable screen first. Add menus, progression, and content only after the loop is fun enough to repeat.
5. Keep tuning constants near the top of scripts or in a dedicated config resource: movement, gravity, cooldowns, spawn rates, health, scoring, timers, and camera shake.
6. Build complete states: ready, playing, paused when useful, won or lost, and restart.
7. Add immediate feedback for input, pickups, hits, damage, scoring, cooldowns, death, victory, and disabled actions.
8. Add presentation pass before calling the prototype done: camera framing, screen shake where useful, hit flash, readable contrast, spacing, UI hierarchy, and audio or visual substitutes for key events.
9. Run Godot locally or headless after changes; fix parser, scene load, and import errors before reporting completion.
10. Playtest the first 60 seconds as a first-time player and tune controls, readability, difficulty, and restart speed.

## Godot Conventions

- Use Godot 4 and GDScript by default.
- Prefer simple scene composition over large monolithic scripts once there are multiple entities.
- Use `Node2D`, `CharacterBody2D`, `Area2D`, `CollisionShape2D`, `CanvasLayer`, and `Control` nodes according to their engine roles.
- Use project input actions instead of checking raw key codes throughout gameplay scripts.
- Use delta-time movement for frame-rate independence.
- Keep collision layers, masks, and group names explicit and documented in code when they affect gameplay.
- Avoid text-heavy tutorial screens. Teach with layout, timing, safe first interactions, and clear UI affordances.
- Use generated placeholder shapes or simple sprites early; do not block core gameplay on final art.

## Required Prototype Features

For a new playable prototype, include:

- Clear objective visible during play or obvious from the first interaction.
- Keyboard controls; add touch controls when targeting browser or mobile.
- Fast restart from failure and victory.
- Score, timer, health, wave, distance, or another pressure indicator when useful.
- Tuning constants that can be changed without hunting through unrelated code.
- A `README.md` run command, usually `godot --path <game-dir>`.
- A `design.md` note explaining what should be tuned next.
- A concise "quality pass" section in `design.md` listing what was improved after initial implementation.

## Minimum Quality Bar

Before reporting completion, the game must satisfy all of these unless the user explicitly asked for a throwaway sketch:

- It has a beginning, a pressure phase, a success or failure outcome, and a fast restart without editor intervention.
- The first 10 seconds communicate the objective through layout, motion, UI, or a short in-world prompt.
- Every important action produces feedback within the same frame or the next visible moment.
- The main character or cursor feels responsive: no accidental input lag, uncontrolled drift, or unclear collision bounds.
- The play space is readable at a glance. Hazards, rewards, player, exits, and UI are visually distinct by color, shape, motion, or layering.
- Difficulty ramps through learnable patterns, placement, timing, or decisions before relying on raw speed or clutter.
- UI does not cover the active play area and text fits at desktop and common mobile/web viewport sizes if web export is relevant.
- Restart takes one key or button and returns to the active loop quickly.

## Presentation Pass

Use simple assets, but make them intentional. A prototype may use primitive shapes, yet it should not look accidental.

- Use a restrained palette with strong contrast between player, danger, reward, and background.
- Add small animations or tweens for spawn, pickup, hit, death, victory, menu transitions, and button focus.
- Use camera follow, look-ahead, shake, zoom pulse, or freeze frame only where it improves readability or impact.
- Add particles or simple burst shapes for hits, pickups, and destruction when those events matter.
- Keep UI compact and purposeful: objective, score or timer, health/status, restart affordance, and state messages.
- Avoid oversized text overlays during action unless the game is paused or ended.

## First-Minute Playtest Rubric

After implementation, play or simulate the first minute and record notes in `design.md`:

- What did the player do first, and was that the intended action?
- Was the first failure or success explainable?
- Did any UI, obstacle, or effect hide important information?
- Which tuning constant changed after the playtest, and why?
- What is the next single improvement that would most improve the feel?

## Validation

Run the strongest practical checks before completion:

- `godot --headless --path <game-dir> --quit` for scene and script load validation.
- `godot --path <game-dir>` when a visible editor/player check is needed and the environment supports GUI.
- Web or desktop export checks when the user asks for a distributable build.
- Playtest desktop and mobile-sized viewports for web games.

Report what was verified and what was not verified. If GUI playtesting is unavailable, say so and still run headless checks.

If the environment allows screenshots or recordings, capture at least one gameplay screenshot after the presentation pass and inspect it before final reporting. Check that the game is not blank, misframed, covered by UI, or visually confusing.

## Playability Bar

Do not treat a Godot project as done just because it launches. Before finalizing, check:

- The player knows what to do within one screen of interaction.
- Controls respond immediately and predictably.
- The first failure feels explainable, not random.
- Restart is one key or one button and returns to play quickly.
- Rewards change score, capability, risk, route choice, or player expression.
- Difficulty increases through decisions before raw speed, health, or enemy count.
- UI text fits and does not cover important play space.

## Common Failure Modes To Avoid

- A player sprite moving in an empty room with no objective, timer, score, enemy, pickup, exit, or fail state.
- Random spawning that creates unavoidable hits or instant failures.
- Placeholder UI that explains the game in paragraphs instead of making the first action obvious.
- Tiny collision shapes or visuals that do not match the actual hitboxes.
- Tuning values scattered through scripts, making iteration slow.
- Reporting "done" after a parser check without a first-minute playtest or quality pass.

## Handoff Format

When reporting completed Godot work, include:

- Game directory and main scene.
- What is playable now.
- Controls.
- Main tuning constants or risks.
- Validation commands run.
- Known gaps or next tuning pass.
