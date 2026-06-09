# test_cartographer.py
from kaggle_environments import make
from cartographer import Cartographer

# Instantiate globally to persist across turns
bot_memory = Cartographer()

def development_agent(obs, config):
    # Pass observation frame into the memory matrix
    bot_memory.update(obs)
    
    actions = {}
    # Extract factory properties precisely by index
    for uid, data in obs.robots.items():
        rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
        move_cd, jump_cd, build_cd = data[5], data[6], data[7]
        
        if owner == obs.player and rtype == 0:  # Our Factory
            wall_ahead = bot_memory.is_wall(col, row, 'NORTH')
            
            # Print state details to the terminal console
            print(f"[Step {obs.step:03d}] Factory Row: {row} | "
                  f"Tiles Mapped: {len(bot_memory.global_map):4d} | "
                  f"Wall North: {str(wall_ahead):5s} | "
                  f"Jump CD: {jump_cd}")
            
            # Basic fallback survival move
            if not wall_ahead:
                actions[uid] = "NORTH"
            elif jump_cd == 0:
                actions[uid] = "JUMP_NORTH"
            else:
                actions[uid] = "IDLE"
                
    return actions

if __name__ == "__main__":
    # Test execution engine run
    print("Initializing baseline Cartographer verification...")
    env = make("crawl", configuration={"randomSeed": 101}, debug=True)
    env.run([development_agent, "random"])
    print("Match successfully executed.")