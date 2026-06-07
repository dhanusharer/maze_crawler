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
build_actions_after_400 = 0

def economy_agent(obs, config):
    global build_actions_after_400, previous_actions
    player = obs.player
    if player not in player_cartographers:
        player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        controllers[player] = TrafficController()
        previous_robots[player] = {}
        previous_actions[player] = {}
        
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
        # Predict target cells for previous step to detect true friendly fire collisions
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
                    continue  # destroyed by scrolls
                target_cell = prev_targets.get(p_uid, (p_col, p_row))
                
                # If this cell was also targeted by another friendly robot, it's friendly fire!
                collision = False
                for other_uid, other_target in prev_targets.items():
                    if other_uid != p_uid and other_target == target_cell:
                        collision = True
                        break
                if collision:
                    friendly_fire_casualties[player] += 1
                    tname = ["Factory", "Scout", "Worker", "Miner"][p_type]
                    print(f"!!! FRIENDLY FIRE CASUALTY: {tname} {p_uid[:4]} was destroyed by friendly collision at {target_cell} at step {obs.step} !!!", flush=True)
                    
    previous_robots[player] = current_friendly
    
    # Process turn
    actions = controller.process_turn(obs, cartographer, config)
    previous_actions[player] = actions.copy()
    
    # Audit for Phase 4 constraints:
    # 1. Step 400 Financial Freeze check
    if obs.step >= 400:
        for uid, action in actions.items():
            if "BUILD" in action or "REMOVE" in action or "BUILD_DIR" in action or "REMOVE_DIR" in action:
                build_actions_after_400 += 1
                print(f"!!! AUDIT FAILURE: Action {action} issued by {uid[:4]} at step {obs.step} >= 400 !!!", flush=True)
                
    # Print progress every turn for player 0
    if player == 0:
        # Count our active units
        scouts = sum(1 for _, _, t in current_friendly.values() if t == 1)
        workers = sum(1 for _, _, t in current_friendly.values() if t == 2)
        miners = sum(1 for _, _, t in current_friendly.values() if t == 3)
        factory_uid = None
        factory_pos = (0, 0)
        factory_energy = 0
        for uid, data in obs.robots.items():
            if data[4] == player and data[0] == 0:
                factory_uid = uid
                factory_pos = (data[1], data[2])
                factory_energy = data[3]
                break
        print(f"[Step {obs.step:03d}] Factory at {factory_pos} | Energy: {factory_energy} | SouthBound: {obs.southBound} | Scouts: {scouts} | Workers: {workers} | Miners: {miners} | Remembered Nodes: {len(controller.macro_manager.remembered_nodes)} | Action: {actions.get(factory_uid, 'IDLE')}", flush=True)
        
    return actions

def run_test(seed, opponent="random"):
    global build_actions_after_400
    build_actions_after_400 = 0
    friendly_fire_casualties[0] = 0
    friendly_fire_casualties[1] = 0
    player_cartographers.clear()
    controllers.clear()
    previous_robots.clear()
    
    opp_name = "Self-Play" if opponent == economy_agent else f"opponent '{opponent}'"
    print(f"\nRunning Phase 4 CFO Test (Seed {seed}) vs {opp_name}...", flush=True)
    env = make("crawl", configuration={"randomSeed": seed}, debug=True)
    env.run([economy_agent, opponent])
    
    # Get final rewards and status
    state = env.state
    p0_reward = state[0].reward
    p0_status = state[0].status
    steps = env.steps[-1][0].observation.step
    
    print("\n" + "="*50, flush=True)
    print(f"Simulation Finished at Step: {steps}", flush=True)
    print(f"Final Total Energy (Reward) - P0: {p0_reward} | P1: {state[1].reward}", flush=True)
    print(f"Player 0 Status: {p0_status} | Player 1 Status: {state[1].status}", flush=True)
    print(f"Friendly Fire Casualties - P0: {friendly_fire_casualties[0]} | P1: {friendly_fire_casualties[1]}", flush=True)
    print(f"Post-Step 400 Actions Violations: {build_actions_after_400}", flush=True)
    print("="*50, flush=True)
    
    success = (friendly_fire_casualties[0] == 0 and 
               friendly_fire_casualties[1] == 0 and 
               build_actions_after_400 == 0 and 
               p0_status == "DONE")
               
    if success:
        print(f"SUCCESS: Phase 4 Financial CFO Test Passed vs {opp_name}!", flush=True)
        return True
    else:
        print(f"FAILURE: Phase 4 constraints or survival failed vs {opp_name}.", flush=True)
        return False

if __name__ == "__main__":
    # Seed 505: The Gold Rush Test
    # Test 1: vs random
    res_rand = run_test(505, "random")
    # Test 2: self-play (vs economy_agent)
    res_self = run_test(505, economy_agent)
    
    all_success = res_rand and res_self
    sys.exit(0 if all_success else 1)
