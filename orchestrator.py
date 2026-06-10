try:
    _ = TACTICS_PARAMS
except NameError:
    TACTICS_PARAMS = {
        "WORKER_THRESHOLD": 2,
        "SAFETY_BUFFER": 2
    }

import time
from pathfinder import find_reachable_paths, project_south_bound, find_path
from economy import MacroManager
from tactician import EnemyTracker, TacticalController

class TrafficController:
    def __init__(self, enable_tactics=True):
        self.unit_paths = {}  # uid -> list of (col, row)
        self.unit_targets = {}  # uid -> (col, row)
        self.macro_manager = MacroManager()
        self.enable_tactics = enable_tactics
        self.enemy_tracker = EnemyTracker()
        self.tactical_controller = TacticalController()
        self.last_turn_elapsed = None
        self.max_depth = 15
        self.factory_reservations = set()

    def _is_fixed_wall(self, cartographer, col, row, direction):
        width = cartographer.width
        if direction == "WEST" and col == 0:
            return True
        if direction == "EAST" and col == width - 1:
            return True
        if direction == "EAST" and col == width // 2 - 1:
            return True
        if direction == "WEST" and col == width // 2:
            return True
        return False

    def _action_destination(self, col, row, action):
        if not action:
            return (col, row)
        if action in ("NORTH", "SOUTH", "EAST", "WEST"):
            dc, dr = {
                "NORTH": (0, 1),
                "SOUTH": (0, -1),
                "EAST": (1, 0),
                "WEST": (-1, 0)
            }[action]
            return (col + dc, row + dr)
        if action.startswith("JUMP_"):
            direction = action.split("_", 1)[1]
            dc, dr = {
                "NORTH": (0, 1),
                "SOUTH": (0, -1),
                "EAST": (1, 0),
                "WEST": (-1, 0)
            }[direction]
            return (col + dc * 2, row + dr * 2)
        return (col, row)

    def _broadcast_factory_reservations(self, factory_uid, friendly_units, actions, horizon=5):
        self.factory_reservations = set()
        if not factory_uid or factory_uid not in friendly_units:
            return

        factory = friendly_units[factory_uid]
        col, row = factory["col"], factory["row"]
        self.factory_reservations.add((col, row, 0))

        trajectory = []
        action_dest = self._action_destination(col, row, actions.get(factory_uid))
        if action_dest != (col, row):
            trajectory.append(action_dest)

        for pos in self.unit_paths.get(factory_uid) or []:
            if len(trajectory) >= horizon:
                break
            trajectory.append(pos)

        for offset, (r_col, r_row) in enumerate(trajectory[:horizon], start=1):
            self.factory_reservations.add((r_col, r_row, offset))

    def _path_clearing_action(self, uid, unit, cartographer, obs, config, reserved_cells, enemy_positions, scroll_counter, move_period):
        if unit["type"] not in (1, 2) or not self.factory_reservations:
            return None

        col, row = unit["col"], unit["row"]
        reserved_track = {(c, r) for c, r, _ in self.factory_reservations}
        planned_path = self.unit_paths.get(uid) or []
        planned_next = planned_path[0] if planned_path else None
        if (col, row) not in reserved_track and planned_next not in reserved_track:
            return None

        projected_south = project_south_bound(
            obs.step, obs.southBound, scroll_counter, move_period, config
        )

        candidates = []
        for direction in ["EAST", "WEST", "NORTH", "SOUTH"]:
            if not cartographer.is_walkable(col, row, direction):
                continue
            dc, dr = cartographer.DIR_OFFSETS[direction]
            nc, nr = col + dc, row + dr
            n_pos = (nc, nr)
            if n_pos in reserved_track:
                continue
            if n_pos in reserved_cells and reserved_cells[n_pos] != uid:
                continue
            if n_pos in enemy_positions:
                continue
            if nr < projected_south or nr > cartographer.north_bound:
                continue

            if reserved_track:
                distance = min(abs(nc - rc) + abs(nr - rr) for rc, rr in reserved_track)
            else:
                distance = 0
            side_bonus = 100 if direction in ("EAST", "WEST") else 0
            score = side_bonus + distance * 10 + nr
            candidates.append((score, direction, n_pos))

        if candidates:
            candidates.sort(reverse=True)
            _, direction, n_pos = candidates[0]
            return direction, n_pos

        if unit["type"] == 2 and unit["energy"] >= 100:
            for direction in ["EAST", "WEST"]:
                if cartographer.is_wall(col, row, direction) and not self._is_fixed_wall(cartographer, col, row, direction):
                    return f"REMOVE_{direction}", (col, row)

        return "IDLE", (col, row)

    def find_blocking_wall(self, cartographer, factory_pos, obs, config):
        """
        BFS ignoring standard walls but respecting fixed walls to find the first
        standard wall blocking the Factory from moving northward.
        """
        width = cartographer.width
        
        def is_fixed_wall(c, r, direction):
            if direction == "WEST" and c == 0:
                return True
            if direction == "EAST" and c == width - 1:
                return True
            if direction == "EAST" and c == width // 2 - 1:
                return True
            if direction == "WEST" and c == width // 2:
                return True
            return False

        from collections import deque
        queue = deque([(factory_pos[0], factory_pos[1], [])])
        visited = {factory_pos}
        target_row = factory_pos[1] + 2
        
        scroll_counter = getattr(obs, "scrollCounter", 4)
        
        while queue:
            c, r, path = queue.popleft()
            if r >= target_row:
                # Trace back to find the first transition blocked by a standard wall
                for vc, vr, d, nc, nr in path:
                    if cartographer.is_wall(vc, vr, d):
                        if not is_fixed_wall(vc, vr, d):
                            return (vc, vr), d
                return None
                
            for direction, offset in cartographer.DIR_OFFSETS.items():
                nc, nr = c + offset[0], r + offset[1]
                if nc < 0 or nc >= width or nr < 0:
                    continue
                if is_fixed_wall(c, r, direction):
                    continue
                    

                    
                if (nc, nr) not in visited:
                    visited.add((nc, nr))
                    queue.append((nc, nr, path + [(c, r, direction, nc, nr)]))
                    
        return None

    def process_turn(self, obs, cartographer, config):
        """
        Coordinates movement intents for all friendly units to avoid collisions.
        Returns:
            dict of actions mapping uid -> action_string.
        """
        start_time = time.time()
        
        if self.last_turn_elapsed is not None and self.last_turn_elapsed < 0.1:
            self.max_depth = 25
        else:
            self.max_depth = 15

        player = obs.player
        scroll_counter = getattr(obs, "scrollCounter", 4)
        actions = {}
        dynamic_safety_buffer = max(2, min(5, 2 + (obs.step // 120)))
        is_seeking_mine = False
        is_chasing_enemy = False
        
        # 1. Update macro manager with global observations
        self.macro_manager.update(obs)
        
        # 2. Identify all friendly units and their state
        friendly_units = {}
        for uid, data in obs.robots.items():
            rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
            if owner == player:
                friendly_units[uid] = {
                    "type": rtype,
                    "col": col,
                    "row": row,
                    "energy": energy,
                    "move_cd": data[5],
                    "jump_cd": data[6],
                    "build_cd": data[7] if len(data) > 7 else 0
                }
                
        # 2_enemy. Identify all enemy unit positions as blocked cells
        enemy_positions = set()
        enemy_factory_energy = 0
        for uid, data in obs.robots.items():
            rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
            if owner != player:
                enemy_positions.add((col, row))
                if rtype == 0:
                    enemy_factory_energy = energy
                
        # 2b. Update tactics tracking and get target overrides
        self.enemy_tracker.update(obs, config)
        tactical_targets = {}
        worker_trap_actions = {}
        should_build_worker = False
        if self.enable_tactics:
            tactical_targets, worker_trap_actions, should_build_worker = self.tactical_controller.assign_tactical_goals(
                obs, cartographer, friendly_units, self.enemy_tracker, config
            )

        # 2c. Death-Row Salvage: doomed Scouts/Workers near south boundary dump energy to Factory
        factory_pos_for_salvage = None
        for uid, unit in friendly_units.items():
            if unit["type"] == 0:
                factory_pos_for_salvage = (unit["col"], unit["row"])
                break

        if factory_pos_for_salvage:
            projected_south_3 = project_south_bound(
                obs.step, obs.southBound, scroll_counter, 3, config
            )
            for uid, unit in friendly_units.items():
                if unit["type"] not in (1, 2):  # Only Scouts and Workers
                    continue
                if uid in tactical_targets:
                    continue  # Don't override existing tactical assignment
                u_row = unit["row"]
                u_col = unit["col"]
                # Check if the unit will be swallowed within 3 turns
                if u_row < projected_south_3:
                    # Check if adjacent to Factory (Manhattan distance 1, no wall)
                    dx = factory_pos_for_salvage[0] - u_col
                    dy = factory_pos_for_salvage[1] - u_row
                    manhattan = abs(dx) + abs(dy)
                    if manhattan == 1:
                        # Determine transfer direction
                        transfer_dir = None
                        if (dx, dy) == (0, 1):
                            transfer_dir = "NORTH"
                        elif (dx, dy) == (0, -1):
                            transfer_dir = "SOUTH"
                        elif (dx, dy) == (1, 0):
                            transfer_dir = "EAST"
                        elif (dx, dy) == (-1, 0):
                            transfer_dir = "WEST"
                        if transfer_dir and not cartographer.is_wall(u_col, u_row, transfer_dir):
                            # Override: force TRANSFER to dump energy into Factory
                            tactical_targets[uid] = (u_col, u_row)  # Stay in place
                            worker_trap_actions[uid] = f"TRANSFER_{transfer_dir}"
                            continue
                    # Not adjacent — route toward Factory
                    tactical_targets[uid] = factory_pos_for_salvage
                
        # 3. Initialize space-time booking registry with all current friendly positions
        # This prevents other units from moving onto occupied cells unless the occupant vacates.
        reserved_cells = {}  # (col, row) -> uid
        for uid, unit in friendly_units.items():
            reserved_cells[(unit["col"], unit["row"])] = uid
        
        # 4. Identify active vs stationary units
        stationary_uids = []
        active_uids = []
        for uid, unit in friendly_units.items():
            if unit["energy"] == 0 or unit["move_cd"] > 0:
                stationary_uids.append(uid)
            else:
                active_uids.append(uid)
                
        # 5. Check Factory spawn intent using CFO
        factory_uid = None
        for uid, unit in friendly_units.items():
            if unit["type"] == 0:  # Factory
                factory_uid = uid
                break
                
        factory_spawn_cell = None
        factory_build_action = None
        if factory_uid and factory_uid in active_uids:
            f_unit = friendly_units[factory_uid]
            build_choice = self.macro_manager.get_build_choice(obs, cartographer, friendly_units, config, should_build_worker)
            if build_choice is not None:
                type_name = {1: "SCOUT", 2: "WORKER", 3: "MINER"}[build_choice]
                # Find the first walkable spawn direction not already reserved
                for d in ["NORTH", "EAST", "WEST", "SOUTH"]:
                    if cartographer.is_walkable(f_unit["col"], f_unit["row"], d):
                        dc, dr = cartographer.DIR_OFFSETS[d]
                        sc, sr = f_unit["col"] + dc, f_unit["row"] + dr
                        if (sc, sr) not in reserved_cells:
                            # Reserve the spawn cell
                            reserved_cells[(sc, sr)] = f"SPAWN_{factory_uid}"
                            factory_build_action = f"BUILD_{type_name}_{d}"
                            factory_spawn_cell = (sc, sr)
                            break

        # 5b. Late-Game Capital Liquidation / Low-Energy Mine Harvesting: Route Factory over friendly mines
        factory_liquidation_target = None
        if factory_uid and factory_uid in active_uids and not factory_build_action:
            if obs.step >= 400 or friendly_units[factory_uid]["energy"] < 600:
                liquidation_targets = self.macro_manager.get_liquidation_targets(
                    obs, cartographer, friendly_units, config
                )
                if liquidation_targets:
                    f_unit = friendly_units[factory_uid]
                    f_pos = (f_unit["col"], f_unit["row"])
                    # Find the nearest reachable liquidation target
                    best_liq = None
                    best_liq_dist = float('inf')
                    for lc, lr, lenergy in liquidation_targets:
                        p = find_path(
                            cartographer, f_pos, (lc, lr),
                            obs.step, obs.southBound, scroll_counter,
                            getattr(config, "factoryMovePeriod", 2), config,
                            initial_jump_cd=f_unit["jump_cd"],
                            blocked_cells=enemy_positions
                        )
                        if p is not None and len(p) < best_liq_dist:
                            best_liq_dist = len(p)
                            best_liq = (lc, lr)
                    if best_liq:
                        factory_liquidation_target = best_liq
                        tactical_targets[factory_uid] = factory_liquidation_target
                        is_seeking_mine = True

        # 5c. Factory Chase Mode: Target the enemy factory for assassination
        if factory_uid and factory_uid in active_uids and factory_uid not in tactical_targets:
            f_unit = friendly_units[factory_uid]
            f_pos = (f_unit["col"], f_unit["row"])
            # Use enemy tracker to get the best estimate of enemy factory position
            ef_col = (self.enemy_tracker.col_min + self.enemy_tracker.col_max) // 2
            ef_row = (self.enemy_tracker.row_min + self.enemy_tracker.row_max) // 2
            if ef_col is not None and ef_row is not None:
                chase_target = (ef_col, ef_row)
                p = find_path(
                    cartographer, f_pos, chase_target,
                    obs.step, obs.southBound, scroll_counter,
                    getattr(config, "factoryMovePeriod", 2), config,
                    initial_jump_cd=f_unit["jump_cd"],
                    safety_buffer=0,
                    blocked_cells=enemy_positions
                )
                if p is not None:
                    tactical_targets[factory_uid] = chase_target
                    is_chasing_enemy = True
                else:
                    # Can't path directly - try to get to the nearest doorway on enemy side
                    # to cross over
                    door_rows = []
                    c1 = cartographer.width // 2 - 1
                    c2 = cartographer.width // 2
                    enemy_side_col = c2 if obs.player == 0 else c1
                    for r in range(obs.southBound, obs.northBound + 1):
                        if (c1, r) in cartographer.global_map or (c2, r) in cartographer.global_map:
                            if not cartographer.is_wall(c1, r, "EAST"):
                                door_rows.append(r)
                    
                    if door_rows:
                        # Find the doorway closest to the enemy factory row
                        best_door = min(door_rows, key=lambda dr: abs(dr - ef_row))
                        # Target the enemy side of the doorway
                        door_target = (enemy_side_col, best_door)
                        p2 = find_path(
                            cartographer, f_pos, door_target,
                            obs.step, obs.southBound, scroll_counter,
                            getattr(config, "factoryMovePeriod", 2), config,
                            initial_jump_cd=f_unit["jump_cd"],
                            safety_buffer=0,
                            blocked_cells=enemy_positions
                        )
                        if p2 is not None:
                            tactical_targets[factory_uid] = door_target
                            is_chasing_enemy = True
                        else:
                            # Try our side of the doorway as intermediate target
                            our_side_col = c1 if obs.player == 0 else c2
                            our_door_target = (our_side_col, best_door)
                            p3 = find_path(
                                cartographer, f_pos, our_door_target,
                                obs.step, obs.southBound, scroll_counter,
                                getattr(config, "factoryMovePeriod", 2), config,
                                initial_jump_cd=f_unit["jump_cd"],
                                safety_buffer=0,
                                blocked_cells=enemy_positions
                            )
                            if p3 is not None:
                                tactical_targets[factory_uid] = our_door_target
                                is_chasing_enemy = True
                            
        # 6. Define priority sorting function for active units
        # Priority: Factory (0) > Workers (2) / Miners (3) > Scouts (1)
        def get_priority(uid):
            rtype = friendly_units[uid]["type"]
            if uid == factory_uid:
                return 0  # Factory must publish its path before escorts act
            elif rtype == 0:
                return 1
            elif rtype in [2, 3]:
                return 2  # Medium priority
            else:
                return 3  # Lowest priority
                
        # Sort active uids by priority
        active_uids.sort(key=get_priority)
        factory_reservations_broadcast = False
        self.factory_reservations = set()
        if factory_uid and factory_uid not in active_uids:
            self._broadcast_factory_reservations(factory_uid, friendly_units, actions)
            factory_reservations_broadcast = True

        # 7. Resolve active units in priority order
        for uid in active_uids:
            if uid != factory_uid and not factory_reservations_broadcast:
                self._broadcast_factory_reservations(factory_uid, friendly_units, actions)
                factory_reservations_broadcast = True

            if uid in tactical_targets:
                if self.unit_targets.get(uid) != tactical_targets[uid]:
                    self.unit_paths[uid] = None
                    self.unit_targets[uid] = tactical_targets[uid]
            unit = friendly_units[uid]
            rtype = unit["type"]
            col = unit["col"]
            row = unit["row"]
            jump_cd = unit["jump_cd"]

            # Determine movement period
            if rtype == 0:
                move_period = getattr(config, "factoryMovePeriod", 2)
            elif rtype == 1:
                move_period = 1
            elif rtype == 2:
                move_period = getattr(config, "workerMovePeriod", 2)
            elif rtype == 3:
                move_period = getattr(config, "minerMovePeriod", 2)
            else:
                move_period = 1
            
            # If this is the Factory and it's spawning, apply the spawn action
            if uid == factory_uid and factory_build_action:
                actions[uid] = factory_build_action
                # Factory stays stationary during spawn, its current cell is already reserved
                continue

            clearing = self._path_clearing_action(
                uid, unit, cartographer, obs, config, reserved_cells, enemy_positions, scroll_counter, move_period
            )
            if clearing:
                clearing_action, clearing_pos = clearing
                actions[uid] = clearing_action
                self.unit_paths[uid] = None
                if clearing_pos != (col, row):
                    if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                        del reserved_cells[(col, row)]
                    reserved_cells[clearing_pos] = uid
                else:
                    reserved_cells[(col, row)] = uid
                continue

            # Death-Row Salvage: any unit flagged for TRANSFER dumps energy immediately
            if uid in worker_trap_actions:
                salvage_action = worker_trap_actions[uid]
                if salvage_action.startswith("TRANSFER_"):
                    actions[uid] = salvage_action
                    continue
                
            # --- Specialized Miner Behavior ---
            if rtype == 3:
                # 1. Standing on mining node -> TRANSFORM (only if not guarding)
                if uid not in tactical_targets:
                    is_node = (col, row) in self.macro_manager.remembered_nodes or f"{col},{row}" in obs.miningNodes
                    if is_node and f"{col},{row}" not in obs.mines:
                        if obs.step < 400 and unit["energy"] >= 100:
                            actions[uid] = "TRANSFORM"
                            # Miner stays stationary, current cell is already reserved
                            continue
                
                # 2. Pathfind to target
                best_path = None
                if uid in tactical_targets:
                    t_cell = tactical_targets[uid]
                    if (col, row) == t_cell:
                        actions[uid] = "IDLE"
                        continue
                    best_path = find_path(
                        cartographer, (col, row), t_cell,
                        obs.step, obs.southBound, scroll_counter,
                        move_period, config,
                        blocked_cells=enemy_positions
                    )
                else:
                    closest_node = None
                    min_dist = float('inf')
                    f_pos = None
                    for fu in friendly_units.values():
                        if fu["type"] == 0:
                            f_pos = (fu["col"], fu["row"])
                            break
                    for node in self.macro_manager.remembered_nodes:
                        if f"{node[0]},{node[1]}" in obs.mines:
                            continue
                        # Only target nodes on our side of the mirror axis
                        our_side = (node[0] < cartographer.width // 2) if obs.player == 0 else (node[0] >= cartographer.width // 2)
                        if not our_side:
                            continue
                        if f_pos and node[1] < f_pos[1] + 3:
                            continue
                        p = find_path(
                            cartographer, (col, row), node,
                            obs.step, obs.southBound, scroll_counter,
                            move_period, config,
                            blocked_cells=enemy_positions
                        )
                        if p is not None:
                            path_len = len(p)
                            arrival_turns = move_period * path_len + 1
                            factory_move_period = getattr(config, "factoryMovePeriod", 2)
                            expected_factory_row = f_pos[1] + (arrival_turns // factory_move_period) if f_pos else 0
                            if f_pos and node[1] < expected_factory_row:
                                continue
                            if path_len < min_dist:
                                min_dist = path_len
                                closest_node = node
                                best_path = p
                        
                if best_path:
                    next_pos = best_path[0]
                    dx = next_pos[0] - col
                    dy = next_pos[1] - row
                    direction = None
                    if (dx, dy) == (0, 1):
                        direction = "NORTH"
                    elif (dx, dy) == (0, -1):
                        direction = "SOUTH"
                    elif (dx, dy) == (1, 0):
                        direction = "EAST"
                    elif (dx, dy) == (-1, 0):
                        direction = "WEST"
                        
                    if direction and cartographer.is_walkable(col, row, direction):
                        if next_pos not in reserved_cells:
                            projected_south = project_south_bound(
                                obs.step, obs.southBound, scroll_counter, move_period, config
                            )
                            if next_pos[1] >= projected_south:
                                actions[uid] = direction
                                self.unit_paths[uid] = best_path[1:]
                                # Vacate old cell, reserve new cell
                                if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                    del reserved_cells[(col, row)]
                                reserved_cells[next_pos] = uid
                                continue
                                
            # --- Specialized Worker Behavior ---
            if rtype == 2:
                if uid in worker_trap_actions:
                    trap_action = worker_trap_actions[uid]
                    if trap_action.startswith("TRANSFER_"):
                        # Death-Row Salvage: dump energy into Factory unconditionally
                        actions[uid] = trap_action
                        continue
                    elif obs.step < 400 and unit["energy"] >= 100:
                        actions[uid] = trap_action
                        continue
                # Check if Factory is blocked
                factory_blocked = False
                factory_unit = None
                for fu in friendly_units.values():
                    if fu["type"] == 0:
                        factory_unit = fu
                        break
                        
                if factory_unit:
                    paths = find_reachable_paths(
                        cartographer, (factory_unit["col"], factory_unit["row"]),
                        obs.step, obs.southBound, scroll_counter,
                        getattr(config, "factoryMovePeriod", 2), config, max_depth=10,
                        initial_jump_cd=factory_unit["jump_cd"],
                        safety_buffer=dynamic_safety_buffer,
                        blocked_cells=enemy_positions
                    )
                    has_forward_path = any(pos[1] > factory_unit["row"] for pos in paths.keys())
                    if not has_forward_path:
                        factory_blocked = True
                        
                if factory_blocked and factory_unit:
                    blocking_info = self.find_blocking_wall(
                        cartographer, (factory_unit["col"], factory_unit["row"]), obs, config
                    )
                    if blocking_info:
                        wall_cell, direction = blocking_info
                        fx, fy = factory_unit["col"], factory_unit["row"]
                        if wall_cell == (fx, fy):
                            dc, dr = cartographer.DIR_OFFSETS[direction]
                            target_cell = (fx + dc, fy + dr)
                            opp_dir = {"NORTH": "SOUTH", "SOUTH": "NORTH", "EAST": "WEST", "WEST": "EAST"}[direction]
                            remove_action = f"REMOVE_{opp_dir}"
                        else:
                            target_cell = wall_cell
                            remove_action = f"REMOVE_{direction}"

                        if (col, row) == target_cell:
                            if obs.step < 400 and unit["energy"] >= 100:
                                actions[uid] = remove_action
                                # Worker stays stationary, current cell is already reserved
                                continue
                        else:
                            p = find_path(
                                cartographer, (col, row), target_cell,
                                obs.step, obs.southBound, scroll_counter,
                                move_period, config,
                                blocked_cells=enemy_positions
                            )
                            if p:
                                next_pos = p[0]
                                dx = next_pos[0] - col
                                dy = next_pos[1] - row
                                dir_to_move = None
                                if (dx, dy) == (0, 1):
                                    dir_to_move = "NORTH"
                                elif (dx, dy) == (0, -1):
                                    dir_to_move = "SOUTH"
                                elif (dx, dy) == (1, 0):
                                    dir_to_move = "EAST"
                                elif (dx, dy) == (-1, 0):
                                    dir_to_move = "WEST"
                                    
                                if dir_to_move and cartographer.is_walkable(col, row, dir_to_move):
                                    if next_pos not in reserved_cells:
                                        projected_south = project_south_bound(
                                            obs.step, obs.southBound, scroll_counter, move_period, config
                                        )
                                        if next_pos[1] >= projected_south:
                                            actions[uid] = dir_to_move
                                            self.unit_paths[uid] = p[1:]
                                            # Vacate old cell, reserve new cell
                                            if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                                del reserved_cells[(col, row)]
                                            reserved_cells[next_pos] = uid
                                            continue
                elif uid in tactical_targets:
                    t_cell = tactical_targets[uid]
                    if (col, row) == t_cell:
                        actions[uid] = "IDLE"
                        continue
                    p = find_path(
                        cartographer, (col, row), t_cell,
                        obs.step, obs.southBound, scroll_counter,
                        move_period, config,
                        blocked_cells=enemy_positions
                    )
                    if p:
                        next_pos = p[0]
                        dx = next_pos[0] - col
                        dy = next_pos[1] - row
                        dir_to_move = None
                        if (dx, dy) == (0, 1):
                            dir_to_move = "NORTH"
                        elif (dx, dy) == (0, -1):
                            dir_to_move = "SOUTH"
                        elif (dx, dy) == (1, 0):
                            dir_to_move = "EAST"
                        elif (dx, dy) == (-1, 0):
                            dir_to_move = "WEST"
                            
                        if dir_to_move and cartographer.is_walkable(col, row, dir_to_move):
                            if next_pos not in reserved_cells:
                                projected_south = project_south_bound(
                                    obs.step, obs.southBound, scroll_counter, move_period, config
                                )
                                if next_pos[1] >= projected_south:
                                    actions[uid] = dir_to_move
                                    self.unit_paths[uid] = p[1:]
                                    # Vacate old cell, reserve new cell
                                    if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                        del reserved_cells[(col, row)]
                                    reserved_cells[next_pos] = uid
                                    continue

            # --- Default Pathfollowing / Searching ---
            path = self.unit_paths.get(uid)
            
            # Validate existing cached path
            if path:
                next_pos = path[0]
                dx = next_pos[0] - col
                dy = next_pos[1] - row
                direction = None
                is_jump = False
                if (dx, dy) == (0, 1):
                    direction = "NORTH"
                elif (dx, dy) == (0, -1):
                    direction = "SOUTH"
                elif (dx, dy) == (1, 0):
                    direction = "EAST"
                elif (dx, dy) == (-1, 0):
                    direction = "WEST"
                elif rtype == 0 and (dx, dy) == (0, 2):
                    direction = "JUMP_NORTH"
                    is_jump = True
                elif rtype == 0 and (dx, dy) == (0, -2):
                    direction = "JUMP_SOUTH"
                    is_jump = True
                elif rtype == 0 and (dx, dy) == (2, 0):
                    direction = "JUMP_EAST"
                    is_jump = True
                elif rtype == 0 and (dx, dy) == (-2, 0):
                    direction = "JUMP_WEST"
                    is_jump = True
                elif (dx, dy) == (0, 0):
                    direction = "IDLE"
                    
                valid_move = False
                if direction:
                    if is_jump or direction == "IDLE":
                        valid_move = True
                    elif cartographer.is_walkable(col, row, direction):
                        valid_move = True
                        
                if valid_move:
                    # Destination cell must not be reserved
                    if next_pos not in reserved_cells or reserved_cells[next_pos] == uid:
                        # Factory collision guard: only avoid collision when enemy has >= our energy
                        if rtype == 0 and next_pos in enemy_positions and enemy_factory_energy >= unit["energy"]:
                            self.unit_paths[uid] = None
                            # Fall through to re-pathing below
                        else:
                            # Factory South safety override (only applies to walking SOUTH)
                            if rtype == 0 and direction == "SOUTH":
                                if not is_seeking_mine and not is_chasing_enemy and jump_cd == 0 and row + 2 <= obs.northBound and (col, row + 2) not in reserved_cells:
                                    direction = "JUMP_NORTH"
                                    next_pos = (col, row + 2)
                                elif not is_seeking_mine and not is_chasing_enemy and next_pos[1] <= obs.southBound + dynamic_safety_buffer:
                                    direction = None
                                    
                            if direction:
                                projected_south = project_south_bound(
                                    obs.step, obs.southBound, scroll_counter, move_period, config
                                )
                                if next_pos[1] >= projected_south:
                                    actions[uid] = direction
                                    self.unit_paths[uid].pop(0)
                                    # Vacate old cell, reserve new cell
                                    if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                        del reserved_cells[(col, row)]
                                    reserved_cells[next_pos] = uid
                                    continue
            # Path is invalid or blocked
            self.unit_paths[uid] = None
            path = None
            
            # Find a new path using A* / BFS
            if not path:
                best_path = None
                best_target = None
                
                if uid in tactical_targets:
                    t_cell = tactical_targets[uid]
                    if (col, row) == t_cell:
                        actions[uid] = "IDLE"
                        # Reserve current cell
                        if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                            pass
                        else:
                            reserved_cells[(col, row)] = uid
                        continue
                    initial_jcd = unit["jump_cd"] if rtype == 0 else None
                    p = find_path(
                        cartographer, (col, row), t_cell,
                        obs.step, obs.southBound, scroll_counter,
                        move_period, config,
                        initial_jump_cd=initial_jcd,
                        safety_buffer=(dynamic_safety_buffer if (rtype == 0 and not is_seeking_mine and not is_chasing_enemy) else 0),
                        blocked_cells=enemy_positions
                    )
                    if p:
                        best_path = p
                        best_target = t_cell
                        
                if not best_path:
                    initial_jcd = unit["jump_cd"] if rtype == 0 else None
                    paths = find_reachable_paths(
                        cartographer, (col, row), 
                        obs.step, obs.southBound, scroll_counter, 
                        move_period, config, max_depth=self.max_depth,
                        initial_jump_cd=initial_jcd,
                        safety_buffer=(dynamic_safety_buffer if (rtype == 0 and not is_seeking_mine and not is_chasing_enemy) else 0),
                        blocked_cells=enemy_positions
                    )
                    
                    # Check for reachable crystals (first step must be unreserved)
                    reachable_crystals = []
                    for key, val in obs.crystals.items():
                        try:
                            cc, cr = map(int, key.split(","))
                            if (cc, cr) in paths and paths[(cc, cr)]:
                                if rtype == 0 and cr <= row:
                                    continue
                                next_step = paths[(cc, cr)][0]
                                if next_step not in reserved_cells:
                                    reachable_crystals.append((cc, cr))
                        except ValueError:
                            pass
                                
                    if reachable_crystals:
                        reachable_crystals.sort(key=lambda pos: len(paths[pos]))
                        best_target = reachable_crystals[0]
                        best_path = paths[best_target]
                    else:
                        # Target the northward cell with maximum row index
                        safe_nodes = []
                        for pos, p in paths.items():
                            if p and p[0] not in reserved_cells:
                                safe_nodes.append(pos)
                                
                        if safe_nodes:
                            max_reachable_row = max(pos[1] for pos in safe_nodes)
                            if max_reachable_row > row:
                                candidates = [pos for pos in safe_nodes if pos[1] == max_reachable_row]
                                best_target = min(candidates, key=lambda pos: abs(pos[0] - col))
                                best_path = paths[best_target]
                            
                if best_path:
                    self.unit_paths[uid] = list(best_path)
                    self.unit_targets[uid] = best_target
                    next_pos = best_path[0]
                    
                    if next_pos in reserved_cells and reserved_cells[next_pos] != uid:
                        direction = None
                    else:
                        dx = next_pos[0] - col
                        dy = next_pos[1] - row
                        direction = None
                        is_jump = False
                        if (dx, dy) == (0, 1):
                            direction = "NORTH"
                        elif (dx, dy) == (0, -1):
                            direction = "SOUTH"
                        elif (dx, dy) == (1, 0):
                            direction = "EAST"
                        elif (dx, dy) == (-1, 0):
                            direction = "WEST"
                        elif rtype == 0 and (dx, dy) == (0, 2):
                            direction = "JUMP_NORTH"
                            is_jump = True
                        elif rtype == 0 and (dx, dy) == (0, -2):
                            direction = "JUMP_SOUTH"
                            is_jump = True
                        elif rtype == 0 and (dx, dy) == (2, 0):
                            direction = "JUMP_EAST"
                            is_jump = True
                        elif rtype == 0 and (dx, dy) == (-2, 0):
                            direction = "JUMP_WEST"
                            is_jump = True
                        elif (dx, dy) == (0, 0):
                            direction = "IDLE"
                            
                        # Factory collision guard: only avoid when enemy has >= our energy
                        if rtype == 0 and next_pos in enemy_positions and enemy_factory_energy >= unit["energy"]:
                            direction = None
                            
                        # Factory South safety override (only applies to walking SOUTH)
                        if rtype == 0 and direction == "SOUTH":
                            if not is_seeking_mine and not is_chasing_enemy and jump_cd == 0 and row + 2 <= obs.northBound and (col, row + 2) not in reserved_cells:
                                direction = "JUMP_NORTH"
                                next_pos = (col, row + 2)
                            elif not is_seeking_mine and not is_chasing_enemy and next_pos[1] <= obs.southBound + dynamic_safety_buffer:
                                direction = None
                                
                        if direction:
                            actions[uid] = direction
                            self.unit_paths[uid].pop(0)
                            # Vacate old cell, reserve new cell
                            if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                del reserved_cells[(col, row)]
                            reserved_cells[next_pos] = uid
                else:
                    # If the Factory has no path, do not pace or jump blindly.
                    # Standing still is safer than burning energy in a coordinate loop.
                    if rtype == 0:
                        actions[uid] = "IDLE"
                        
                        # Handle spawn trap cancellation if this cell was reserved for a spawn
                        if (col, row) in reserved_cells:
                            owner_val = reserved_cells[(col, row)]
                            if isinstance(owner_val, str) and owner_val.startswith("SPAWN_"):
                                spawn_factory_uid = owner_val.split("_")[1]
                                actions[spawn_factory_uid] = "IDLE"
                                del reserved_cells[(col, row)]
                                
                        reserved_cells[(col, row)] = uid
                        continue

                    # Fallback moves if no path is found
                    fallback_action = None
                    if row <= obs.southBound + dynamic_safety_buffer:
                        if not fallback_action:
                            # Find a free adjacent cell
                            for d in ["NORTH", "EAST", "WEST", "SOUTH"]:
                                if cartographer.is_walkable(col, row, d):
                                    dc, dr = cartographer.DIR_OFFSETS[d]
                                    nc, nr = col + dc, row + dr
                                    if (nc, nr) not in reserved_cells:
                                        # Factory South safety override for fallback
                                        if rtype == 0 and d == "SOUTH":
                                            if not is_seeking_mine and not is_chasing_enemy and jump_cd == 0 and row + 2 <= obs.northBound and (col, row + 2) not in reserved_cells:
                                                fallback_action = "JUMP_NORTH"
                                                if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                                    del reserved_cells[(col, row)]
                                                reserved_cells[(col, row + 2)] = uid
                                                break
                                            elif not is_seeking_mine and not is_chasing_enemy and nr <= obs.southBound + dynamic_safety_buffer:
                                                continue
                                                
                                        if d == "SOUTH" and row <= obs.southBound + dynamic_safety_buffer:
                                            continue
                                        fallback_action = d
                                        if (col, row) in reserved_cells and reserved_cells[(col, row)] == uid:
                                            del reserved_cells[(col, row)]
                                        reserved_cells[(nc, nr)] = uid
                                        break
                                    
                    if fallback_action:
                        actions[uid] = fallback_action
                    else:
                        # Forced IDLE: reserve current cell
                        actions[uid] = "IDLE"
                        
                        # Handle spawn trap cancellation if this cell was reserved for a spawn
                        if (col, row) in reserved_cells:
                            owner_val = reserved_cells[(col, row)]
                            if isinstance(owner_val, str) and owner_val.startswith("SPAWN_"):
                                spawn_factory_uid = owner_val.split("_")[1]
                                actions[spawn_factory_uid] = "IDLE"
                                del reserved_cells[(col, row)]
                                
                        reserved_cells[(col, row)] = uid

        if not factory_reservations_broadcast:
            self._broadcast_factory_reservations(factory_uid, friendly_units, actions)

        # Debug Factory movement decisions
        for uid, unit in friendly_units.items():
            if unit["type"] == 0:
                print(f"DEBUG_FACTORY: Step {obs.step} pos: ({unit['col']},{unit['row']}) target: {self.unit_targets.get(uid)} path: {self.unit_paths.get(uid)} jump_cd: {unit['jump_cd']} action: {actions.get(uid)}", flush=True)
            elif unit["type"] == 1:
                print(f"DEBUG_SCOUT: Step {obs.step} uid: {uid[:4]} pos: ({unit['col']},{unit['row']}) energy: {unit['energy']} target: {self.unit_targets.get(uid)} path: {self.unit_paths.get(uid)}", flush=True)
            elif unit["type"] == 2:
                print(f"DEBUG_WORKER: Step {obs.step} uid: {uid[:4]} pos: ({unit['col']},{unit['row']}) energy: {unit['energy']} target: {self.unit_targets.get(uid)} path: {self.unit_paths.get(uid)} action: {actions.get(uid)}", flush=True)
            elif unit["type"] == 3:
                print(f"DEBUG_MINER: Step {obs.step} uid: {uid[:4]} pos: ({unit['col']},{unit['row']}) energy: {unit['energy']} target: {self.unit_targets.get(uid)} path: {self.unit_paths.get(uid)} action: {actions.get(uid)}", flush=True)

        self.last_turn_elapsed = time.time() - start_time
        return actions
