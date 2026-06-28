---
name: godot-game-prototyper
description: Build and iterate playable Godot 4 game prototypes with GDScript, scenes, input, UI, restart flow, tuning constants, and playtest verification. Use when Codex needs to create a new Godot game, add mechanics to an existing Godot project, improve Godot game feel, structure one-game-per-directory projects, run Godot headless checks, or prepare a Godot prototype for desktop or web export.
---

# Godot Game Prototyper

## Overview

Use Godot 4 as the default engine for new AI Games repository prototypes unless the user requests another stack. Prioritize a complete playable loop over feature count: control, challenge, feedback, failure or win, fast restart, and one tuning pass.

## Repository Placement

- Put each new game in `games/<game-id>/`.
- Put the Godot project root directly inside that game directory unless there is a strong reason to nest it.
- Include `README.md` with premise, controls, run command, and current status.
- Include `design.md` with core loop, first-session arc, tuning constants, and playtest notes.
- Extract reusable Godot workflows, checklists, or patterns into `skills/` instead of leaving them buried in one game.

## Workflow

1. Define the smallest loop before coding: player action, obstacle or decision, reward or loss, feedback, and restart.
2. Create the Godot project with `project.godot`, `scenes/`, `scripts/`, and asset folders only when needed.
3. Implement one playable screen first. Add menus, progression, and content only after the loop is fun enough to repeat.
4. Keep tuning constants near the top of scripts or in a dedicated config resource: movement, gravity, cooldowns, spawn rates, health, scoring, timers, and camera shake.
5. Build complete states: ready, playing, paused when useful, won or lost, and restart.
6. Add immediate feedback for input, pickups, hits, damage, scoring, cooldowns, death, victory, and disabled actions.
7. Run Godot locally or headless after changes; fix parser, scene load, and import errors before reporting completion.
8. Playtest the first 60 seconds as a first-time player and tune controls, readability, difficulty, and restart speed.

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

## Validation

Run the strongest practical checks before completion:

- `godot --headless --path <game-dir> --quit` for scene and script load validation.
- `godot --path <game-dir>` when a visible editor/player check is needed and the environment supports GUI.
- Web or desktop export checks when the user asks for a distributable build.
- Playtest desktop and mobile-sized viewports for web games.

Report what was verified and what was not verified. If GUI playtesting is unavailable, say so and still run headless checks.

## Playability Bar

Do not treat a Godot project as done just because it launches. Before finalizing, check:

- The player knows what to do within one screen of interaction.
- Controls respond immediately and predictably.
- The first failure feels explainable, not random.
- Restart is one key or one button and returns to play quickly.
- Rewards change score, capability, risk, route choice, or player expression.
- Difficulty increases through decisions before raw speed, health, or enemy count.
- UI text fits and does not cover important play space.

## Handoff Format

When reporting completed Godot work, include:

- Game directory and main scene.
- What is playable now.
- Controls.
- Main tuning constants or risks.
- Validation commands run.
- Known gaps or next tuning pass.
