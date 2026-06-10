from kaggle_environments import make
from cartographer import Cartographer
from orchestrator import TrafficController

env = make("crawl", configuration={"randomSeed": 505}, debug=True)

# Symmetrical setup as test_tactics.py
player_cartographers = {}
controllers = {}

def debug_agent(obs, config):
    player = obs.player
    if player not in player_cartographers:
        player_cartographers[player] = Cartographer(width=config.width, height=config.height)
        controllers[player] = TrafficController(enable_tactics=(player == 0))
        
    cartographer = player_cartographers[player]
    controller = controllers[player]
    cartographer.update(obs)
    
    actions = controller.process_turn(obs, cartographer, config)
    
    if obs.step in [73, 74, 75]:
        print(f"\n--- [Step {obs.step} | Player {player}] ---")
        print(f"southBound: {obs.southBound}")
        print("Robots:")
        for uid, rdata in obs.robots.items():
            rtype, col, row, energy, owner = rdata[0], rdata[1], rdata[2], rdata[3], rdata[4]
            typename = ["Factory", "Scout", "Worker", "Miner"][rtype]
            print(f"  {typename} {uid[:4]} at ({col},{row}) owner: {owner} energy: {energy} move_cd: {rdata[5]} jump_cd: {rdata[6]}")
        print(f"Factory action: {actions.get(next(k for k,v in obs.robots.items() if v[4] == player and v[0] == 0), 'IDLE')}")
        print(f"All actions: {actions}")
        
    return actions

env.run([debug_agent, debug_agent])
