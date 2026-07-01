extends Node2D

const WORLD_SIZE := Vector2(1280.0, 720.0)
const PLAYER_SPEED := 260.0
const DASH_SPEED := 820.0
const DASH_DURATION := 0.14
const DASH_COOLDOWN := 1.35
const FIRE_RATE := 0.36
const BULLET_SPEED := 560.0
const MAX_HAZARDS := 2
const HAZARD_BASE_CHANCE := 0.18
const SPAWN_TELEGRAPH_TIME := 0.62
const AIM_RANGE := 520.0

var rng := RandomNumberGenerator.new()
var mode := "ready"
var wave := 1
var gems := 0
var wave_spawn_left := 0
var spawn_timer := 0.0
var fire_timer := 0.0
var fire_cooldown := FIRE_RATE
var dash_timer := 0.0
var dash_cooldown := DASH_COOLDOWN
var dash_time := 0.0
var invuln_timer := 0.0
var gem_magnet_radius := 112.0
var shake := 0.0
var message := "Press Enter or Space to start"
var chosen_upgrades: Array[String] = []

var player := {
	"pos": Vector2(640, 360),
	"vel": Vector2.ZERO,
	"radius": 18.0,
	"hp": 5,
	"damage": 1,
}
var enemies: Array[Dictionary] = []
var bullets: Array[Dictionary] = []
var enemy_bullets: Array[Dictionary] = []
var pending_spawns: Array[Dictionary] = []
var drops: Array[Dictionary] = []
var hazards: Array[Dictionary] = []
var particles: Array[Dictionary] = []
var wave_plan: Array[Dictionary] = [
	{"name": "Lantern Alley", "count": 6, "types": ["drifter", "drifter", "runner"]},
	{"name": "Mask Gate", "count": 8, "types": ["drifter", "runner", "runner", "shooter"]},
	{"name": "Exit Shrine", "count": 7, "types": ["runner", "shooter", "shooter", "brute"]},
]

var rooms := [
	Rect2(92, 94, 304, 212),
	Rect2(444, 84, 360, 232),
	Rect2(860, 112, 300, 196),
	Rect2(124, 386, 354, 210),
	Rect2(550, 364, 298, 236),
	Rect2(916, 390, 250, 206),
]
var stalls := [
	Rect2(80, 330, 254, 38),
	Rect2(370, 330, 176, 38),
	Rect2(784, 330, 244, 38),
	Rect2(1058, 330, 130, 38),
	Rect2(414, 118, 24, 154),
	Rect2(820, 136, 24, 150),
	Rect2(502, 424, 24, 118),
	Rect2(870, 424, 24, 128),
]

func _ready() -> void:
	rng.randomize()
	reset()
	if has_user_arg("--smoke-test"):
		run_smoke_test()
		return
	var capture_path := get_capture_path()
	if capture_path != "":
		capture_preview(capture_path)

func has_user_arg(name: String) -> bool:
	for arg in OS.get_cmdline_args():
		if arg == name:
			return true
	for arg in OS.get_cmdline_user_args():
		if arg == name:
			return true
	return false

func get_capture_path() -> String:
	for arg in OS.get_cmdline_args():
		if arg.begins_with("--capture="):
			return arg.trim_prefix("--capture=")
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--capture="):
			return arg.trim_prefix("--capture=")
	return ""

func capture_preview(path: String) -> void:
	start()
	var preview_types := ["drifter", "runner", "shooter", "brute"]
	for i in preview_types.size():
		spawn_enemy(preview_types[i], Vector2(470 + i * 112, 290 + (i % 2) * 120))
	hazards.append({"rect": Rect2(790, 430, 26, 132), "warn": 0.0, "active": 0.34})
	drops.append({"pos": Vector2(710, 365), "radius": 7.0})
	bullets.append({"pos": Vector2(612, 360), "vel": Vector2(1, -0.2).normalized() * BULLET_SPEED, "life": 0.9, "radius": 5.0, "damage": player.damage})
	burst(player.pos, Color("#37f4d0"), 6)
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	image.save_png(path)
	get_tree().quit()

func run_smoke_test() -> void:
	start()
	var advanced_waves := 0
	var frames := 0
	while frames < 3600:
		frames += 1
		if mode == "upgrade":
			if advanced_waves == 0:
				upgrade_fire_rate()
			elif advanced_waves == 1:
				upgrade_damage()
			else:
				upgrade_dash()
			advanced_waves += 1
		if mode in ["won", "lost"]:
			break
		if frames % 40 == 0:
			var angle := float(frames) * 0.043
			player.pos = Vector2(640, 360) + Vector2(cos(angle), sin(angle)) * 120.0
		update_game(1.0 / 60.0)
	if wave < 1 or player.hp < 0:
		push_error("Smoke test ended with invalid state")
		get_tree().quit(1)
		return
	print("Night Market Dash smoke test: mode=%s wave=%d gems=%d enemies=%d bullets=%d spawns=%d" % [mode, wave, gems, enemies.size(), bullets.size(), pending_spawns.size()])
	get_tree().quit(0)

func reset() -> void:
	mode = "ready"
	wave = 1
	gems = 0
	wave_spawn_left = 0
	spawn_timer = 0.0
	fire_timer = 0.0
	fire_cooldown = FIRE_RATE
	dash_timer = 0.0
	dash_cooldown = DASH_COOLDOWN
	dash_time = 0.0
	invuln_timer = 0.0
	gem_magnet_radius = 112.0
	shake = 0.0
	message = "Press Enter or Space to start"
	chosen_upgrades.clear()
	player = {
		"pos": Vector2(640, 360),
		"vel": Vector2.ZERO,
		"radius": 18.0,
		"hp": 5,
		"damage": 1,
	}
	enemies.clear()
	bullets.clear()
	enemy_bullets.clear()
	pending_spawns.clear()
	drops.clear()
	hazards.clear()
	particles.clear()

func start() -> void:
	mode = "playing"
	message = ""
	begin_wave()

func begin_wave() -> void:
	var plan := get_wave_plan()
	wave_spawn_left = plan.count
	spawn_timer = 0.45
	hazards.clear()

func get_wave_plan() -> Dictionary:
	return wave_plan[min(wave - 1, wave_plan.size() - 1)]

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("restart"):
		reset()
	if mode == "ready" and (event.is_action_pressed("dash") or (event is InputEventKey and event.pressed and event.keycode == KEY_ENTER)):
		start()
	elif mode == "playing" and event.is_action_pressed("dash"):
		try_dash()
	elif mode == "upgrade" and event is InputEventKey and event.pressed:
		if event.keycode == KEY_1:
			upgrade_fire_rate()
		elif event.keycode == KEY_2:
			upgrade_damage()
		elif event.keycode == KEY_3:
			upgrade_dash()

func upgrade_fire_rate() -> void:
	fire_cooldown = max(0.18, fire_cooldown * 0.72)
	chosen_upgrades.append("Faster charms")
	next_wave()

func upgrade_damage() -> void:
	player.damage += 1
	gem_magnet_radius += 18.0
	chosen_upgrades.append("Harder hits")
	next_wave()

func upgrade_dash() -> void:
	dash_cooldown = max(0.72, dash_cooldown * 0.72)
	player.hp = min(6, player.hp + 1)
	chosen_upgrades.append("Shorter dash")
	next_wave()

func next_wave() -> void:
	mode = "playing"
	wave += 1
	message = ""
	begin_wave()

func try_dash() -> void:
	if dash_timer > 0.0:
		return
	var dir := input_vector()
	if dir == Vector2.ZERO:
		return
	player.vel = dir * DASH_SPEED
	dash_time = DASH_DURATION
	dash_timer = dash_cooldown
	invuln_timer = max(invuln_timer, 0.22)
	burst(player.pos, Color("#37f4d0"), 9)

func input_vector() -> Vector2:
	var dir := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	return dir.normalized() if dir.length() > 0.0 else Vector2.ZERO

func _process(delta: float) -> void:
	if Input.is_action_just_pressed("dash") and mode == "ready":
		start()
	update_game(delta)
	queue_redraw()

func update_game(delta: float) -> void:
	shake = max(0.0, shake - delta * 18.0)
	update_particles(delta)
	if mode != "playing":
		return

	invuln_timer = max(0.0, invuln_timer - delta)
	fire_timer -= delta
	dash_timer = max(0.0, dash_timer - delta)
	dash_time = max(0.0, dash_time - delta)

	if dash_time <= 0.0:
		player.vel = input_vector() * PLAYER_SPEED
	player.pos += player.vel * delta
	player.pos = player.pos.clamp(Vector2(32, 42), WORLD_SIZE - Vector2(32, 32))
	for stall in stalls:
		push_circle_out(player, stall)

	spawn_timer -= delta
	if wave_spawn_left > 0 and spawn_timer <= 0.0:
		queue_enemy_spawn()
		wave_spawn_left -= 1
		spawn_timer = max(0.55, 1.2 - wave * 0.11)
	if hazards.size() < MAX_HAZARDS and rng.randf() < delta * (HAZARD_BASE_CHANCE + wave * 0.05):
		spawn_hazard()

	fire_nearest()
	update_bullets(delta)
	update_pending_spawns(delta)
	update_enemies(delta)
	update_enemy_bullets(delta)
	update_hazards(delta)
	update_drops(delta)

	if player.hp <= 0:
		mode = "lost"
		message = "The market took you. Press R to restart."
	elif wave_spawn_left == 0 and enemies.is_empty():
		if wave >= 3:
			mode = "won"
			message = "Exit opened. Press R to restart."
		else:
			mode = "upgrade"
			message = "Choose: 1 faster charms  2 harder hits  3 reset dash"

func queue_enemy_spawn() -> void:
	var room: Rect2 = rooms[rng.randi_range(0, rooms.size() - 1)]
	var plan := get_wave_plan()
	var types: Array = plan.types
	var enemy_type: String = types[rng.randi_range(0, types.size() - 1)]
	var spawn_pos := Vector2(rng.randf_range(room.position.x + 36, room.end.x - 36), rng.randf_range(room.position.y + 36, room.end.y - 36))
	pending_spawns.append({
		"pos": spawn_pos,
		"type": enemy_type,
		"timer": SPAWN_TELEGRAPH_TIME,
	})

func spawn_enemy(enemy_type: String, spawn_pos: Vector2) -> void:
	var radius := 16.0
	var hp := 3 + wave
	var speed := 92.0 + wave * 12.0
	if enemy_type == "runner":
		radius = 12.0
		hp = 2
		speed = 165.0
	elif enemy_type == "brute":
		radius = 24.0
		hp = 10
		speed = 70.0
	enemies.append({
		"pos": spawn_pos,
		"radius": radius,
		"hp": hp,
		"speed": speed,
		"type": enemy_type,
		"shoot_timer": rng.randf_range(0.35, 1.1),
		"hit": 0.0,
	})

func update_pending_spawns(delta: float) -> void:
	for spawn in pending_spawns:
		spawn.timer -= delta
		if spawn.timer <= 0.0:
			spawn_enemy(spawn.type, spawn.pos)
			spawn.dead = true
			burst(spawn.pos, Color("#ffd15c"), 5)
	pending_spawns = pending_spawns.filter(func(s): return not s.has("dead"))

func spawn_hazard() -> void:
	var room: Rect2 = rooms[rng.randi_range(0, rooms.size() - 1)]
	var horizontal := rng.randf() > 0.5
	hazards.append({
		"rect": Rect2(
			room.position.x + 22 if horizontal else rng.randf_range(room.position.x + 58, room.end.x - 58),
			rng.randf_range(room.position.y + 58, room.end.y - 58) if horizontal else room.position.y + 22,
			room.size.x - 44 if horizontal else 24,
			24 if horizontal else room.size.y - 44
		),
		"warn": 0.95,
		"active": 0.28,
	})

func fire_nearest() -> void:
	if fire_timer > 0.0:
		return
	var direction := get_fire_direction()
	if direction == Vector2.ZERO:
		return
	bullets.append({"pos": player.pos, "vel": direction * BULLET_SPEED, "life": 0.9, "radius": 5.0, "damage": player.damage})
	fire_timer = fire_cooldown

func get_fire_direction() -> Vector2:
	if Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		var manual_dir: Vector2 = player.pos.direction_to(get_local_mouse_position())
		if manual_dir.length_squared() > 0.001:
			return manual_dir
	if enemies.is_empty():
		return Vector2.ZERO
	var best_index := -1
	var best_dist := 99999.0
	for i in enemies.size():
		var distance: float = player.pos.distance_to(enemies[i].pos)
		if distance < best_dist:
			best_dist = distance
			best_index = i
	if best_index == -1 or best_dist > AIM_RANGE:
		return Vector2.ZERO
	return player.pos.direction_to(enemies[best_index].pos)

func update_bullets(delta: float) -> void:
	for bullet in bullets:
		bullet.pos += bullet.vel * delta
		bullet.life -= delta
		for enemy in enemies:
			if bullet.life > 0.0 and bullet.pos.distance_to(enemy.pos) < bullet.radius + enemy.radius:
				bullet.life = 0.0
				enemy.hp -= bullet.damage
				enemy.hit = 0.12
				shake = max(shake, 1.5)
				burst(enemy.pos, Color("#ffd15c"), 4)
	bullets = bullets.filter(func(b): return b.life > 0.0 and Rect2(Vector2(-60, -60), WORLD_SIZE + Vector2(120, 120)).has_point(b.pos))

func update_enemies(delta: float) -> void:
	for enemy in enemies:
		enemy.hit = max(0.0, enemy.hit - delta)
		var dir: Vector2 = enemy.pos.direction_to(player.pos)
		if enemy.type == "shooter":
			var distance_to_player: float = enemy.pos.distance_to(player.pos)
			if distance_to_player < 230.0:
				enemy.pos -= dir * enemy.speed * 0.72 * delta
			elif distance_to_player > 330.0:
				enemy.pos += dir * enemy.speed * 0.54 * delta
			enemy.shoot_timer -= delta
			if enemy.shoot_timer <= 0.0:
				enemy.shoot_timer = rng.randf_range(1.2, 1.65)
				enemy_bullets.append({"pos": enemy.pos, "vel": dir * 240.0, "life": 2.0, "radius": 5.0})
				burst(enemy.pos, Color("#ff4e64"), 3)
		elif enemy.type == "brute":
			enemy.pos += dir * enemy.speed * delta
			enemy.shoot_timer -= delta
			if enemy.shoot_timer <= 0.0:
				enemy.shoot_timer = rng.randf_range(1.8, 2.3)
				for angle in [-18.0, 0.0, 18.0]:
					enemy_bullets.append({"pos": enemy.pos, "vel": dir.rotated(deg_to_rad(angle)) * 210.0, "life": 2.2, "radius": 6.0})
				burst(enemy.pos, Color("#ff4e64"), 5)
		else:
			enemy.pos += dir * enemy.speed * delta
		for stall in stalls:
			push_circle_out(enemy, stall)
		if enemy.pos.distance_to(player.pos) < enemy.radius + player.radius and invuln_timer <= 0.0:
			player.hp -= 1
			invuln_timer = 0.85
			shake = 6.0
			burst(player.pos, Color("#ff4e64"), 10)
	for enemy in enemies:
		if enemy.hp <= 0:
			drops.append({"pos": enemy.pos, "radius": 7.0})
			burst(enemy.pos, Color("#37f4d0"), 8)
	enemies = enemies.filter(func(e): return e.hp > 0)

func update_enemy_bullets(delta: float) -> void:
	for bullet in enemy_bullets:
		bullet.pos += bullet.vel * delta
		bullet.life -= delta
		if bullet.life > 0.0 and bullet.pos.distance_to(player.pos) < bullet.radius + player.radius and invuln_timer <= 0.0:
			bullet.life = 0.0
			player.hp -= 1
			invuln_timer = 0.75
			shake = 5.0
			burst(player.pos, Color("#ff4e64"), 9)
	enemy_bullets = enemy_bullets.filter(func(b): return b.life > 0.0 and Rect2(Vector2(-80, -80), WORLD_SIZE + Vector2(160, 160)).has_point(b.pos))

func update_hazards(delta: float) -> void:
	for hazard in hazards:
		if hazard.warn > 0.0:
			hazard.warn -= delta
		else:
			hazard.active -= delta
			if hazard.rect.has_point(player.pos) and invuln_timer <= 0.0:
				player.hp -= 1
				invuln_timer = 0.75
				shake = 5.0
				burst(player.pos, Color("#ff4e64"), 9)
	hazards = hazards.filter(func(h): return h.active > 0.0)

func update_drops(delta: float) -> void:
	for drop in drops:
		var distance: float = drop.pos.distance_to(player.pos)
		if distance < gem_magnet_radius:
			drop.pos = drop.pos.lerp(player.pos, delta * 8.0)
		if distance < player.radius + drop.radius + 3.0:
			drop.dead = true
			gems += 1
			burst(drop.pos, Color("#ffd15c"), 6)
	drops = drops.filter(func(g): return not g.has("dead"))

func update_particles(delta: float) -> void:
	for particle in particles:
		particle.pos += particle.vel * delta
		particle.vel *= pow(0.025, delta)
		particle.life -= delta
	particles = particles.filter(func(p): return p.life > 0.0)

func push_circle_out(circle: Dictionary, rect: Rect2) -> void:
	var nearest: Vector2 = circle.pos.clamp(rect.position, rect.end)
	var push_delta: Vector2 = circle.pos - nearest
	var distance: float = push_delta.length()
	if distance > 0.0 and distance < circle.radius + 2.0:
		circle.pos += push_delta.normalized() * (circle.radius + 2.0 - distance)

func burst(pos: Vector2, color: Color, count: int) -> void:
	for i in min(count, 8):
		var angle := rng.randf_range(0.0, TAU)
		var speed := rng.randf_range(34.0, 145.0)
		particles.append({"pos": pos, "vel": Vector2.from_angle(angle) * speed, "life": rng.randf_range(0.16, 0.34), "color": color})

func _draw() -> void:
	var offset := Vector2(rng.randf_range(-shake, shake), rng.randf_range(-shake, shake)) * 0.5
	draw_set_transform(offset)
	draw_market()
	draw_hazards()
	draw_spawn_telegraphs()
	draw_drops()
	draw_bullets()
	draw_enemy_bullets()
	draw_enemies()
	draw_player()
	draw_particles()
	draw_set_transform(Vector2.ZERO)
	draw_hud()

func draw_market() -> void:
	draw_rect(Rect2(Vector2.ZERO, WORLD_SIZE), Color("#071114"))
	draw_rect(Rect2(64, 92, 1152, 560), Color(0.04, 0.13, 0.14, 0.46), true)
	draw_rect(Rect2(64, 92, 1152, 560), Color(0.22, 0.96, 0.82, 0.08), false, 2.0)
	for y in [216, 504]:
		draw_line(Vector2(112, y), Vector2(1168, y), Color(0.22, 0.96, 0.82, 0.025), 1.0)
	for stall in stalls:
		draw_rect(stall, Color(0.22, 0.18, 0.1, 0.42), true)
		draw_rect(stall, Color(0.95, 0.76, 0.32, 0.10), false, 1.0)

func draw_hazards() -> void:
	for hazard in hazards:
		var color := Color(1.0, 0.3, 0.4, 0.06) if hazard.warn > 0.0 else Color(1.0, 0.3, 0.4, 0.34)
		draw_rect(hazard.rect, color, true)
		draw_rect(hazard.rect, Color(1.0, 0.85, 0.85, 0.36), false, 1.0)

func draw_spawn_telegraphs() -> void:
	for spawn in pending_spawns:
		var ratio: float = clamp(spawn.timer / SPAWN_TELEGRAPH_TIME, 0.0, 1.0)
		var radius: float = lerp(30.0, 13.0, 1.0 - ratio)
		draw_arc(spawn.pos, radius, 0.0, TAU, 32, Color(1.0, 0.82, 0.36, 0.7), 2.0)
		draw_circle(spawn.pos, 4.0, Color(1.0, 0.82, 0.36, 0.5))

func draw_player() -> void:
	if dash_time > 0.0:
		draw_line(player.pos - player.vel * 0.04, player.pos, Color(0.22, 0.96, 0.82, 0.72), 10.0)
	var color := Color.WHITE if invuln_timer > 0.0 and int(Time.get_ticks_msec() / 70) % 2 == 0 else Color("#37f4d0")
	var p: Vector2 = player.pos
	draw_circle(p + Vector2(0, 7), 17.0, Color("#071114"))
	draw_colored_polygon(PackedVector2Array([
		p + Vector2(0, -23),
		p + Vector2(18, -2),
		p + Vector2(13, 22),
		p + Vector2(-13, 22),
		p + Vector2(-18, -2),
	]), color)
	draw_polyline(PackedVector2Array([
		p + Vector2(0, -23),
		p + Vector2(18, -2),
		p + Vector2(13, 22),
		p + Vector2(-13, 22),
		p + Vector2(-18, -2),
		p + Vector2(0, -23),
	]), Color("#e8fff8"), 2.0)
	draw_circle(p + Vector2(0, -4), 8.0, Color("#071114"))
	draw_circle(p + Vector2(4, -6), 2.4, Color("#e8fff8"))
	draw_line(p + Vector2(-16, 10), p + Vector2(16, 10), Color("#ffd15c"), 3.0)

func draw_enemies() -> void:
	for enemy in enemies:
		draw_enemy(enemy)

func draw_enemy(enemy: Dictionary) -> void:
	var p: Vector2 = enemy.pos
	var color := Color.WHITE if enemy.hit > 0.0 else Color("#ff4e64")
	if enemy.type == "runner":
		color = Color.WHITE if enemy.hit > 0.0 else Color("#ff8b4f")
		draw_circle(p, 17.0, Color("#071114"))
		draw_colored_polygon(PackedVector2Array([
			p + Vector2(0, -17),
			p + Vector2(18, 14),
			p + Vector2(-18, 14),
		]), color)
		draw_polyline(PackedVector2Array([p + Vector2(0, -17), p + Vector2(18, 14), p + Vector2(-18, 14), p + Vector2(0, -17)]), Color("#ffe1ca"), 2.0)
		draw_circle(p + Vector2(0, 3), 4.0, Color("#071114"))
	elif enemy.type == "shooter":
		color = Color.WHITE if enemy.hit > 0.0 else Color("#c85cff")
		draw_circle(p, 20.0, Color("#071114"))
		draw_colored_polygon(PackedVector2Array([
			p + Vector2(0, -19),
			p + Vector2(18, 0),
			p + Vector2(0, 19),
			p + Vector2(-18, 0),
		]), color)
		draw_polyline(PackedVector2Array([p + Vector2(0, -19), p + Vector2(18, 0), p + Vector2(0, 19), p + Vector2(-18, 0), p + Vector2(0, -19)]), Color("#f1d6ff"), 2.0)
		draw_circle(p, 6.0, Color("#071114"))
		draw_circle(p, 2.5, Color("#ff6d83"))
	elif enemy.type == "brute":
		color = Color.WHITE if enemy.hit > 0.0 else Color("#e2455d")
		draw_circle(p, 30.0, Color("#071114"))
		draw_rect(Rect2(p - Vector2(23, 23), Vector2(46, 46)), color, true)
		draw_rect(Rect2(p - Vector2(23, 23), Vector2(46, 46)), Color("#ffd0d6"), false, 2.0)
		draw_circle(p + Vector2(-8, -4), 4.0, Color("#071114"))
		draw_circle(p + Vector2(8, -4), 4.0, Color("#071114"))
		draw_line(p + Vector2(-10, 11), p + Vector2(10, 11), Color("#071114"), 4.0)
	else:
		draw_circle(p, 20.0, Color("#071114"))
		draw_circle(p, 16.0, color)
		draw_arc(p, 17.5, 0.0, TAU, 18, Color(1, 0.95, 0.95, 0.62), 2.0)
		draw_circle(p + Vector2(-5, -4), 3.0, Color("#071114"))
		draw_circle(p + Vector2(5, -4), 3.0, Color("#071114"))
		draw_line(p + Vector2(-7, 7), p + Vector2(7, 7), Color("#071114"), 3.0)

func draw_bullets() -> void:
	for bullet in bullets:
		draw_circle(bullet.pos, bullet.radius, Color("#b9fff1"))

func draw_enemy_bullets() -> void:
	for bullet in enemy_bullets:
		draw_circle(bullet.pos, bullet.radius, Color("#ff6d83"))
		draw_arc(bullet.pos, bullet.radius + 2.0, 0.0, TAU, 12, Color(1.0, 0.85, 0.88, 0.48), 1.0)

func draw_drops() -> void:
	for drop in drops:
		var p: Vector2 = drop.pos
		draw_colored_polygon(PackedVector2Array([p + Vector2(0, -9), p + Vector2(8, 0), p + Vector2(0, 9), p + Vector2(-8, 0)]), Color("#ffd15c"))
		draw_polyline(PackedVector2Array([p + Vector2(0, -9), p + Vector2(8, 0), p + Vector2(0, 9), p + Vector2(-8, 0), p + Vector2(0, -9)]), Color("#fff2bf"), 1.5)

func draw_particles() -> void:
	for particle in particles:
		var alpha: float = clamp(particle.life / 0.34, 0.0, 0.72)
		var color: Color = particle.color
		color.a = alpha
		draw_circle(particle.pos, 3.0, color)

func draw_hud() -> void:
	var font := ThemeDB.fallback_font
	var plan := get_wave_plan()
	var line := "%s   Wave %d/3   HP %d   Gems %d   Damage %d   Dash %s" % [plan.name, wave, max(0, player.hp), gems, player.damage, "Ready" if dash_timer <= 0.0 else "%.1f" % dash_timer]
	draw_string(font, Vector2(24, 34), line, HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color("#e8fff8"))
	draw_string(font, Vector2(24, 64), "WASD/Arrows move  Mouse hold manual fire  Space dash  R restart", HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color("#8bb2aa"))
	if not chosen_upgrades.is_empty():
		draw_string(font, Vector2(24, 91), "Upgrades: " + ", ".join(chosen_upgrades), HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color("#ffd15c"))
	if mode != "playing":
		draw_rect(Rect2(Vector2.ZERO, WORLD_SIZE), Color(0, 0, 0, 0.48), true)
		draw_string(font, Vector2(365, 310), "Night Market Dash", HORIZONTAL_ALIGNMENT_LEFT, -1, 44, Color("#e8fff8"))
		draw_string(font, Vector2(365, 356), message, HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color("#ffd15c"))
		if mode == "upgrade":
			draw_string(font, Vector2(365, 392), "1 Fire faster   2 Damage + magnet   3 Dash cooldown + heal", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color("#e8fff8"))
