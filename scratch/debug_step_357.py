import sys
from kaggle_environments import make
from cartographer import Cartographer
from orchestrator import TrafficController
import test_tactics

# Open a file for writing debug logs
debug_file = open("scratch/debug_out.txt", "w")

# We can reuse the agents from test_tactics, but wrap them
def debug_tactical_agent(obs, config):
    player = obs.player
    if player not in test_tactics.player_cartographers:
        test_tactics.player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        test_tactics.controllers[player] = TrafficController(enable_tactics=True)
        test_tactics.previous_robots[player] = {}
        test_tactics.previous_actions[player] = {}
        
    controller = test_tactics.controllers[player]
    
    # Wrap process_turn to print debug info
    if not hasattr(controller, "_wrapped"):
        orig_process_turn = controller.process_turn
        def custom_process_turn(obs_val, cartographer_val, config_val):
            res = orig_process_turn(obs_val, cartographer_val, config_val)
            if 50 <= obs_val.step <= 333:
                debug_file.write(f"\n--- STEP {obs_val.step} ---\n")
                factory_uid = None
                for uid, data in obs_val.robots.items():
                    if data[4] == obs_val.player and data[0] == 0:
                        factory_uid = uid
                        debug_file.write(f"Factory P0: pos=({data[1]},{data[2]}), energy={data[3]}, action={res.get(uid)}, jump_cd={data[6]}\n")
                    elif data[4] != obs_val.player and data[0] == 0:
                        debug_file.write(f"Factory P1: pos=({data[1]},{data[2]}), energy={data[3]}, action={res.get(uid)}, jump_cd={data[6] if len(data) > 6 else 0}\n")
                
                # Print friendly units list with energy
                friendly_units_list = []
                for uid, data in obs_val.robots.items():
                    if data[4] == obs_val.player:
                        friendly_units_list.append(f"{data[0]} at ({data[1]},{data[2]}) energy={data[3]}")
                debug_file.write(f"Friendly robots: {friendly_units_list}\n")
                
                # Print liquidation targets
                liq_targets = controller.macro_manager.get_liquidation_targets(obs_val, cartographer_val, {}, config_val)
                debug_file.write(f"Liquidation targets: {liq_targets}\n")
                
                # Print tactical_targets of the Factory
                debug_file.write(f"Unit targets registry: {controller.unit_targets}\n")
                debug_file.write(f"Unit paths registry: {controller.unit_paths}\n")
                
            return res
            
        controller.process_turn = custom_process_turn
        controller._wrapped = True
        
    actions = test_tactics.run_agent_turn(obs, config, player)
    return actions

def debug_baseline_agent(obs, config):
    return test_tactics.baseline_agent(obs, config)

env = make("crawl", configuration={"randomSeed": 505}, debug=True)
env.run([debug_tactical_agent, debug_baseline_agent])
debug_file.close()



