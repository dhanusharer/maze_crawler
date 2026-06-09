try:
    _ = TACTICS_PARAMS
except NameError:
    TACTICS_PARAMS = {
        "WORKER_THRESHOLD": 2,
        "SAFETY_BUFFER": 2
    }

from pathfinder import find_path, find_reachable_paths, project_south_bound

class EnemyTracker:
    def __init__(self):
        self.col_min = None
        self.col_max = None
        self.row_min = None
        self.row_max = None
        self.last_seen_step = -1
        self.jump_cd = 0
        self.last_exact_pos = None

    def update(self, obs, config):
        # Decrement jump cooldown
        self.jump_cd = max(0, self.jump_cd - 1)
        
        # 1. Search for actual visible enemy factory
        found = False
        for uid, data in obs.robots.items():
            rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
            if owner != obs.player and rtype == 0:  # Enemy Factory
                # Check if position changed by 2 cells in one step -> Jump detected
                if self.last_exact_pos:
                    dist = abs(col - self.last_exact_pos[0]) + abs(row - self.last_exact_pos[1])
                    if dist == 2 or abs(col - self.last_exact_pos[0]) == 2 or abs(row - self.last_exact_pos[1]) == 2:
                        self.jump_cd = 20
                
                self.col_min = col
                self.col_max = col
                self.row_min = row
                self.row_max = row
                self.last_seen_step = obs.step
                self.last_exact_pos = (col, row)
                
                # Sync directly with visible jump_cd if available
                if len(data) > 6:
                    self.jump_cd = data[6]
                    
                found = True
                break
        
        # 2. Bounding box expansion if hidden under fog
        if not found:
            if self.col_min is None:
                # Initialize using horizontal mirror of our Factory
                our_col, our_row = 5, 2
                for uid, data in obs.robots.items():
                    if data[4] == obs.player and data[0] == 0:
                        our_col, our_row = data[1], data[2]
                        break
                self.col_min = config.width - 1 - our_col
                self.col_max = config.width - 1 - our_col
                self.row_min = our_row
                self.row_max = our_row
                self.last_exact_pos = (self.col_min, self.row_min)
                self.last_seen_step = obs.step
            else:
                # Expand bounding box by 1 row/col every 2 turns
                turns_since_seen = obs.step - self.last_seen_step
                if turns_since_seen > 0 and turns_since_seen % 2 == 0:
                    self.col_min = max(0, self.col_min - 1)
                    self.col_max = min(config.width - 1, self.col_max + 1)
                    self.row_min = max(obs.southBound + 1, self.row_min + (1 if obs.step > 250 else 0))
                    self.row_max = min(obs.northBound, self.row_max + 1)

def find_doorways(cartographer):
    door_rows = []
    w = cartographer.width
    c1 = w // 2 - 1
    c2 = w // 2
    # Scan rows from south_bound to north_bound
    for r in range(cartographer.south_bound, cartographer.north_bound + 1):
        if (c1, r) in cartographer.global_map or (c2, r) in cartographer.global_map:
            if not cartographer.is_wall(c1, r, "EAST"):
                door_rows.append(r)
    return door_rows

class TacticalController:
    def __init__(self):
        self.built_walls = set()  # Track walls we've built: (col, row, direction)

    def assign_tactical_goals(self, obs, cartographer, friendly_units, enemy_tracker, config):
        door_rows = find_doorways(cartographer)
        w = cartographer.width
        c1 = w // 2 - 1
        c2 = w // 2
        our_side_col = c1 if obs.player == 0 else c2
        enemy_side_col = c2 if obs.player == 0 else c1

        # --- Counter-Wall Re-Trapping: detect cleared walls and queue re-builds ---
        retrap_overrides = {}  # uid -> build_action_string
        cleared_walls = set()
        for (wc, wr, wdir) in list(self.built_walls):
            # Remove walls that have scrolled below the boundary
            if wr < obs.southBound:
                self.built_walls.discard((wc, wr, wdir))
                continue
            # Check if the wall still exists
            if not cartographer.is_wall(wc, wr, wdir):
                cleared_walls.add((wc, wr, wdir))

        # For each cleared wall, find an adjacent alive Worker to re-build it
        if cleared_walls:
            workers_list = [(uid, u) for uid, u in friendly_units.items() if u["type"] == 2]
            for (wc, wr, wdir) in cleared_walls:
                for w_uid, w_unit in workers_list:
                    if w_uid in retrap_overrides:
                        continue
                    if w_unit["col"] == wc and w_unit["row"] == wr:
                        # Worker is on the exact cell — rebuild
                        if w_unit["energy"] >= 100:
                            retrap_overrides[w_uid] = f"BUILD_{wdir}"
                            break

        # Group friendly robots by type
        scouts = []
        workers = []
        miners = []
        for uid, unit in friendly_units.items():
            if unit["type"] == 1:
                scouts.append((uid, unit))
            elif unit["type"] == 2:
                workers.append((uid, unit))
            elif unit["type"] == 3:
                miners.append((uid, unit))

        # Sort to ensure consistent behavior
        scouts.sort(key=lambda x: x[0])
        workers.sort(key=lambda x: x[0])
        miners.sort(key=lambda x: x[0])

        tactical_targets = {}  # uid -> target_cell
        worker_trap_actions = {}  # uid -> build_action_string
        should_build_worker = False

        # Enemy Factory projected center position
        ef_col = (enemy_tracker.col_min + enemy_tracker.col_max) // 2
        ef_row = enemy_tracker.row_max  # Target row_max for safety containment

        # --- Counter-Wall Re-Trapping: detect cleared walls and queue re-builds ---
        retrap_overrides = {}  # uid -> build_action_string
        cleared_walls = set()
        for (wc, wr, wdir) in list(self.built_walls):
            # Remove walls that have scrolled below the boundary
            if wr < obs.southBound:
                self.built_walls.discard((wc, wr, wdir))
                continue
            # Check if the wall still exists
            if not cartographer.is_wall(wc, wr, wdir):
                cleared_walls.add((wc, wr, wdir))

        # For each cleared wall, find an adjacent alive Worker to re-build it
        if cleared_walls:
            for (wc, wr, wdir) in cleared_walls:
                for w_uid, w_unit in workers:
                    if w_uid in retrap_overrides:
                        continue
                    if w_unit["col"] == wc and w_unit["row"] == wr:
                        if w_unit["energy"] >= 100:
                            retrap_overrides[w_uid] = f"BUILD_{wdir}"
                            break

        # --- Adversarial Doorway Welding + Double-Lock airlift ---
        tracking_center_row = (enemy_tracker.row_min + enemy_tracker.row_max) // 2
        active_door_rows = [r for r in door_rows if r >= obs.southBound]
        target_door_row = None
        min_door_dist = float('inf')
        for r in active_door_rows:
            dist = abs(tracking_center_row - r)
            if dist <= 3 and dist < min_door_dist:
                min_door_dist = dist
                target_door_row = r

        best_sec_uid = None
        double_lock_col = None
        is_primary_built = False
        build_dir = "EAST" if obs.player == 0 else "WEST"
        
        if target_door_row is not None:
            double_lock_col = our_side_col - 1 if obs.player == 0 else our_side_col + 1
            is_primary_built = cartographer.is_wall(our_side_col, target_door_row, build_dir)
            
            # Find primary worker
            primary_worker_uid = None
            best_p_dist = float('inf')
            for w_uid, w_unit in workers:
                dist = abs(w_unit["col"] - our_side_col) + abs(w_unit["row"] - target_door_row)
                if dist < best_p_dist:
                    best_p_dist = dist
                    primary_worker_uid = w_uid
                    
            if is_primary_built:
                # Find best secondary unit (Scout or other Worker)
                best_sec_dist = float('inf')
                candidates = []
                for s_uid, s_unit in scouts:
                    candidates.append((s_uid, s_unit))
                for w_uid, w_unit in workers:
                    if w_uid != primary_worker_uid:
                        candidates.append((w_uid, w_unit))
                        
                for c_uid, c_unit in candidates:
                    dist = abs(c_unit["col"] - double_lock_col) + abs(c_unit["row"] - target_door_row)
                    if dist < best_sec_dist:
                        best_sec_dist = dist
                        best_sec_uid = c_uid
                        
                if best_sec_uid:
                    tactical_targets[best_sec_uid] = (double_lock_col, target_door_row)

        # 1. Scout Resource Starvation & Interception
        scroll_counter = getattr(obs, "scrollCounter", 4)
        enemy_paths = {}
        if ef_col is not None and ef_row is not None:
            enemy_paths = find_reachable_paths(
                cartographer, (ef_col, ef_row),
                obs.step, obs.southBound, scroll_counter,
                getattr(config, "factoryMovePeriod", 2), config,
                max_depth=10, initial_jump_cd=enemy_tracker.jump_cd
            )

        assigned_targets = set()
        if target_door_row is not None:
            assigned_targets.add((our_side_col, target_door_row))
            assigned_targets.add((double_lock_col, target_door_row))

        for i, (s_uid, s_unit) in enumerate(scouts):
            if i <= 1:
                if s_uid in tactical_targets:
                    assigned_targets.add(tactical_targets[s_uid])
                    continue  # assigned to double lock
                
                # Snatch crystals from enemy Factory's path
                intercept_target = None
                best_crystal_priority = -1
                
                for key, val in obs.crystals.items():
                    try:
                        cc, cr = map(int, key.split(","))
                        if (cc, cr) in enemy_paths:
                            enemy_path_len = len(enemy_paths[(cc, cr)])
                            enemy_arrival_turns = getattr(config, "factoryMovePeriod", 2) * enemy_path_len
                            
                            p = find_path(
                                cartographer, (s_unit["col"], s_unit["row"]), (cc, cr),
                                obs.step, obs.southBound, scroll_counter,
                                1, config
                            )
                            if p is not None:
                                scout_arrival_turns = len(p)
                                if scout_arrival_turns <= enemy_arrival_turns - 1:
                                    if (cc, cr) not in assigned_targets:
                                        priority = val - scout_arrival_turns
                                        if priority > best_crystal_priority:
                                            best_crystal_priority = priority
                                            intercept_target = (cc, cr)
                    except Exception:
                        pass
                
                if intercept_target:
                    tactical_targets[s_uid] = intercept_target
                    assigned_targets.add(intercept_target)
                else:
                    # Fallback to standard starvation vacuuming
                    starve_crystals = []
                    for key in obs.crystals.keys():
                        try:
                            cc, cr = map(int, key.split(","))
                            dist_to_path = abs(cc - ef_col)
                            if dist_to_path <= 5 and cr >= ef_row - 2 and cr <= ef_row + 10:
                                if (cc, cr) not in assigned_targets:
                                    starve_crystals.append((cc, cr))
                        except ValueError:
                            pass
                    
                    if starve_crystals:
                        starve_crystals.sort(key=lambda pos: abs(pos[0] - s_unit["col"]) + abs(pos[1] - s_unit["row"]))
                        tactical_targets[s_uid] = starve_crystals[0]
                        assigned_targets.add(starve_crystals[0])
                    elif door_rows and (ef_col, enemy_tracker.row_max) not in assigned_targets:
                        tactical_targets[s_uid] = (ef_col, enemy_tracker.row_max)
                        assigned_targets.add((ef_col, enemy_tracker.row_max))
                    else:
                        row_candidate = max(obs.southBound, min(s_unit["row"], obs.northBound))
                        while (our_side_col, row_candidate) in assigned_targets and row_candidate > obs.southBound:
                            row_candidate -= 1
                        tactical_targets[s_uid] = (our_side_col, row_candidate)
                        assigned_targets.add((our_side_col, row_candidate))

        # 2. Worker Wall Trap Containment (with counter-wall re-trapping)
        for w_uid, w_unit in workers:
            # Check if this worker is the secondary double-lock worker
            if w_uid == best_sec_uid:
                if w_unit["col"] == double_lock_col and w_unit["row"] == target_door_row:
                    if is_primary_built and not cartographer.is_wall(double_lock_col, target_door_row, build_dir):
                        if w_unit["energy"] >= 100:
                            worker_trap_actions[w_uid] = f"BUILD_{build_dir}"
                            self.built_walls.add((double_lock_col, target_door_row, build_dir))
                tactical_targets[w_uid] = (double_lock_col, target_door_row)
                continue

            # Counter-wall re-trap override takes highest priority
            if w_uid in retrap_overrides:
                worker_trap_actions[w_uid] = retrap_overrides[w_uid]
                tactical_targets[w_uid] = (w_unit["col"], w_unit["row"])
                continue

            w_col, w_row = w_unit["col"], w_unit["row"]

            # --- Adversarial Doorway Welding ---
            if target_door_row is not None:
                # Throat of the doorway tile on our side
                target_cell = (our_side_col, target_door_row)
                if w_col == our_side_col and w_row == target_door_row:
                    if not cartographer.is_wall(w_col, w_row, build_dir):
                        if w_unit["energy"] >= 100:
                            worker_trap_actions[w_uid] = f"BUILD_{build_dir}"
                            self.built_walls.add((w_col, w_row, build_dir))
                        tactical_targets[w_uid] = (w_col, w_row)
                else:
                    tactical_targets[w_uid] = target_cell
                continue

            # --- Standard Containment Trapping ---
            target_cell = (ef_col, ef_row + 1)

            # Check if adjacent to the enemy Factory's cell and block it
            if w_row == ef_row + 1 and w_col == ef_col:
                if not cartographer.is_wall(w_col, w_row, "SOUTH"):
                    worker_trap_actions[w_uid] = "BUILD_SOUTH"
                    tactical_targets[w_uid] = (w_col, w_row)
                    self.built_walls.add((w_col, w_row, "SOUTH"))
            elif w_row == ef_row and w_col == ef_col - 1:
                if not cartographer.is_wall(w_col, w_row, "EAST"):
                    worker_trap_actions[w_uid] = "BUILD_EAST"
                    tactical_targets[w_uid] = (w_col, w_row)
                    self.built_walls.add((w_col, w_row, "EAST"))
            elif w_row == ef_row and w_col == ef_col + 1:
                if not cartographer.is_wall(w_col, w_row, "WEST"):
                    worker_trap_actions[w_uid] = "BUILD_WEST"
                    tactical_targets[w_uid] = (w_col, w_row)
                    self.built_walls.add((w_col, w_row, "WEST"))
            else:
                # Path to trap position
                tactical_targets[w_uid] = target_cell

        # 3. Symmetrical Door Camping
        enemy_units = []
        for uid, data in obs.robots.items():
            rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
            if owner != obs.player:
                enemy_units.append((col, row, rtype))

        used_guardians = set()
        for d_row in door_rows:
            our_door_cell = (our_side_col, d_row)
            enemy_door_cell = (enemy_side_col, d_row)

            # Check if any enemy unit is close to the door on their side (distance <= 2)
            enemy_near = False
            for ec, er, etype in enemy_units:
                if abs(ec - enemy_door_cell[0]) + abs(er - enemy_door_cell[1]) <= 2:
                    enemy_near = True
                    break

            if enemy_near:
                best_guardian = None
                best_dist = float('inf')
                potential_guardians = workers
                
                for g_uid, g_unit in potential_guardians:
                    if g_uid in used_guardians or g_uid in tactical_targets:
                        continue
                    dist = abs(g_unit["col"] - our_door_cell[0]) + abs(g_unit["row"] - our_door_cell[1])
                    if dist < best_dist and dist < 10:
                        best_dist = dist
                        best_guardian = g_uid

                if best_guardian:
                    tactical_targets[best_guardian] = our_door_cell
                    used_guardians.add(best_guardian)

        # 4. Offensive Worker Spawning Authorization:
        # High confidence = bounding box width and height <= WORKER_THRESHOLD, and doors are mapped, and we have 0 workers
        is_high_confidence = (
            (enemy_tracker.col_max - enemy_tracker.col_min) <= TACTICS_PARAMS["WORKER_THRESHOLD"] and
            (enemy_tracker.row_max - enemy_tracker.row_min) <= TACTICS_PARAMS["WORKER_THRESHOLD"]
        )
        if len(door_rows) > 0 and is_high_confidence and len(workers) == 0:
            should_build_worker = True

        return tactical_targets, worker_trap_actions, should_build_worker
