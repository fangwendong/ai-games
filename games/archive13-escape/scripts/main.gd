extends Node3D

const LOOP_SECONDS := 13 * 60
const PLAYER_SPEED := 3.2
const MOUSE_SENS := 0.004
const LOCK_CODE := [2, 1, 7]
const REPORT_SOLUTION := [1, 2, 3, 4, 5, 6]
const COLOR_SOLUTION := ["blue", "green", "yellow", "red"]

var state := {
	"step": "lamp",
	"remaining": LOOP_SECONDS,
	"lamp_on": false,
	"calendar_seen": false,
	"rule_seen": false,
	"cabinet_open": false,
	"fuse_taken": false,
	"projector_on": false,
	"report_solved": false,
	"case_open": false,
	"core_taken": false,
	"terminal_ready": false,
	"terminal_unlocked": false,
	"door_open": false,
	"ending": "",
	"notes": [],
	"items": []
}

var steps := [
	{"id": "lamp", "title": "打开台灯", "target": "lamp", "zone": "desk", "hint": "房间太暗，先找到桌上的暖色光源。"},
	{"id": "clues", "title": "读懂柜锁", "target": "calendar", "zone": "desk", "hint": "查看日历和编号卡，用线索推算铁柜密码。"},
	{"id": "cabinet", "title": "打开铁柜", "target": "cabinet", "zone": "cabinet", "hint": "把推算出的 217 输进三位数字锁。"},
	{"id": "fuse", "title": "恢复投影电源", "target": "fuse_box", "zone": "projector", "hint": "从铁柜取出保险丝，插回投影电箱。"},
	{"id": "report", "title": "复原删除报告", "target": "report_table", "zone": "projector", "hint": "按投影出来的页码顺序重排碎片。"},
	{"id": "case", "title": "解锁记忆柜", "target": "memory_case", "zone": "case", "hint": "按照片墙亮起的颜色顺序操作柜门。"},
	{"id": "core", "title": "取出记忆核心", "target": "memory_core", "zone": "case", "hint": "拿起发光核心，准备接入终端。"},
	{"id": "terminal", "title": "终端认证", "target": "terminal", "zone": "desk", "hint": "把记忆核心接入终端，识别第一个被删除的主体。"},
	{"id": "door", "title": "离开档案室", "target": "door", "zone": "door", "hint": "门禁已解除，选择恢复策略并离开。"}
]

var camera: Camera3D
var player_pos := Vector3(0, 1.65, 5.3)
var yaw := 0.0
var pitch := -0.12
var focus_pos := Vector3.ZERO
var focus_look := Vector3.ZERO
var focus_blend := 0.0
var right_dragging := false
var touch_move := Vector2.ZERO
var touch_turn := 0.0
var lock_digits := [0, 0, 0]
var report_slots := []
var color_input := []
var objects := {}
var tags := {}
var active_panel: PanelContainer
var panel_title: Label
var panel_body: Label
var panel_actions: VBoxContainer
var objective_title: Label
var objective_hint: Label
var timer_label: Label
var log_label: Label
var inventory_label: Label
var toast_label: Label
var crosshair: Label
var floor_light: OmniLight3D
var lamp_light: OmniLight3D
var projector_light: SpotLight3D
var door_light: MeshInstance3D
var cabinet_door: MeshInstance3D
var case_glass: MeshInstance3D
var terminal_screen: MeshInstance3D
var projection_label: Label3D
var cabinet_display: Label3D
var report_display: Label3D
var color_display: Label3D
var report_piece_nodes := {}
var color_button_nodes := {}
var touch_buttons := []
func _ready() -> void:
	RenderingServer.set_default_clear_color(Color("#050b12"))
	_ensure_input_actions()
	_build_room()
	_build_ui()
	_focus_zone("desk", true)
	_update_step_ui()
	set_process(true)


func _process(delta: float) -> void:
	state["remaining"] = max(0, state["remaining"] - delta)
	_update_player(delta)
	_update_camera(delta)
	_update_guidance()
	_update_ui()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT:
			right_dragging = event.pressed
		elif event.button_index == MOUSE_BUTTON_LEFT and event.pressed and not active_panel.visible:
			_interact_from_screen(event.position)
	elif event is InputEventMouseMotion and right_dragging:
		yaw -= event.relative.x * MOUSE_SENS
		pitch = clamp(pitch - event.relative.y * MOUSE_SENS, -0.9, 0.35)


func _ensure_input_actions() -> void:
	var actions := {
		"move_forward": KEY_W,
		"move_back": KEY_S,
		"move_left": KEY_A,
		"move_right": KEY_D,
		"focus_target": KEY_SPACE
	}
	for action in actions.keys():
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		var ev := InputEventKey.new()
		ev.physical_keycode = actions[action]
		InputMap.action_add_event(action, ev)


func _build_room() -> void:
	var world := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("#050b12")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("#5d7288")
	env.ambient_light_energy = 0.28
	env.fog_enabled = true
	env.fog_density = 0.028
	env.fog_light_color = Color("#0b121c")
	world.environment = env
	add_child(world)

	camera = Camera3D.new()
	camera.name = "PlayerCamera"
	camera.fov = 64
	camera.near = 0.05
	add_child(camera)

	floor_light = OmniLight3D.new()
	floor_light.name = "ColdCeilingLight"
	floor_light.light_energy = 1.35
	floor_light.omni_range = 9.5
	floor_light.position = Vector3(0, 4.2, 0)
	add_child(floor_light)

	lamp_light = OmniLight3D.new()
	lamp_light.name = "DeskLampLight"
	lamp_light.light_color = Color("#ffd27a")
	lamp_light.light_energy = 0.25
	lamp_light.omni_range = 4.0
	lamp_light.position = Vector3(-2.6, 1.7, 1.1)
	add_child(lamp_light)

	projector_light = SpotLight3D.new()
	projector_light.name = "ProjectorBeam"
	projector_light.light_color = Color("#8ad7ff")
	projector_light.light_energy = 0.0
	projector_light.spot_range = 6.0
	projector_light.spot_angle = 28
	projector_light.position = Vector3(0.1, 1.35, 2.0)
	add_child(projector_light)
	projector_light.look_at(Vector3(0.2, 2.0, -3.75), Vector3.UP)

	_add_box("floor", Vector3(9.4, 0.12, 8.4), Vector3(0, -0.06, 0), Color("#101923"), false)
	_add_box("back_wall", Vector3(9.4, 4.6, 0.18), Vector3(0, 2.25, -3.9), Color("#172535"), false)
	_add_box("left_wall", Vector3(0.18, 4.6, 8.4), Vector3(-4.7, 2.25, 0), Color("#141f2d"), false)
	_add_box("right_wall", Vector3(0.18, 4.6, 8.4), Vector3(4.7, 2.25, 0), Color("#141f2d"), false)
	_add_box("ceiling", Vector3(9.4, 0.14, 8.4), Vector3(0, 4.55, 0), Color("#0d1621"), false)

	_make_desk_zone()
	_make_cabinet_zone()
	_make_projector_zone()
	_make_case_zone()
	_make_door_zone()
	_make_room_dressing()


func _make_desk_zone() -> void:
	_add_box("desk_top", Vector3(4.9, 0.25, 1.65), Vector3(-1.25, 1.02, 1.45), Color("#29231d"), false)
	_add_box("desk_body", Vector3(4.65, 0.82, 1.35), Vector3(-1.25, 0.54, 1.45), Color("#17181b"), false)
	_add_interactive("lamp", "台灯", Vector3(-3.0, 1.18, 1.1), _make_lamp(), Vector3(0.85, 1.2, 0.85))
	_add_interactive("calendar", "07/13", Vector3(-1.95, 1.19, 1.02), _flat_box("calendar_card", Vector3(0.78, 0.05, 0.58), Color("#d6c493")), Vector3(0.9, 0.35, 0.75))
	_add_interactive("rule_card", "编号卡", Vector3(0.05, 1.2, 1.03), _flat_box("rule_card_mesh", Vector3(0.86, 0.05, 0.58), Color("#d8dde5")), Vector3(0.95, 0.35, 0.75))
	_add_interactive("terminal", "终端", Vector3(1.45, 1.18, 0.92), _make_terminal(), Vector3(1.25, 0.85, 0.85))


func _make_cabinet_zone() -> void:
	var cabinet := Node3D.new()
	cabinet.add_child(_box_child("body", Vector3(1.35, 2.35, 0.72), Vector3.ZERO, Color("#25313d")))
	cabinet_door = _box_child("door", Vector3(1.18, 2.05, 0.1), Vector3(0, 0.03, -0.43), Color("#31404d"))
	cabinet.add_child(cabinet_door)
	cabinet.add_child(_box_child("keypad", Vector3(0.28, 0.42, 0.08), Vector3(0.42, 0.16, -0.52), Color("#111821"), Color("#ffd27a"), 0.55))
	cabinet_display = Label3D.new()
	cabinet_display.text = "000"
	cabinet_display.font_size = 42
	cabinet_display.modulate = Color("#ffd27a")
	cabinet_display.outline_size = 6
	cabinet_display.outline_modulate = Color("#111821")
	cabinet_display.position = Vector3(0.04, 0.52, -0.56)
	cabinet.add_child(cabinet_display)
	_add_interactive("cabinet", "铁柜", Vector3(-3.55, 1.22, -1.45), cabinet, Vector3(1.45, 2.6, 1.0))
	_add_interactive("fuse_box", "电箱", Vector3(-3.8, 1.35, -2.9), _make_fuse_box(), Vector3(1.0, 1.1, 0.7))


func _make_projector_zone() -> void:
	_add_box("screen_panel", Vector3(2.4, 1.35, 0.08), Vector3(0.15, 2.05, -3.8), Color("#d6dde5"), false)
	projection_label = Label3D.new()
	projection_label.text = ""
	projection_label.font_size = 42
	projection_label.modulate = Color("#102536")
	projection_label.outline_size = 6
	projection_label.outline_modulate = Color("#c4e7ff")
	projection_label.position = Vector3(0.15, 2.08, -3.86)
	add_child(projection_label)
	report_display = Label3D.new()
	report_display.text = "_ _ _\n_ _ _"
	report_display.font_size = 32
	report_display.modulate = Color("#d8dde5")
	report_display.outline_size = 5
	report_display.outline_modulate = Color("#101923")
	report_display.position = Vector3(1.4, 1.62, 1.55)
	report_display.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	add_child(report_display)
	_add_interactive("projector", "投影机", Vector3(-0.2, 1.13, 1.95), _make_projector(), Vector3(1.2, 0.6, 0.8))
	_add_interactive("report_table", "碎片台", Vector3(1.4, 1.15, 1.55), _make_report_table(), Vector3(1.4, 0.55, 1.0))
	_add_report_piece_objects()


func _make_case_zone() -> void:
	_add_interactive("photo_wall", "照片墙", Vector3(2.65, 2.35, -3.78), _make_photo_wall(), Vector3(2.0, 1.2, 0.45))
	var case := Node3D.new()
	case.add_child(_box_child("case_body", Vector3(1.15, 2.0, 0.72), Vector3.ZERO, Color("#17212c")))
	case_glass = _box_child("glass", Vector3(0.96, 1.56, 0.06), Vector3(0, 0.04, -0.42), Color(0.55, 0.85, 1.0, 0.45), Color("#207ea5"), 0.25)
	case.add_child(case_glass)
	case.add_child(_box_child("color_lock", Vector3(0.82, 0.16, 0.08), Vector3(0, -0.88, -0.5), Color("#111821"), Color("#7fc9ff"), 0.45))
	color_display = Label3D.new()
	color_display.text = "_ _ _ _"
	color_display.font_size = 30
	color_display.modulate = Color("#d8dde5")
	color_display.outline_size = 6
	color_display.outline_modulate = Color("#111821")
	color_display.position = Vector3(0, -0.62, -0.52)
	case.add_child(color_display)
	_add_color_button_objects(case)
	_add_interactive("memory_case", "记忆柜", Vector3(3.35, 1.25, -1.3), case, Vector3(1.35, 2.35, 1.0))
	_add_interactive("memory_core", "记忆核心", Vector3(3.35, 1.7, -1.55), _make_memory_core(), Vector3(0.7, 0.7, 0.7))


func _make_door_zone() -> void:
	var door := Node3D.new()
	door.add_child(_box_child("slab", Vector3(1.55, 2.9, 0.18), Vector3.ZERO, Color("#111821")))
	door_light = _box_child("access_light", Vector3(0.18, 0.42, 0.07), Vector3(0.58, -0.2, -0.14), Color("#ff6570"), Color("#7b1218"), 0.85)
	door.add_child(door_light)
	_add_interactive("door", "主门", Vector3(0.3, 1.48, -3.76), door, Vector3(1.8, 3.1, 0.65))


func _make_room_dressing() -> void:
	for shelf_index in range(3):
		var y := 0.85 + float(shelf_index) * 0.68
		_add_box("left_shelf_%d" % shelf_index, Vector3(0.12, 0.08, 2.4), Vector3(-4.46, y, -0.4), Color("#243141"), false)
		for box_index in range(5):
			var z := -1.42 + float(box_index) * 0.48
			_add_box("archive_box_%d_%d" % [shelf_index, box_index], Vector3(0.34, 0.42, 0.3), Vector3(-4.22, y + 0.24, z), Color("#2f3f4e"), false)
	for i in range(5):
		_add_box("floor_cable_%d" % i, Vector3(0.08, 0.035, 1.05), Vector3(-1.15 + float(i) * 0.42, 0.02, 0.05 - float(i) * 0.32), Color("#05080c"), false)
	_add_box("door_warning_top", Vector3(1.75, 0.08, 0.07), Vector3(0.3, 2.96, -3.88), Color("#ffd27a"), false)
	_add_box("door_warning_bottom", Vector3(1.75, 0.08, 0.07), Vector3(0.3, 0.05, -3.88), Color("#ffd27a"), false)
	_add_box("projector_beam_marker", Vector3(0.12, 0.025, 2.6), Vector3(0.05, 0.05, -0.95), Color("#1e536c"), false)


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	layer.add_child(root)

	var top := HBoxContainer.new()
	top.position = Vector2(22, 16)
	top.size = Vector2(900, 70)
	top.add_theme_constant_override("separation", 22)
	root.add_child(top)
	var title := Label.new()
	title.text = "第13次归档"
	title.add_theme_font_size_override("font_size", 36)
	top.add_child(title)
	timer_label = Label.new()
	timer_label.add_theme_font_size_override("font_size", 22)
	top.add_child(timer_label)

	var guide := PanelContainer.new()
	guide.position = Vector2(22, 488)
	guide.size = Vector2(430, 168)
	root.add_child(guide)
	var guide_box := VBoxContainer.new()
	guide_box.add_theme_constant_override("separation", 7)
	guide.add_child(guide_box)
	objective_title = Label.new()
	objective_title.add_theme_font_size_override("font_size", 27)
	guide_box.add_child(objective_title)
	objective_hint = Label.new()
	objective_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	objective_hint.add_theme_font_size_override("font_size", 17)
	guide_box.add_child(objective_hint)
	var focus_button := Button.new()
	focus_button.text = "看向目标 / Space"
	focus_button.pressed.connect(_focus_current_target)
	guide_box.add_child(focus_button)
	var restart_button := Button.new()
	restart_button.text = "重新开始"
	restart_button.pressed.connect(_restart)
	guide_box.add_child(restart_button)

	var side := PanelContainer.new()
	side.position = Vector2(970, 86)
	side.size = Vector2(286, 492)
	root.add_child(side)
	var side_box := VBoxContainer.new()
	side_box.add_theme_constant_override("separation", 8)
	side.add_child(side_box)
	var inv_title := Label.new()
	inv_title.text = "道具"
	inv_title.add_theme_font_size_override("font_size", 21)
	side_box.add_child(inv_title)
	inventory_label = Label.new()
	inventory_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	inventory_label.add_theme_font_size_override("font_size", 16)
	side_box.add_child(inventory_label)
	var log_title := Label.new()
	log_title.text = "线索记录"
	log_title.add_theme_font_size_override("font_size", 21)
	side_box.add_child(log_title)
	log_label = Label.new()
	log_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	log_label.add_theme_font_size_override("font_size", 15)
	side_box.add_child(log_label)

	active_panel = PanelContainer.new()
	active_panel.visible = false
	active_panel.position = Vector2(458, 116)
	active_panel.size = Vector2(492, 430)
	root.add_child(active_panel)
	var panel_box := VBoxContainer.new()
	panel_box.add_theme_constant_override("separation", 10)
	active_panel.add_child(panel_box)
	panel_title = Label.new()
	panel_title.add_theme_font_size_override("font_size", 28)
	panel_box.add_child(panel_title)
	panel_body = Label.new()
	panel_body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	panel_body.add_theme_font_size_override("font_size", 18)
	panel_box.add_child(panel_body)
	panel_actions = VBoxContainer.new()
	panel_actions.add_theme_constant_override("separation", 8)
	panel_box.add_child(panel_actions)

	crosshair = Label.new()
	crosshair.text = "+"
	crosshair.position = Vector2(634, 345)
	crosshair.add_theme_font_size_override("font_size", 30)
	root.add_child(crosshair)

	toast_label = Label.new()
	toast_label.position = Vector2(24, 666)
	toast_label.size = Vector2(1020, 32)
	toast_label.add_theme_font_size_override("font_size", 18)
	root.add_child(toast_label)

	_add_touch_controls(root)

func _play_sfx(kind: String) -> void:
	if DisplayServer.get_name() == "headless":
		return
	var stream := _tone_stream(kind)
	if stream == null:
		return
	var player := AudioStreamPlayer.new()
	player.stream = stream
	player.bus = "Master"
	add_child(player)
	player.finished.connect(func():
		player.queue_free()
	)
	player.play()


func _tone_stream(kind: String) -> AudioStreamWAV:
	var freq := 660.0
	var duration := 0.08
	var volume := 0.35
	match kind:
		"good":
			freq = 784.0
			duration = 0.09
		"bad":
			freq = 220.0
			duration = 0.12
		"lock":
			freq = 520.0
			duration = 0.1
		"open":
			freq = 932.0
			duration = 0.12
		"ambient":
			freq = 110.0
			duration = 0.18
		_:
			pass
	var sample_rate := 22050
	var sample_count := int(sample_rate * duration)
	var bytes := PackedByteArray()
	bytes.resize(sample_count * 2)
	for i in range(sample_count):
		var t := float(i) / float(sample_rate)
		var wave := sin(TAU * freq * t) * 0.6 + sin(TAU * (freq * 2.0) * t) * 0.2
		var env := 1.0 - (float(i) / float(sample_count))
		var sample := int(clamp(wave * env * volume * 32767.0, -32767.0, 32767.0))
		bytes[i * 2] = sample & 0xff
		bytes[i * 2 + 1] = (sample >> 8) & 0xff
	var wav := AudioStreamWAV.new()
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.stereo = false
	wav.mix_rate = sample_rate
	wav.loop_mode = AudioStreamWAV.LOOP_DISABLED
	wav.data = bytes
	return wav


func _add_touch_controls(root: Control) -> void:
	var pad := GridContainer.new()
	pad.columns = 3
	pad.position = Vector2(36, 300)
	pad.size = Vector2(180, 150)
	root.add_child(pad)
	var labels := ["", "↑", "", "←", "↓", "→"]
	var vectors: Array[Vector2] = [Vector2.ZERO, Vector2(0, -1), Vector2.ZERO, Vector2(-1, 0), Vector2(0, 1), Vector2(1, 0)]
	for i in range(labels.size()):
		var button := Button.new()
		button.text = labels[i]
		button.custom_minimum_size = Vector2(58, 48)
		button.disabled = labels[i] == ""
		var move_vec: Vector2 = vectors[i]
		button.button_down.connect(func(): touch_move = move_vec)
		button.button_up.connect(func(): touch_move = Vector2.ZERO)
		pad.add_child(button)
		touch_buttons.append(button)
	var turn_pad := HBoxContainer.new()
	turn_pad.position = Vector2(1030, 600)
	turn_pad.size = Vector2(190, 64)
	turn_pad.add_theme_constant_override("separation", 8)
	root.add_child(turn_pad)
	var left_turn := Button.new()
	left_turn.text = "转左"
	left_turn.custom_minimum_size = Vector2(88, 54)
	left_turn.button_down.connect(func(): touch_turn = -1.0)
	left_turn.button_up.connect(func(): touch_turn = 0.0)
	turn_pad.add_child(left_turn)
	var right_turn := Button.new()
	right_turn.text = "转右"
	right_turn.custom_minimum_size = Vector2(88, 54)
	right_turn.button_down.connect(func(): touch_turn = 1.0)
	right_turn.button_up.connect(func(): touch_turn = 0.0)
	turn_pad.add_child(right_turn)


func _update_player(delta: float) -> void:
	var dir := Vector3.ZERO
	var forward := Vector3(-sin(yaw), 0, -cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	if Input.is_action_pressed("move_forward"):
		dir += forward
	if Input.is_action_pressed("move_back"):
		dir -= forward
	if Input.is_action_pressed("move_right"):
		dir += right
	if Input.is_action_pressed("move_left"):
		dir -= right
	if touch_move.y < 0:
		dir += forward
	if touch_move.y > 0:
		dir -= forward
	if touch_move.x > 0:
		dir += right
	if touch_move.x < 0:
		dir -= right
	if dir.length() > 0.01:
		focus_blend = max(0.0, focus_blend - delta * 3.0)
		player_pos += dir.normalized() * PLAYER_SPEED * delta
		player_pos.x = clamp(player_pos.x, -3.9, 3.9)
		player_pos.z = clamp(player_pos.z, -2.95, 5.65)
	if Input.is_action_just_pressed("focus_target"):
		_focus_current_target()
	if abs(touch_turn) > 0.01:
		focus_blend = max(0.0, focus_blend - delta * 3.0)
		yaw -= touch_turn * delta * 1.8


func _update_camera(delta: float) -> void:
	var base_forward := Vector3(-sin(yaw) * cos(pitch), sin(pitch), -cos(yaw) * cos(pitch))
	if focus_blend > 0.01:
		camera.global_position = camera.global_position.lerp(focus_pos, min(1.0, delta * 4.8))
		camera.look_at(focus_look, Vector3.UP)
		focus_blend = max(0.0, focus_blend - delta * 0.65)
	else:
		camera.global_position = player_pos
		camera.look_at(player_pos + base_forward, Vector3.UP)


func _handle_interaction(id: String) -> void:
	if not _is_revealed(id):
		_toast("这里暂时没有可操作的进展，先跟随当前目标。")
		return
	match id:
		"lamp":
			if state["lamp_on"]:
				_toast("台灯已经点亮。")
				_play_sfx("bad")
				return
			state["lamp_on"] = true
			lamp_light.light_energy = 2.9
			floor_light.light_energy = 1.75
			_play_sfx("good")
			_add_note("日历显影：07/13，表示第 13 份归档。")
			_show_panel("灯光启动", "暖光扫过桌面，日历数字浮现出来。房间不再像一张静态谜题图，而是开始回应你的操作。", [
				{"text": "查看线索", "action": "step_clues"}
			])
		"calendar":
			state["calendar_seen"] = true
			_play_sfx("good")
			_add_note("07/13：第 13 份，不是密码本身。")
			_show_panel("日历", "日期被划了 13 道细线。它告诉你顺序：第 13 份档案。", [
				{"text": "继续调查", "action": "close"}
			])
		"rule_card":
			state["rule_seen"] = true
			_play_sfx("good")
			_add_note("编号从 205 开始，每份 +1，所以第 13 份为 217。")
			_show_panel("编号卡", "归档编号从 205 起算，每份递增 1。你把第 13 份推到 217。", [
				{"text": "去铁柜", "action": "step_cabinet"}
			])
		"cabinet":
			_show_cabinet_lock()
		"fuse_box":
			_show_fuse_box()
		"projector":
			if state["projector_on"]:
				_toast("投影正在播放删除报告残页。")
				_play_sfx("good")
			else:
				_toast("投影机没有电。")
				_play_sfx("bad")
		"report_table":
			_show_report_puzzle()
		"photo_wall":
			_add_note("照片墙颜色顺序：蓝、绿、黄、红。")
			_play_sfx("good")
			_show_panel("照片墙", "四张照片依次亮起：蓝、绿、黄、红。最后一张照片的脸被涂掉，只剩 A-013。", [
				{"text": "去记忆柜", "action": "step_case"}
			])
		"memory_case":
			_show_color_lock()
		"memory_core":
			if not state["case_open"]:
				_toast("核心还锁在柜内。")
				_play_sfx("bad")
				return
			state["core_taken"] = true
			_add_item("记忆核心")
			_toast("记忆核心收入道具。它在接近终端时持续发光。")
			_play_sfx("good")
			_advance_to("terminal")
		"terminal":
			_show_terminal()
		"door":
			if state["terminal_unlocked"]:
				_show_ending()
			else:
				_toast("主门仍处于红色锁定状态。")
				_play_sfx("bad")


func _show_cabinet_lock() -> void:
	if state["cabinet_open"]:
		_toast("铁柜已经打开，里面的保险丝可以使用。")
		_play_sfx("good")
		_advance_to("fuse")
		return
	if not state["calendar_seen"] or not state["rule_seen"]:
		_toast("你还缺少完整推算线索。先看日历和编号卡。")
		_play_sfx("bad")
		_advance_to("clues")
		return
	_update_lock_display()
	_show_panel("三位数字锁", "点击三个轮盘调整数字。日历给顺序，编号卡给起点。", [
		{"text": "百位 +", "action": "lock_inc_0"},
		{"text": "十位 +", "action": "lock_inc_1"},
		{"text": "个位 +", "action": "lock_inc_2"},
		{"text": "确认输入", "action": "lock_submit"}
	])


func _show_fuse_box() -> void:
	if not state["cabinet_open"]:
		_toast("电箱缺保险丝，铁柜可能有备用件。")
		_play_sfx("bad")
		return
	if state["projector_on"]:
		_toast("电源已恢复。")
		_play_sfx("good")
		return
	state["fuse_taken"] = true
	_add_item("备用保险丝")
	_show_panel("电箱", "保险丝插回插槽。投影机的风扇开始转动，墙面出现碎裂的报告页。", [
		{"text": "启动投影", "action": "projector_on"}
	])


func _show_report_puzzle() -> void:
	if not state["projector_on"]:
		_toast("投影未启动，碎片上看不到页码。")
		_play_sfx("bad")
		return
	if state["report_solved"]:
		_toast("报告已经复原。")
		_play_sfx("good")
		return
	_update_report_display()
	_close_panel()
	_toast("点击桌上的编号碎片，按 1 到 6 的顺序放入。错序会打散当前排列。")
	_play_sfx("good")


func _show_color_lock() -> void:
	if state["case_open"]:
		_toast("记忆柜已经打开。")
		_play_sfx("good")
		return
	if not state["report_solved"]:
		_toast("你还不知道这组颜色对应谁。先复原删除报告。")
		_play_sfx("bad")
		return
	_update_color_display()
	_close_panel()
	_toast("直接点击柜门上的颜色按钮，按蓝、绿、黄、红的顺序触发。")
	_play_sfx("good")


func _show_terminal() -> void:
	if not state["core_taken"]:
		_toast("终端需要记忆核心。")
		_play_sfx("bad")
		return
	if state["terminal_unlocked"]:
		_toast("终端已经通过认证。")
		_play_sfx("good")
		return
	_show_panel("终端认证", "系统要求选择“第一个被删除的主体”。外部员工姓名会被拒绝。", [
		{"text": "沈蓝", "action": "terminal_wrong"},
		{"text": "A-013", "action": "terminal_unlock"}
	])


func _show_ending() -> void:
	_show_panel("恢复策略", "门后不是出口，而是备份库。你可以只恢复自己，也可以把被删除者全部送回系统。", [
		{"text": "恢复所有人", "action": "ending_all"},
		{"text": "只恢复自己", "action": "ending_self"}
	])


func _run_action(action: String) -> void:
	match action:
		"close":
			_close_panel()
		"step_clues":
			_close_panel()
			_advance_to("clues")
		"step_cabinet":
			_close_panel()
			_advance_to("cabinet")
		"step_case":
			_close_panel()
			_advance_to("case")
		"lock_inc_0":
			_inc_lock_digit(0)
		"lock_inc_1":
			_inc_lock_digit(1)
		"lock_inc_2":
			_inc_lock_digit(2)
		"lock_submit":
			_submit_lock()
		"projector_on":
			state["projector_on"] = true
			_close_panel()
			_toast("投影启动。墙上的报告碎片出现页码影子。")
			_play_sfx("open")
			projector_light.light_energy = 2.6
			projection_label.text = "1 2 3\n4 5 6\nA-013"
			_advance_to("report")
		"report_piece_1":
			_add_report_piece(1)
		"report_piece_2":
			_add_report_piece(2)
		"report_piece_3":
			_add_report_piece(3)
		"report_piece_4":
			_add_report_piece(4)
		"report_piece_5":
			_add_report_piece(5)
		"report_piece_6":
			_add_report_piece(6)
		"report_reset":
			report_slots.clear()
			_update_report_display()
			_toast("碎片已拿起，重新按页码摆放。")
			_play_sfx("bad")
		"color_blue":
			_add_color("blue")
		"color_green":
			_add_color("green")
		"color_yellow":
			_add_color("yellow")
		"color_red":
			_add_color("red")
		"color_reset":
			color_input.clear()
			_update_color_display()
			_toast("颜色触点已复位。")
			_play_sfx("bad")
		"terminal_wrong":
			_add_note("终端拒绝沈蓝：权限主体不能删除外部对象。")
			_toast("认证失败：权限主体不能删除外部对象。")
			_play_sfx("bad")
		"terminal_unlock":
			state["terminal_unlocked"] = true
			state["terminal_ready"] = true
			_add_note("A-013 认证通过，主门门禁解除。")
			_close_panel()
			_toast("终端变绿，主门机械锁释放。")
			_play_sfx("open")
			terminal_screen.material_override = _mat(Color("#13352b"), Color("#44f0a2"), 1.2)
			door_light.material_override = _mat(Color("#45ef9a"), Color("#0d7a3e"), 1.0)
			_advance_to("door")
		"ending_all":
			state["ending"] = "恢复所有人"
			_finish_game("你把备份库重新接入，照片墙上的名字逐个亮起。")
		"ending_self":
			state["ending"] = "只恢复自己"
			_finish_game("你保留了自己的出口，房间在身后继续倒计时。")


func _finish_game(text: String) -> void:
	state["door_open"] = true
	_close_panel()
	_toast("章节完成：" + text)
	_advance_to("door")


func _inc_lock_digit(index: int) -> void:
	lock_digits[index] = (int(lock_digits[index]) + 1) % 10
	_update_lock_display()
	_toast("当前输入：" + _lock_text())
	_play_sfx("lock")


func _submit_lock() -> void:
	if lock_digits != LOCK_CODE:
		_toast(_lock_text() + " 不对。日期是顺序，编号卡才给起点。")
		_play_sfx("bad")
		return
	state["cabinet_open"] = true
	_add_item("碎片包")
	_add_item("卡壳")
	_close_panel()
	_toast("铁柜门弹开，保险丝和碎片包掉出来。")
	_play_sfx("open")
	cabinet_display.modulate = Color("#7df0bf")
	_tween_node(cabinet_door, "position:x", -0.62, 0.35)
	_advance_to("fuse")


func _add_report_piece(piece: int) -> void:
	if state["report_solved"]:
		return
	var expected := int(REPORT_SOLUTION[report_slots.size()])
	if piece != expected:
		report_slots.clear()
		_update_report_display()
		_toast("第 %d 片边缘对不上，页码阴影被打散。" % piece)
		_play_sfx("bad")
		return
	report_slots.append(piece)
	_update_report_display()
	_play_sfx("lock")
	if report_slots.size() == REPORT_SOLUTION.size():
		state["report_solved"] = true
		_add_note("删除报告：A-013 是权限主体，第一次删除目标是自己。")
		_close_panel()
		_toast("报告合拢，A-013 的名字第一次完整出现。")
		_play_sfx("open")
		projection_label.text = "A-013\n自删除测试"
		report_display.modulate = Color("#7df0bf")
		_advance_to("case")
	else:
		_toast("第 %d 片吸附到槽位。" % piece)


func _add_color(color_id: String) -> void:
	if state["case_open"]:
		return
	var expected := String(COLOR_SOLUTION[color_input.size()])
	if color_id != expected:
		color_input.clear()
		_update_color_display()
		_toast("颜色回路断开。观察照片墙的亮起顺序。")
		_play_sfx("bad")
		return
	color_input.append(color_id)
	_update_color_display()
	_play_sfx("lock")
	if color_input.size() == COLOR_SOLUTION.size():
		state["case_open"] = true
		_close_panel()
		_toast("记忆柜玻璃滑开，核心从冷光中浮起。")
		_play_sfx("open")
		color_display.modulate = Color("#7df0bf")
		_tween_node(case_glass, "position:x", 0.72, 0.36)
		_advance_to("core")
	else:
		_toast("颜色触点已接通：%s" % _color_text())


func _lock_text() -> String:
	return "%d%d%d" % [lock_digits[0], lock_digits[1], lock_digits[2]]


func _update_lock_display() -> void:
	if cabinet_display:
		cabinet_display.text = _lock_text()


func _update_report_display() -> void:
	if not report_display:
		return
	var slots := []
	for i in range(REPORT_SOLUTION.size()):
		if i < report_slots.size():
			slots.append(str(report_slots[i]))
		else:
			slots.append("_")
	report_display.text = "%s %s %s\n%s %s %s" % [slots[0], slots[1], slots[2], slots[3], slots[4], slots[5]]


func _color_text() -> String:
	var names := {
		"blue": "蓝",
		"green": "绿",
		"yellow": "黄",
		"red": "红"
	}
	var out := []
	for item in color_input:
		out.append(names.get(item, "?"))
	return " ".join(out)


func _update_color_display() -> void:
	if not color_display:
		return
	var names := {
		"blue": "蓝",
		"green": "绿",
		"yellow": "黄",
		"red": "红"
	}
	var slots := []
	for i in range(COLOR_SOLUTION.size()):
		if i < color_input.size():
			slots.append(names.get(color_input[i], "?"))
		else:
			slots.append("_")
	color_display.text = " ".join(slots)


func _show_panel(title: String, body: String, actions: Array) -> void:
	active_panel.visible = true
	panel_title.text = title
	panel_body.text = body
	for child in panel_actions.get_children():
		child.queue_free()
	for action in actions:
		var button := Button.new()
		button.text = action["text"]
		var action_id := String(action["action"])
		button.pressed.connect(func(): _run_action(action_id))
		panel_actions.add_child(button)


func _close_panel() -> void:
	active_panel.visible = false


func _restart() -> void:
	get_tree().reload_current_scene()


func _advance_to(step_id: String) -> void:
	state["step"] = step_id
	_update_step_ui()
	_focus_current_target()


func _current_step() -> Dictionary:
	for step in steps:
		if step["id"] == state["step"]:
			return step
	return steps[0]


func _update_step_ui() -> void:
	var step := _current_step()
	objective_title.text = step["title"]
	objective_hint.text = step["hint"]
	_update_visibility()


func _update_visibility() -> void:
	for id in objects.keys():
		var node: Node3D = objects[id]
		node.visible = _is_revealed(id)


func _is_revealed(id: String) -> bool:
	if id in ["lamp", "door"]:
		return true
	if id in ["calendar", "rule_card", "terminal"] and state["lamp_on"]:
		return true
	if id == "cabinet" and state["lamp_on"]:
		return true
	if id in ["fuse_box", "projector", "report_table"] and state["cabinet_open"]:
		return true
	if id in ["report_piece_1", "report_piece_2", "report_piece_3", "report_piece_4", "report_piece_5", "report_piece_6"] and state["projector_on"] and not state["report_solved"]:
		return true
	if id in ["photo_wall", "memory_case"] and state["report_solved"]:
		return true
	if id in ["color_blue", "color_green", "color_yellow", "color_red"] and state["report_solved"] and not state["case_open"]:
		return true
	if id == "memory_core" and state["case_open"]:
		return true
	return id == _current_step()["target"]


func _update_guidance() -> void:
	var target := String(_current_step()["target"])
	for id in objects.keys():
		var node: Node3D = objects[id]
		var tag: Label3D = tags[id]
		if not node.visible:
			continue
		if id == target:
			var pulse := 1.0 + sin(Time.get_ticks_msec() / 150.0) * 0.035
			node.scale = Vector3.ONE * pulse
			tag.modulate = Color("#ffd27a")
			tag.visible = true
		else:
			node.scale = Vector3.ONE
			tag.modulate = Color("#d9dde5")
			tag.visible = state["ending"] != "" or id in ["door", "terminal"]


func _update_ui() -> void:
	var minutes := int(state["remaining"]) / 60
	var seconds := int(state["remaining"]) % 60
	timer_label.text = "循环剩余 %02d:%02d" % [minutes, seconds]
	inventory_label.text = "暂无" if state["items"].is_empty() else "\n".join(state["items"])
	var notes: Array = state["notes"]
	log_label.text = "暂无" if notes.is_empty() else "\n".join(notes.slice(max(0, notes.size() - 6), notes.size()))


func _focus_current_target() -> void:
	var step := _current_step()
	_focus_zone(String(step["zone"]))


func _focus_zone(zone: String, instant := false) -> void:
	var poses := {
		"desk": {"pos": Vector3(-0.3, 2.08, 4.25), "look": Vector3(-1.2, 1.15, 1.05)},
		"cabinet": {"pos": Vector3(-2.15, 2.05, 2.25), "look": Vector3(-3.55, 1.3, -1.45)},
		"projector": {"pos": Vector3(0.2, 2.1, 3.3), "look": Vector3(0.45, 1.8, -2.8)},
		"case": {"pos": Vector3(2.2, 2.05, 2.35), "look": Vector3(3.1, 1.45, -1.8)},
		"door": {"pos": Vector3(0.0, 2.05, 2.35), "look": Vector3(0.25, 1.55, -3.75)}
	}
	var pose = poses.get(zone, poses["desk"])
	focus_pos = pose["pos"]
	focus_look = pose["look"]
	focus_blend = 1.0
	if instant:
		camera.global_position = focus_pos
		camera.look_at(focus_look, Vector3.UP)


func _interact_from_screen(screen_pos: Vector2) -> void:
	var from := camera.project_ray_origin(screen_pos)
	var to := from + camera.project_ray_normal(screen_pos) * 80.0
	var query := PhysicsRayQueryParameters3D.create(from, to)
	query.collide_with_areas = true
	query.collide_with_bodies = false
	var hit := get_world_3d().direct_space_state.intersect_ray(query)
	if hit.is_empty():
		return
	var collider: Object = hit.get("collider")
	if collider and collider.has_meta("id"):
		_handle_interaction(String(collider.get_meta("id")))


func _add_interactive(id: String, label: String, position: Vector3, node: Node3D, pick_size: Vector3) -> void:
	node.name = id
	node.position = position
	add_child(node)
	objects[id] = node
	var tag := Label3D.new()
	tag.name = "tag"
	tag.text = label
	tag.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	tag.font_size = 30
	tag.modulate = Color("#d9dde5")
	tag.outline_size = 8
	tag.outline_modulate = Color("#050b12")
	tag.position = Vector3(0, pick_size.y * 0.55 + 0.18, 0)
	node.add_child(tag)
	tags[id] = tag
	var area := Area3D.new()
	area.name = id + "_area"
	area.set_meta("id", id)
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = pick_size
	shape.shape = box
	area.add_child(shape)
	node.add_child(area)


func _add_box(node_name: String, size: Vector3, position: Vector3, color: Color, pickable: bool) -> MeshInstance3D:
	var mesh := _box_child(node_name, size, position, color)
	add_child(mesh)
	if pickable:
		var area := Area3D.new()
		area.set_meta("id", node_name)
		var shape := CollisionShape3D.new()
		var box := BoxShape3D.new()
		box.size = size
		shape.shape = box
		area.add_child(shape)
		mesh.add_child(area)
	return mesh


func _flat_box(node_name: String, size: Vector3, color: Color) -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child(node_name, size, Vector3.ZERO, color))
	return node


func _make_lamp() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("base", Vector3(0.45, 0.08, 0.45), Vector3.ZERO, Color("#1a2028")))
	node.add_child(_box_child("stem", Vector3(0.08, 0.72, 0.08), Vector3(0, 0.36, 0), Color("#2b333d")))
	node.add_child(_box_child("shade", Vector3(0.62, 0.28, 0.42), Vector3(0.1, 0.79, -0.05), Color("#ffd27a"), Color("#ffb844"), 0.7))
	return node


func _make_terminal() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("body", Vector3(1.15, 0.72, 0.38), Vector3.ZERO, Color("#222c36")))
	terminal_screen = _box_child("screen", Vector3(0.82, 0.42, 0.05), Vector3(0, 0.08, -0.23), Color("#102f46"), Color("#1c8bc3"), 0.85)
	node.add_child(terminal_screen)
	return node


func _make_fuse_box() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("panel", Vector3(0.72, 0.72, 0.12), Vector3.ZERO, Color("#202a35")))
	node.add_child(_box_child("slot", Vector3(0.12, 0.48, 0.06), Vector3(0.18, 0, -0.09), Color("#ff6570"), Color("#7b1218"), 0.45))
	return node


func _make_projector() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("body", Vector3(0.72, 0.32, 0.48), Vector3.ZERO, Color("#1b242e")))
	node.add_child(_box_child("lens", Vector3(0.28, 0.28, 0.12), Vector3(0, 0, -0.3), Color("#8ad7ff"), Color("#8ad7ff"), 0.4))
	return node


func _make_report_table() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("top", Vector3(1.1, 0.08, 0.78), Vector3.ZERO, Color("#29231d")))
	return node


func _add_report_piece_objects() -> void:
	for i in range(6):
		var piece := Node3D.new()
		var x := -0.32 + float(i % 3) * 0.33
		var z := -0.12 + floorf(float(i) / 3.0) * 0.29
		piece.add_child(_box_child("piece", Vector3(0.22, 0.025, 0.18), Vector3.ZERO, Color("#d8dde5")))
		var tag := Label3D.new()
		tag.text = str(i + 1)
		tag.font_size = 26
		tag.modulate = Color("#102536")
		tag.outline_size = 4
		tag.outline_modulate = Color("#d8dde5")
		tag.position = Vector3(0, 0.08, 0)
		piece.add_child(tag)
		_add_interactive("report_piece_%d" % (i + 1), "碎片 %d" % (i + 1), Vector3(1.4 + x, 1.27, 1.55 + z), piece, Vector3(0.28, 0.08, 0.22))
		report_piece_nodes[i + 1] = piece


func _add_color_button_objects(parent: Node3D) -> void:
	var colors := [
		{"id": "blue", "color": Color("#7fc9ff"), "x": -0.24},
		{"id": "green", "color": Color("#7df0bf"), "x": -0.05},
		{"id": "yellow", "color": Color("#ffd27a"), "x": 0.14},
		{"id": "red", "color": Color("#ff6f77"), "x": 0.33}
	]
	for item in colors:
		var button := Node3D.new()
		button.add_child(_box_child("cap", Vector3(0.16, 0.16, 0.16), Vector3.ZERO, item["color"], item["color"], 0.6))
		var tag := Label3D.new()
		tag.text = String(item["id"])
		tag.font_size = 18
		tag.modulate = Color("#102536")
		tag.outline_size = 4
		tag.outline_modulate = Color("#d8dde5")
		tag.position = Vector3(0, 0.15, 0)
		button.add_child(tag)
		_add_interactive("color_%s" % String(item["id"]), String(item["id"]), Vector3(3.35 + float(item["x"]), 1.2, -1.0), button, Vector3(0.26, 0.28, 0.26))
		color_button_nodes[String(item["id"])] = button


func _make_photo_wall() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("board", Vector3(1.75, 1.08, 0.08), Vector3.ZERO, Color("#151d29")))
	var colors := [Color("#7fc9ff"), Color("#7df0bf"), Color("#ffd27a"), Color("#ff6f77")]
	for i in range(4):
		node.add_child(_box_child("photo_%d" % i, Vector3(0.34, 0.42, 0.05), Vector3(-0.57 + float(i) * 0.38, 0.08, -0.08), colors[i], colors[i], 0.18))
	return node


func _make_memory_core() -> Node3D:
	var node := Node3D.new()
	node.add_child(_box_child("core", Vector3(0.36, 0.36, 0.36), Vector3.ZERO, Color("#55f0d2"), Color("#55f0d2"), 1.2))
	return node


func _box_child(node_name: String, size: Vector3, position: Vector3, color: Color, emission := Color.BLACK, energy := 0.0) -> MeshInstance3D:
	var mesh := MeshInstance3D.new()
	mesh.name = node_name
	var box := BoxMesh.new()
	box.size = size
	mesh.mesh = box
	mesh.position = position
	mesh.material_override = _mat(color, emission, energy)
	mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	return mesh


func _mat(color: Color, emission := Color.BLACK, energy := 0.0) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.66
	material.metallic = 0.1
	if energy > 0.0:
		material.emission_enabled = true
		material.emission = emission
		material.emission_energy_multiplier = energy
	return material


func _tween_node(node: Node, property: String, value: Variant, duration: float) -> void:
	var tween := create_tween()
	tween.tween_property(node, property, value, duration).set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)


func _add_note(text: String) -> void:
	if not state["notes"].has(text):
		state["notes"].append(text)


func _add_item(text: String) -> void:
	if not state["items"].has(text):
		state["items"].append(text)


func _toast(text: String) -> void:
	toast_label.text = text
