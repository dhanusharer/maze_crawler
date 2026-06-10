import sys
from kaggle_environments import make
from cartographer import Cartographer
from orchestrator import TrafficController

# Persistent agent state
player_cartographers = {}
controllers = {}
previous_robots = {}
previous_actions = {}
friendly_fire_casualties = {0: 0, 1: 0}
build_actions_after_400 = {0: 0, 1: 0}

def tactical_agent(obs, config):
    global build_actions_after_400, previous_actions
    player = obs.player
    if player not in player_cartographers:
        player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        controllers[player] = TrafficController(enable_tactics=True)
        previous_robots[player] = {}
        previous_actions[player] = {}
        
    return run_agent_turn(obs, config, player)

def baseline_agent(obs, config):
    global build_actions_after_400, previous_actions
    player = obs.player
    if player not in player_cartographers:
        player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        controllers[player] = TrafficController(enable_tactics=False)
        previous_robots[player] = {}
        previous_actions[player] = {}
        
    return run_agent_turn(obs, config, player)

def run_agent_turn(obs, config, player):
    cartographer = player_cartographers[player]
    controller = controllers[player]
    cartographer.update(obs)
    
    # Check for friendly fire casualties
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
            
        for p_uid, (p_col, p_row, p_type) in prev.items():
            if p_uid not in current_uids:
                if p_row < obs.southBound:
                    continue  # scroll swallowed
                target_cell = prev_targets.get(p_uid, (p_col, p_row))
                
                collision = False
                for other_uid, other_target in prev_targets.items():
                    if other_uid != p_uid and other_target == target_cell:
                        collision = True
                        break
                if collision:
                    friendly_fire_casualties[player] += 1
                    tname = ["Factory", "Scout", "Worker", "Miner"][p_type]
                    print(f"!!! FRIENDLY FIRE CASUALTY: {tname} {p_uid[:4]} (P{player}) destroyed at {target_cell} step {obs.step} !!!", flush=True)
                    
    previous_robots[player] = current_friendly
    
    # Process turn
    actions = controller.process_turn(obs, cartographer, config)
    previous_actions[player] = actions.copy()
    
    # Audit for Phase 4 constraints:
    if obs.step >= 400:
        for uid, action in actions.items():
            if "BUILD" in action or "REMOVE" in action or "BUILD_DIR" in action or "REMOVE_DIR" in action:
                build_actions_after_400[player] += 1
                print(f"!!! AUDIT FAILURE (P{player}): Action {action} at step {obs.step} >= 400 !!!", flush=True)
                
    # Print status every step for both
    # Only print details for Factory
    factory_uid = None
    factory_pos = (0, 0)
    factory_energy = 0
    for uid, data in obs.robots.items():
        if data[4] == player and data[0] == 0:
            factory_uid = uid
            factory_pos = (data[1], data[2])
            factory_energy = data[3]
            break
            
    scouts = sum(1 for _, _, t in current_friendly.values() if t == 1)
    workers = sum(1 for _, _, t in current_friendly.values() if t == 2)
    miners = sum(1 for _, _, t in current_friendly.values() if t == 3)
    
    pname = "Tactical (P0)" if player == 0 else "Baseline (P1)"
    print(f"[Step {obs.step:03d} | {pname}] Factory: {factory_pos} | E: {factory_energy} | Scouts: {scouts} | Workers: {workers} | Miners: {miners} | Action: {actions.get(factory_uid, 'IDLE')}", flush=True)
        
    return actions

def run_assassination_test(seed):
    friendly_fire_casualties[0] = 0
    friendly_fire_casualties[1] = 0
    build_actions_after_400[0] = 0
    build_actions_after_400[1] = 0
    player_cartographers.clear()
    controllers.clear()
    previous_robots.clear()
    previous_actions.clear()
    
    print(f"\nRunning Phase 5.1 Assassination Test (Seed {seed})...", flush=True)
    env = make("crawl", configuration={"randomSeed": seed}, debug=True)
    env.run([tactical_agent, baseline_agent])
    
    # Get final rewards and status
    state = env.state
    p0_reward = state[0].reward
    p0_status = state[0].status
    p1_reward = state[1].reward
    p1_status = state[1].status
    steps = env.steps[-1][0].observation.step
    
    print("\n" + "="*50, flush=True)
    print(f"Simulation Finished at Step: {steps}", flush=True)
    print(f"Player 0 (Tactical) Reward: {p0_reward} | Status: {p0_status}", flush=True)
    print(f"Player 1 (Baseline) Reward: {p1_reward} | Status: {p1_status}", flush=True)
    print(f"P0 Friendly Fire Casualties: {friendly_fire_casualties[0]}", flush=True)
    print(f"P1 Friendly Fire Casualties: {friendly_fire_casualties[1]}", flush=True)
    print(f"Post-Step 400 Actions Violations - P0: {build_actions_after_400[0]} | P1: {build_actions_after_400[1]}", flush=True)
    print("="*50, flush=True)
    
    # Success condition:
    # 1. P0 (Tactical) is not eliminated (reward >= 0)
    # 2. P1 (Baseline) is ELIMINATED (reward < 0)
    # 3. P0 has 0 friendly fire casualties
    # 4. P0 has 0 post-400 violations
    success = (p0_reward >= 0 and 
               p1_reward < 0 and 
               friendly_fire_casualties[0] == 0 and 
               build_actions_after_400[0] == 0)
               
    if success:
        print("SUCCESS: Phase 5.1 Tactical Agent successfully eliminated the baseline!", flush=True)
        return True
    else:
        print("FAILURE: Tactical Agent failed to assassinate the baseline.", flush=True)
        return False

if __name__ == "__main__":
    res = run_assassination_test(505)
    sys.exit(0 if res else 1)
