import sys
from kaggle_environments import make
from cartographer import Cartographer
from orchestrator import TrafficController

# Persistent agent state
player_cartographers = {}
controllers = {}
previous_robots = {}  # player -> {uid: (col, row, type)}
previous_actions = {}  # player -> {uid: action}
friendly_fire_casualties = {0: 0, 1: 0}

def orchestrated_agent(obs, config):
    player = obs.player
    if player not in player_cartographers:
        player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        controllers[player] = TrafficController()
        previous_robots[player] = {}
        previous_actions[player] = {}
        
    cartographer = player_cartographers[player]
    controller = controllers[player]
    cartographer.update(obs)
    
    # Check for friendly fire casualties from the previous turn transition
    current_uids = set()
    current_friendly = {}
    for uid, data in obs.robots.items():
        rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
        if owner == player:
            current_uids.add(uid)
            current_friendly[uid] = (col, row, rtype)
            
    prev = previous_robots[player]
    prev_act = previous_actions[player]
    if prev:
        prev_targets = {}
        for p_uid, (p_col, p_row, p_type) in prev.items():
            act = prev_act.get(p_uid, "IDLE")
            t_col, t_row = p_col, p_row
            if act in ["NORTH", "SOUTH", "EAST", "WEST"]:
                dc, dr = cartographer.DIR_OFFSETS[act]
                t_col, t_row = p_col + dc, p_row + dr
            elif act.startswith("JUMP_"):
                d = act.split("_")[1]
                dc, dr = cartographer.DIR_OFFSETS[d]
                t_col, t_row = p_col + dc * 2, p_row + dr * 2
            prev_targets[p_uid] = (t_col, t_row)
            
        # Check which previous robots are missing
        for p_uid, (p_col, p_row, p_type) in prev.items():
            if p_uid not in current_uids:
                # Check if it was destroyed by scrolling or combat
                # Boundary destruction happens in Phase 9 of crawl.py, so if its row is >= obs.southBound, it was combat!
                if p_row >= obs.southBound:
                    target_cell = prev_targets.get(p_uid, (p_col, p_row))
                    collision = False
                    for other_uid, other_target in prev_targets.items():
                        if other_uid != p_uid and other_target == target_cell:
                            collision = True
                            break
                    if collision:
                        friendly_fire_casualties[player] += 1
                        tname = ["Factory", "Scout", "Worker", "Miner"][p_type]
                        print(f"!!! FRIENDLY FIRE CASUALTY: {tname} {p_uid[:4]} was destroyed at {target_cell} step {obs.step} !!!", flush=True)
                    
    # Update previous robots for next turn
    previous_robots[player] = current_friendly
    
    # Process turn with the TrafficController
    actions = controller.process_turn(obs, cartographer, config)
    previous_actions[player] = actions.copy()
    
    # Print status log for Factory
    factory_uid = None
    for uid, data in obs.robots.items():
        rtype, col, row, owner = data[0], data[1], data[2], data[4]
        if owner == player and rtype == 0:
            factory_uid = uid
            print(f"[Step {obs.step:03d}] Factory at ({col},{row}) | Tiles Mapped: {cartographer.get_mapped_count()} | Active Scouts: {len(current_friendly) - 1} | Action: {actions.get(uid, 'IDLE')}", flush=True)
            break
            
    return actions

def run_stress_test(seed, test_name):
    print("\n" + "="*50, flush=True)
    print(f"Starting Stress Test: {test_name} (Seed {seed})", flush=True)
    print("="*50, flush=True)
    
    # Reset persistent states for a clean run
    player_cartographers.clear()
    controllers.clear()
    previous_robots.clear()
    previous_actions.clear()
    friendly_fire_casualties[0] = 0
    friendly_fire_casualties[1] = 0
    
    env = make("crawl", configuration={"randomSeed": seed}, debug=True)
    env.run([orchestrated_agent, "random"])
    
    state = env.state
    p0_status = state[0].status
    p0_reward = state[0].reward
    casualties = friendly_fire_casualties[0]
    
    print("-"*50, flush=True)
    print(f"Test Result: {test_name}", flush=True)
    print(f"Steps Completed: {obs_step_reached(env)}")
    print(f"Friendly Fire Casualties: {casualties}")
    print(f"Final Reward (Total Energy): {p0_reward}")
    print(f"Player 0 Status: {p0_status}")
    
    # Success evaluation
    success = (casualties == 0 and p0_status == "DONE")
    if success:
        print(f"SUCCESS: {test_name} passed successfully with ZERO friendly fire casualties!", flush=True)
    else:
        print(f"FAILURE: {test_name} failed. Casualties: {casualties}, Status: {p0_status}", flush=True)
    return success

def obs_step_reached(env):
    if env.steps:
        return env.steps[-1][0].observation.step
    return 0

if __name__ == "__main__":
    print("Initializing Phase 3 Orchestration Tests...", flush=True)
    
    # Run Swarm Test (Seed 303)
    # The swarm test forces high scout production. Factory builds scout every 10 turns.
    swarm_success = run_stress_test(303, "Swarm Test")
    
    # Run Choke-Point Test (Seed 404)
    # Testing coordinate booking inside narrow channels
    choke_success = run_stress_test(404, "Choke-Point Test")
    
    print("\n" + "="*50, flush=True)
    if swarm_success and choke_success:
        print("ALL ORCHESTRATION TESTS PASSED SUCCESSFULLY!", flush=True)
        sys.exit(0)
    else:
        print("SOME ORCHESTRATION TESTS FAILED.", flush=True)
        sys.exit(1)
