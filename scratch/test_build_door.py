from kaggle_environments import make

def test_agent(obs, config):
    actions = {}
    player = obs.player
    
    # Scan for doorways in our global map (we can check all rows up to obs.northBound)
    # Even if they are not in visibility, we can scan obs.walls.
    # Note: obs.walls contains flat array from southBound to northBound.
    doorway_row = None
    for r in range(obs.southBound, obs.northBound + 1):
        idx = (r - obs.southBound) * 20 + 9
        val = obs.walls[idx]
        if val != -1 and not (val & 2): # EAST bit is 2
            doorway_row = r
            break

    # Locate our robots
    for uid, data in obs.robots.items():
        rtype, col, row, energy, owner = data[0], data[1], data[2], data[3], data[4]
        if owner == player:
            if rtype == 0: # Factory
                if obs.step == 0:
                    actions[uid] = "BUILD_WORKER_NORTH"
                else:
                    # Move North to keep up and explore
                    actions[uid] = "NORTH"
            elif rtype == 2: # Worker
                if doorway_row is not None:
                    if col != 9 or row != doorway_row:
                        # Move toward (9, doorway_row)
                        if col < 9:
                            actions[uid] = "EAST"
                        elif col > 9:
                            actions[uid] = "WEST"
                        elif row < doorway_row:
                            actions[uid] = "NORTH"
                        elif row > doorway_row:
                            actions[uid] = "SOUTH"
                    else:
                        # We are at the doorway! Try to weld it
                        actions[uid] = "BUILD_EAST"
                        print(f"Step {obs.step} - Worker at doorway, energy: {energy}. Wall value at doorway cell: {obs.walls[(row - obs.southBound)*20 + 9]}")
                else:
                    # Move north to find doorways
                    actions[uid] = "NORTH"
    return actions

env = make("crawl", configuration={"randomSeed": 505}, debug=True)
env.run([test_agent, "random"])
state = env.state
obs = state[0].observation
print(f"Final Step: {obs.step}")
