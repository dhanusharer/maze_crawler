import heapq

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

def find_reachable_paths(cartographer, start, current_step, current_south, current_scroll_counter, move_period, config, max_depth=20, initial_jump_cd=None):
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
        queue = [(start[0], start[1], [], initial_jump_cd)]
        visited_states = {(start[0], start[1], initial_jump_cd)}
    else:
        queue = [(start[0], start[1], [])]
        visited_states = {start}
        
    paths = {start: []}
    
    head = 0
    while head < len(queue):
        if initial_jump_cd is not None:
            c, r, path, jump_cd = queue[head]
        else:
            c, r, path = queue[head]
        head += 1
        
        g = len(path) * move_period
        if len(path) >= max_depth:
            continue
            
        # 1. Standard adjacent walking transitions
        for direction, offset in cartographer.DIR_OFFSETS.items():
            if cartographer.is_walkable(c, r, direction):
                nc, nr = c + offset[0], r + offset[1]
                n_pos = (nc, nr)
                
                next_g = g + move_period
                projected_south = get_projected_south(next_g)
                
                if nr < projected_south or nr > cartographer.north_bound:
                    continue
                    
                if initial_jump_cd is not None:
                    next_jump_cd = max(0, jump_cd - move_period)
                    state = (nc, nr, next_jump_cd)
                    if state not in visited_states:
                        visited_states.add(state)
                        next_path = path + [n_pos]
                        if n_pos not in paths:
                            paths[n_pos] = next_path
                        queue.append((nc, nr, next_path, next_jump_cd))
                else:
                    if n_pos not in visited_states:
                        visited_states.add(n_pos)
                        next_path = path + [n_pos]
                        paths[n_pos] = next_path
                        queue.append((nc, nr, next_path))
                        
        # 3. Wait transition (stay in place to cool down jump)
        if initial_jump_cd is not None and jump_cd > 0:
            next_g = g + move_period
            projected_south = get_projected_south(next_g)
            if r >= projected_south:
                next_jump_cd = max(0, jump_cd - move_period)
                state = (c, r, next_jump_cd)
                if state not in visited_states:
                    visited_states.add(state)
                    queue.append((c, r, path + [(c, r)], next_jump_cd))
                        
        # 2. Jump transitions (ignoring intermediate walls)
        if initial_jump_cd is not None and jump_cd == 0:
            for direction, offset in cartographer.DIR_OFFSETS.items():
                nc, nr = c + offset[0] * 2, r + offset[1] * 2
                n_pos = (nc, nr)
                
                if nc < 0 or nc >= cartographer.width or nr < 0:
                    continue
                    
                next_g = g + move_period
                projected_south = get_projected_south(next_g)
                
                if nr < projected_south or nr > cartographer.north_bound:
                    continue
                    
                next_jump_cd = 20
                state = (nc, nr, next_jump_cd)
                if state not in visited_states:
                    visited_states.add(state)
                    next_path = path + [n_pos]
                    if n_pos not in paths:
                        paths[n_pos] = next_path
                    queue.append((nc, nr, next_path, next_jump_cd))
                
    return paths

def find_path(cartographer, start, target, current_step, current_south, current_scroll_counter, move_period, config, initial_jump_cd=None):
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
        open_set = [(start_h * move_period, 0, start[0], start[1], [], initial_jump_cd)]
        visited = {(start[0], start[1], initial_jump_cd): 0}
    else:
        start_h = heuristic(start)
        open_set = [(start_h * move_period, 0, start[0], start[1], [])]
        visited = {start: 0}
    
    while open_set:
        if initial_jump_cd is not None:
            f, g, col, row, path, jump_cd = heapq.heappop(open_set)
        else:
            f, g, col, row, path = heapq.heappop(open_set)
            jump_cd = None
            
        if (col, row) == target:
            return path
            
        state_key = (col, row, jump_cd) if initial_jump_cd is not None else (col, row)
        if g > visited.get(state_key, float('inf')):
            continue
            
        # 1. Standard walking moves
        for direction, offset in cartographer.DIR_OFFSETS.items():
            if cartographer.is_walkable(col, row, direction):
                nc, nr = col + offset[0], row + offset[1]
                n_pos = (nc, nr)
                
                next_g = g + move_period
                projected_south = get_projected_south(next_g)
                
                if nr < projected_south or nr > cartographer.north_bound:
                    continue
                    
                if initial_jump_cd is not None:
                    next_jump_cd = max(0, jump_cd - move_period)
                    visited_key = (nc, nr, next_jump_cd)
                    if next_g < visited.get(visited_key, float('inf')):
                        visited[visited_key] = next_g
                        next_f = next_g + heuristic(n_pos) * move_period
                        heapq.heappush(open_set, (next_f, next_g, nc, nr, path + [n_pos], next_jump_cd))
                else:
                    visited_key = n_pos
                    if next_g < visited.get(visited_key, float('inf')):
                        visited[visited_key] = next_g
                        next_f = next_g + heuristic(n_pos) * move_period
                        heapq.heappush(open_set, (next_f, next_g, nc, nr, path + [n_pos]))
                        
        # 2. Jump moves (only for jump-capable pathfinding when cooldown is 0)
        if initial_jump_cd is not None and jump_cd == 0:
            for direction, offset in cartographer.DIR_OFFSETS.items():
                nc, nr = col + offset[0] * 2, row + offset[1] * 2
                n_pos = (nc, nr)
                
                if nc < 0 or nc >= cartographer.width or nr < 0:
                    continue
                    
                next_g = g + move_period
                projected_south = get_projected_south(next_g)
                
                if nr < projected_south or nr > cartographer.north_bound:
                    continue
                    
                next_jump_cd = 20
                visited_key = (nc, nr, next_jump_cd)
                if next_g < visited.get(visited_key, float('inf')):
                    visited[visited_key] = next_g
                    next_f = next_g + heuristic(n_pos) * move_period
                    heapq.heappush(open_set, (next_f, next_g, nc, nr, path + [n_pos], next_jump_cd))
                    
        # 3. Wait transition (stay in place to cool down jump)
        if initial_jump_cd is not None and jump_cd > 0:
            next_g = g + move_period
            projected_south = get_projected_south(next_g)
            if row >= projected_south:
                next_jump_cd = max(0, jump_cd - move_period)
                visited_key = (col, row, next_jump_cd)
                if next_g < visited.get(visited_key, float('inf')):
                    visited[visited_key] = next_g
                    next_f = next_g + heuristic((col, row)) * move_period
                    heapq.heappush(open_set, (next_f, next_g, col, row, path + [(col, row)], next_jump_cd))
                    
    return None
