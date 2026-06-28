# AI Games

This repository is the shared home for AI-assisted game prototypes and reusable Codex skills.

## Layout

- `games/`: one directory per game.
- `skills/`: reusable skills, prompts, workflow notes, and Godot-specific conventions learned from projects.

## Game Directory Convention

Each game should live in `games/<game-id>/` and include:

- `README.md`: premise, controls, current status, and how to run it.
- `design.md`: core loop, first-session arc, tuning notes, and playtest findings.
- project files: Godot, web, or other engine files for the playable build.

For Godot games, keep the Godot project root inside the game directory.

## Skill Convention

Reusable skills should live in `skills/<skill-id>/`.

When a project creates a reusable workflow, checklist, Godot pattern, tuning method, or playtest rubric, extract it into `skills/` instead of leaving it buried in a single game.

