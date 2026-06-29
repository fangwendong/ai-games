extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var packed: PackedScene = load("res://scenes/main.tscn")
	var game: Node = packed.instantiate()
	root.add_child(game)
	await process_frame
	await process_frame

	_assert_eq(game.state["step"], "lamp", "initial objective")
	game._handle_interaction("lamp")
	game._run_action("step_clues")
	_assert_true(game.state["lamp_on"], "lamp lights the room")
	_assert_eq(game.state["step"], "clues", "lamp advances to clue step")

	game._handle_interaction("calendar")
	game._run_action("close")
	game._handle_interaction("rule_card")
	game._run_action("step_cabinet")
	_assert_true(game.state["calendar_seen"], "calendar clue recorded")
	_assert_true(game.state["rule_seen"], "rule clue recorded")
	_assert_eq(game.state["step"], "cabinet", "clues advance to cabinet")

	game._handle_interaction("cabinet")
	game._run_action("lock_inc_0")
	game._run_action("lock_submit")
	_assert_true(not game.state["cabinet_open"], "wrong lock code stays closed")
	game._run_action("lock_inc_0")
	game._run_action("lock_inc_1")
	for i in range(7):
		game._run_action("lock_inc_2")
	game._run_action("lock_submit")
	_assert_true(game.state["cabinet_open"], "cabinet opens")
	_assert_eq(game.state["step"], "fuse", "cabinet advances to fuse")

	game._handle_interaction("fuse_box")
	game._run_action("projector_on")
	_assert_true(game.state["projector_on"], "projector powers on")
	_assert_eq(game.state["step"], "report", "fuse advances to report")

	game._handle_interaction("report_table")
	game._run_action("report_piece_2")
	_assert_eq(game.report_slots.size(), 0, "wrong report order resets")
	for piece in [1, 2, 3, 4, 5, 6]:
		game._run_action("report_piece_%d" % piece)
	_assert_true(game.state["report_solved"], "report solves")
	_assert_eq(game.state["step"], "case", "report advances to case")

	game._handle_interaction("photo_wall")
	game._run_action("step_case")
	game._handle_interaction("memory_case")
	game._run_action("color_red")
	_assert_eq(game.color_input.size(), 0, "wrong color order resets")
	for color in ["blue", "green", "yellow", "red"]:
		game._run_action("color_" + color)
	_assert_true(game.state["case_open"], "case opens")
	_assert_eq(game.state["step"], "core", "case advances to core")

	game._handle_interaction("memory_core")
	_assert_true(game.state["core_taken"], "core collected")
	_assert_eq(game.state["step"], "terminal", "core advances to terminal")

	game._handle_interaction("terminal")
	game._run_action("terminal_wrong")
	_assert_true(game.state["notes"].has("终端拒绝沈蓝：权限主体不能删除外部对象。"), "wrong terminal attempt teaches rule")
	game._run_action("terminal_unlock")
	_assert_true(game.state["terminal_unlocked"], "terminal unlocks")
	_assert_eq(game.state["step"], "door", "terminal advances to door")

	game._handle_interaction("door")
	game._run_action("ending_all")
	_assert_true(game.state["door_open"], "door opens")
	_assert_eq(game.state["ending"], "恢复所有人", "ending selected")

	print("ARCHIVE13_SMOKE_PASS")
	quit(0)


func _assert_true(value: bool, label: String) -> void:
	if not value:
		push_error("Smoke failed: " + label)
		quit(1)


func _assert_eq(actual: Variant, expected: Variant, label: String) -> void:
	if actual != expected:
		push_error("Smoke failed: " + label + " expected=%s actual=%s" % [str(expected), str(actual)])
		quit(1)
