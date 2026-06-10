import heapq

SAFETY_BUFFER_PENALTY = 50

def project_south_bound(current_step, current_south, current_scroll_counter, future_turns, config):
    """
    Predicts the southBound value `future_turns` into the future.
    """
    def get_val(key, default):
        if hasattr(config, key):
            return getattr(config, key)
        if isinstance(config, dict) and key in config:
            return config[key]
        return default
        
    scroll_ramp_steps = get_val("scrollRampSteps", 400)
    scroll_start_interval = get_val("scrollStartInterval", 4)
    scroll_end_interval = get_val("scrollEndInterval", 1)
    
    def get_scroll_interval(step):
        if step >= scroll_ramp_steps:
            return scroll_end_interval
        progress = step / max(1, scroll_ramp_steps)
        interval = scroll_start_interval - (scroll_start_interval - scroll_end_interval) * progress
        return max(scroll_end_interval, round(interval))
        
    south = current_south
    counter = current_scroll_counter
    step = current_step
    
    for _ in range(future_turns):
        counter -= 1
        if counter <= 0:
            south += 1
            counter = get_scroll_interval(step)
        step += 1
        
    return south

def _safety_penalty(row, projected_south, safety_buffer):
    if row < projected_south:
        return None
    if safety_buffer > 0 and row < projected_south + safety_buffer:
        return SAFETY_BUFFER_PENALTY
    return 0

def _previous_distinct_position(start, path, current_pos):
    for pos in reversed([start] + path):
        if pos != current_pos:
            return pos
    return None

def find_reachable_paths(cartographer, start, current_step, current_south, current_scroll_counter, move_period, config, max_depth=20, initial_jump_cd=None, safety_buffer=0, blocked_cells=None):
    """
    Performs a BFS from start to find all reachable cells within max_depth steps.
    It takes scroll-awareness into account, and is jump-aware for the Factory.
    Returns:
        dictionary mapping target cell (col, row) -> path (list of nodes from start to target, excluding start)
    """
    projected_south_cache = {}
    def get_projected_south(turns):
        if turns not in projected_south_cache:
            projected_south_cache[turns] = project_south_bound(
                current_step, current_south, current_scroll_counter, turns, config
            )
        return projected_south_cache[turns]

    if initial_jump_cd is not None:
        queue = [(0, 0, start[0], start[1], [], initial_jump_cd)]
        visited_states = {(start[0], start[1], initial_jump_cd): 0}
    else:
        queue = [(0, 0, start[0], start[1], [])]
        visited_states = {start: 0}
        
    paths = {start: []}
    path_costs = {start: 0}

    heapq.heapify(queue)
    while queue:
        if initial_jump_cd is not None:
            cost, steps, c, r, path, jump_cd = heapq.heappop(queue)
            state_key = (c, r, jump_cd)
        else:
            cost, steps, c, r, path = heapq.heappop(queue)
            jump_cd = None
            state_key = (c, r)

        if cost > visited_states.get(state_key, float('inf')):
            continue

        if len(path) >= max_depth:
            continue

        previous_pos = _previous_distinct_position(start, path, (c, r))
            
        # 1. Standard adjacent walking transitions
        for direction, offset in cartographer.DIR_OFFSETS.items():
            if cartographer.is_walkable(c, r, direction):
                nc, nr = c + offset[0], r + offset[1]
                n_pos = (nc, nr)

                if n_pos == previous_pos:
                    continue
                
                next_steps = steps + 1
                next_turns = next_steps * move_period
                projected_south = get_projected_south(next_turns)
                
                penalty = _safety_penalty(nr, projected_south, safety_buffer)
                if penalty is None or nr > cartographer.north_bound:
                    continue
                    
                if blocked_cells and n_pos in blocked_cells:
                    continue

                next_cost = cost + move_period + penalty
                    
                if initial_jump_cd is not None:
                    next_jump_cd = max(0, jump_cd - move_period)
                    state = (nc, nr, next_jump_cd)
                    if next_cost < visited_states.get(state, float('inf')):
                        visited_states[state] = next_cost
                        next_path = path + [n_pos]
                        if next_cost < path_costs.get(n_pos, float('inf')):
                            paths[n_pos] = next_path
                            path_costs[n_pos] = next_cost
                        heapq.heappush(queue, (next_cost, next_steps, nc, nr, next_path, next_jump_cd))
                else:
                    if next_cost < visited_states.get(n_pos, float('inf')):
                        visited_states[n_pos] = next_cost
                        next_path = path + [n_pos]
                        if next_cost < path_costs.get(n_pos, float('inf')):
                            paths[n_pos] = next_path
                            path_costs[n_pos] = next_cost
                        heapq.heappush(queue, (next_cost, next_steps, nc, nr, next_path))
                        
        # 3. Wait transition (stay in place to cool down jump)
        if initial_jump_cd is not None and jump_cd > 0:
            next_col = c
            next_row = r
            next_steps = steps + 1
            next_turns = next_steps * move_period
            projected_south = get_projected_south(next_turns)
            penalty = _safety_penalty(next_row, projected_south, safety_buffer)
            if penalty is not None:
                next_jump_cd = max(0, jump_cd - move_period)
                state = (next_col, next_row, next_jump_cd)
                next_cost = cost + move_period + penalty
                if next_cost < visited_states.get(state, float('inf')):
                    visited_states[state] = next_cost
                    heapq.heappush(queue, (next_cost, next_steps, next_col, next_row, path + [(next_col, next_row)], next_jump_cd))
                        
        # 2. Jump transitions (ignoring intermediate walls)
        if initial_jump_cd is not None and jump_cd == 0:
            for direction, offset in cartographer.DIR_OFFSETS.items():
                nc, nr = c + offset[0] * 2, r + offset[1] * 2
                n_pos = (nc, nr)
                
                if nc < 0 or nc >= cartographer.width or nr < 0:
                    continue
                    
                next_steps = steps + 1
                next_turns = next_steps * move_period
                projected_south = get_projected_south(next_turns)
                
                penalty = _safety_penalty(nr, projected_south, safety_buffer)
                if penalty is None or nr > cartographer.north_bound:
                    continue
                    
                if blocked_cells and n_pos in blocked_cells:
                    continue
                    
                next_jump_cd = 20
                state = (nc, nr, next_jump_cd)
                next_cost = cost + move_period + penalty
                if next_cost < visited_states.get(state, float('inf')):
                    visited_states[state] = next_cost
                    next_path = path + [n_pos]
                    if next_cost < path_costs.get(n_pos, float('inf')):
                        paths[n_pos] = next_path
                        path_costs[n_pos] = next_cost
                    heapq.heappush(queue, (next_cost, next_steps, nc, nr, next_path, next_jump_cd))
                
    return paths

def find_path(cartographer, start, target, current_step, current_south, current_scroll_counter, move_period, config, initial_jump_cd=None, safety_buffer=0, blocked_cells=None):
    """
    Finds the shortest path from start (col, row) to target (col, row) using A* search.
    The path is scroll-aware and jump-aware.
    """
    if start == target:
        return []
        
    projected_south_cache = {}
    def get_projected_south(turns):
        if turns not in projected_south_cache:
            projected_south_cache[turns] = project_south_bound(
                current_step, current_south, current_scroll_counter, turns, config
            )
        return projected_south_cache[turns]
        
    def heuristic(pos):
        return abs(pos[0] - target[0]) + abs(pos[1] - target[1])
        
    if initial_jump_cd is not None:
        start_h = heuristic(start)
        open_set = [(start_h * move_period, 0, 0, start[0], start[1], [], initial_jump_cd)]
        visited = {(start[0], start[1], initial_jump_cd): 0}
    else:
        start_h = heuristic(start)
        open_set = [(start_h * move_period, 0, 0, start[0], start[1], [])]
        visited = {start: 0}
    
    while open_set:
        if initial_jump_cd is not None:
            f, cost, turns, col, row, path, jump_cd = heapq.heappop(open_set)
        else:
            f, cost, turns, col, row, path = heapq.heappop(open_set)
            jump_cd = None
            
        if (col, row) == target:
            return path
            
        state_key = (col, row, jump_cd) if initial_jump_cd is not None else (col, row)
        if cost > visited.get(state_key, float('inf')):
            continue

        previous_pos = _previous_distinct_position(start, path, (col, row))
            
        # 1. Standard walking moves
        for direction, offset in cartographer.DIR_OFFSETS.items():
            if cartographer.is_walkable(col, row, direction):
                nc, nr = col + offset[0], row + offset[1]
                n_pos = (nc, nr)

                if n_pos == previous_pos:
                    continue
                
                next_turns = turns + move_period
                projected_south = get_projected_south(next_turns)
                
                penalty = _safety_penalty(nr, projected_south, safety_buffer)
                if penalty is None or nr > cartographer.north_bound:
                    continue
                    
                if blocked_cells and n_pos in blocked_cells and n_pos != target:
                    continue

                next_cost = cost + move_period + penalty
                    
                if initial_jump_cd is not None:
                    next_jump_cd = max(0, jump_cd - move_period)
                    visited_key = (nc, nr, next_jump_cd)
                    if next_cost < visited.get(visited_key, float('inf')):
                        visited[visited_key] = next_cost
                        next_f = next_cost + heuristic(n_pos) * move_period
                        heapq.heappush(open_set, (next_f, next_cost, next_turns, nc, nr, path + [n_pos], next_jump_cd))
                else:
                    visited_key = n_pos
                    if next_cost < visited.get(visited_key, float('inf')):
                        visited[visited_key] = next_cost
                        next_f = next_cost + heuristic(n_pos) * move_period
                        heapq.heappush(open_set, (next_f, next_cost, next_turns, nc, nr, path + [n_pos]))
                         
        # 2. Jump moves (only for jump-capable pathfinding when cooldown is 0)
        if initial_jump_cd is not None and jump_cd == 0:
            for direction, offset in cartographer.DIR_OFFSETS.items():
                nc, nr = col + offset[0] * 2, row + offset[1] * 2
                n_pos = (nc, nr)
                
                if nc < 0 or nc >= cartographer.width or nr < 0:
                    continue
                    
                next_turns = turns + move_period
                projected_south = get_projected_south(next_turns)
                
                penalty = _safety_penalty(nr, projected_south, safety_buffer)
                if penalty is None or nr > cartographer.north_bound:
                    continue
                    
                if blocked_cells and n_pos in blocked_cells and n_pos != target:
                    continue
                    
                next_jump_cd = 20
                visited_key = (nc, nr, next_jump_cd)
                next_cost = cost + move_period + penalty
                if next_cost < visited.get(visited_key, float('inf')):
                    visited[visited_key] = next_cost
                    next_f = next_cost + heuristic(n_pos) * move_period
                    heapq.heappush(open_set, (next_f, next_cost, next_turns, nc, nr, path + [n_pos], next_jump_cd))
                    
        # 3. Wait transition (stay in place to cool down jump)
        if initial_jump_cd is not None and jump_cd > 0:
            next_col = col
            next_row = row
            next_turns = turns + move_period
            projected_south = get_projected_south(next_turns)
            penalty = _safety_penalty(next_row, projected_south, safety_buffer)
            if penalty is not None:
                next_jump_cd = max(0, jump_cd - move_period)
                visited_key = (next_col, next_row, next_jump_cd)
                next_cost = cost + move_period + penalty
                if next_cost < visited.get(visited_key, float('inf')):
                    visited[visited_key] = next_cost
                    next_f = next_cost + heuristic((next_col, next_row)) * move_period
                    heapq.heappush(open_set, (next_f, next_cost, next_turns, next_col, next_row, path + [(next_col, next_row)], next_jump_cd))
                    
    return None
