import sys
from cartographer import Cartographer
from pathfinder import find_path, find_reachable_paths

# Setup a clean config object
class MockConfig:
    width = 20
    height = 20
    scrollRampSteps = 40000
    scrollStartInterval = 10000
    scrollEndInterval = 10000

config = MockConfig()

def test_jump_pathfinding():
    print("Running test_jump_pathfinding...", flush=True)
    cartographer = Cartographer(width=20, height=20)
    cartographer.south_bound = 0
    cartographer.north_bound = 19
    
    # Fill map with open space (no walls)
    for c in range(20):
        for r in range(20):
            cartographer.global_map[(c, r)] = 0  # no walls
            
    # Now place a wall between row 2 and row 3.
    # A wall is a bitfield.
    # For (c, 2), add WALL_N (1)
    # For (c, 3), add WALL_S (4)
    # This creates a solid horizontal wall along the entire row.
    for c in range(20):
        cartographer.global_map[(c, 2)] = Cartographer.WALL_N
        cartographer.global_map[(c, 3)] = Cartographer.WALL_S
        
    # Box in (5, 2) specifically to prevent walking east, west, or south
    cartographer.global_map[(5, 2)] = Cartographer.WALL_N | Cartographer.WALL_E | Cartographer.WALL_W | Cartographer.WALL_S
    cartographer.global_map[(4, 2)] = Cartographer.WALL_E
    cartographer.global_map[(6, 2)] = Cartographer.WALL_W
    cartographer.global_map[(5, 1)] = Cartographer.WALL_N
        
    start = (5, 2)
    target = (5, 4)
    
    # 1. Without jump capability, finding path should return None (since target is blocked by wall)
    path_no_jump = find_path(cartographer, start, target, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, initial_jump_cd=None)
    print(f"Path without jump capability: {path_no_jump}", flush=True)
    assert path_no_jump is None, "Path should be None without jump capability"
    
    # 2. With jump capability (jump_cd=0), it should find a path using a jump!
    path_with_jump = find_path(cartographer, start, target, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, initial_jump_cd=0)
    print(f"Path with jump capability: {path_with_jump}", flush=True)
    assert path_with_jump == [(5, 4)], f"Expected path [(5, 4)], got {path_with_jump}"
    
    # 3. With jump cooldown not ready (jump_cd=20), finding path should return None
    path_cooldown_not_ready = find_path(cartographer, start, target, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, initial_jump_cd=20)
    print(f"Path with jump cooldown not ready: {path_cooldown_not_ready}", flush=True)
    assert path_cooldown_not_ready is None, "Path should be None when jump cooldown is active and there's no detour"

    # 4. Detour test: unbox start cell, and open one cell on the far right (c=19) to allow walking detour
    cartographer.global_map[(5, 2)] = Cartographer.WALL_N
    cartographer.global_map[(4, 2)] = 0
    cartographer.global_map[(6, 2)] = 0
    cartographer.global_map[(5, 1)] = 0
    cartographer.global_map[(19, 2)] = 0
    cartographer.global_map[(19, 3)] = 0
    
    # Now search with jump cooldown active (initial_jump_cd=20).
    # Pathfinder should find the long walking detour on the right.
    path_detour = find_path(cartographer, start, target, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, initial_jump_cd=20)
    print(f"Detour path found (length {len(path_detour)}): {path_detour[:3]} ... {path_detour[-3:]}", flush=True)
    assert path_detour is not None, "A detour path should be found"
    
    # 5. Search with jump ready (initial_jump_cd=0).
    # Pathfinder should choose the jump directly over the wall because it's much shorter!
    path_jump_preferred = find_path(cartographer, start, target, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, initial_jump_cd=0)
    print(f"Preferred path with jump: {path_jump_preferred}", flush=True)
    assert path_jump_preferred == [(5, 4)], f"Expected direct jump [(5, 4)], got {path_jump_preferred}"

    # 6. Test find_reachable_paths jump capability
    reachable_no_jump = find_reachable_paths(cartographer, start, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, max_depth=5, initial_jump_cd=None)
    assert (5, 4) not in reachable_no_jump, "Target should not be reachable without jump"
    
    reachable_with_jump = find_reachable_paths(cartographer, start, current_step=0, current_south=0, current_scroll_counter=4, move_period=2, config=config, max_depth=5, initial_jump_cd=0)
    assert (5, 4) in reachable_with_jump, "Target should be reachable with jump"

    print("ALL TESTS PASSED SUCCESSFULLY!", flush=True)

if __name__ == "__main__":
    test_jump_pathfinding()
