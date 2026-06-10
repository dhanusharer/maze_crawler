import sys
from kaggle_environments import make
from cartographer import Cartographer
from pathfinder import find_reachable_paths, project_south_bound

# Persistent state
player_cartographers = {}
unit_paths = {}  # uid -> list of (col, row)
unit_targets = {}  # uid -> (col, row)

def pathfinder_agent(obs, config):
    player = obs.player
    if player not in player_cartographers:
        player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        
    cartographer = player_cartographers[player]
    cartographer.update(obs)
    
    # Calculate scroll state
    scroll_counter = getattr(obs, "scrollCounter", 4)
    
    actions = {}
    
    # Identify friendly units
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
            
    # Process actions for each friendly unit
    for uid, unit in friendly_units.items():
        rtype = unit["type"]
        col = unit["col"]
        row = unit["row"]
        move_cd = unit["move_cd"]
        jump_cd = unit["jump_cd"]
        build_cd = unit["build_cd"]
        
        # Factory build logic
        if rtype == 0:  # Factory
            if unit["energy"] > 150 and build_cd == 0:
                # Spawn a Scout if walkable
                for d in ["NORTH", "EAST", "WEST", "SOUTH"]:
                    if cartographer.is_walkable(col, row, d):
                        actions[uid] = f"BUILD_SCOUT_{d}"
                        break
                if uid in actions:
                    continue
                    
        # Movement logic
        if move_cd > 0:
            continue
            
        move_period = config.factoryMovePeriod if rtype == 0 else 1
        
        # Get path for this unit
        path = unit_paths.get(uid)
        
        # Validate existing path
        if path:
            next_pos = path[0]
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
                projected_south = project_south_bound(
                    obs.step, obs.southBound, scroll_counter, move_period, config
                )
                if next_pos[1] >= projected_south:
                    actions[uid] = direction
                    unit_paths[uid].pop(0)
                    continue
            # Path is invalid or blocked
            unit_paths[uid] = None
            path = None
            
        # If no active path, run BFS to find all reachable paths
        if not path:
            paths = find_reachable_paths(
                cartographer, (col, row), 
                obs.step, obs.southBound, scroll_counter, 
                move_period, config, max_depth=15
            )
            
            best_path = None
            best_target = None
            
            # Find reachable crystals
            reachable_crystals = []
            for key, val in obs.crystals.items():
                cc, cr = int(key.split(",")[0]), int(key.split(",")[1])
                if (cc, cr) in paths and paths[(cc, cr)]:
                    reachable_crystals.append((cc, cr))
                    
            if reachable_crystals:
                # Sort by path length (closest first)
                reachable_crystals.sort(key=lambda pos: len(paths[pos]))
                best_target = reachable_crystals[0]
                best_path = paths[best_target]
            else:
                # Target the reachable cell with the maximum row index to keep moving forward
                if paths:
                    max_reachable_row = max(pos[1] for pos in paths.keys())
                    if max_reachable_row > row:
                        candidates = [pos for pos in paths.keys() if pos[1] == max_reachable_row]
                        best_target = min(candidates, key=lambda pos: abs(pos[0] - col))
                        best_path = paths[best_target]
                    
            if best_path:
                unit_paths[uid] = list(best_path)
                unit_targets[uid] = best_target
                next_pos = best_path[0]
                dx = next_pos[0] - col
                dy = next_pos[1] - row
                if (dx, dy) == (0, 1):
                    actions[uid] = "NORTH"
                elif (dx, dy) == (0, -1):
                    actions[uid] = "SOUTH"
                elif (dx, dy) == (1, 0):
                    actions[uid] = "EAST"
                elif (dx, dy) == (-1, 0):
                    actions[uid] = "WEST"
                if uid in actions:
                    unit_paths[uid].pop(0)
            else:
                # Fallback moves if no path is found
                if rtype == 0:  # Factory jump fallback
                    if jump_cd == 0 and row + 2 <= obs.northBound:
                        actions[uid] = "JUMP_NORTH"
                    elif cartographer.is_walkable(col, row, "NORTH"):
                        actions[uid] = "NORTH"
                else:
                    # Scout random walk fallback
                    for d in ["NORTH", "EAST", "WEST", "SOUTH"]:
                        if cartographer.is_walkable(col, row, d):
                            if d == "SOUTH" and row <= obs.southBound + 2:
                                continue
                            actions[uid] = d
                            break
                            
        # Print status log for factory to confirm smooth navigation
        if rtype == 0:
            print(f"[Step {obs.step:03d}] Factory at ({col},{row}) | Tiles Mapped: {cartographer.get_mapped_count()} | Target: {unit_targets.get(uid)} | Action: {actions.get(uid, 'IDLE')}", flush=True)
            
    return actions

if __name__ == "__main__":
    print("Initializing environment for pathfinding test...", flush=True)
    env = make("crawl", configuration={"randomSeed": 202}, debug=True)
    
    print("Running match...", flush=True)
    env.run([pathfinder_agent, "random"])
    
    print("Match finished!", flush=True)
    state = env.state
    print(f"Player 0 status: {state[0].status}, reward: {state[0].reward}", flush=True)
    print(f"Player 1 status: {state[1].status}, reward: {state[1].reward}", flush=True)
