from pathfinder import find_reachable_paths, project_south_bound, find_path

class MacroManager:
    def __init__(self):
        self.remembered_nodes = set()

    def update(self, obs):
        """Update macro manager state at the beginning of each turn."""
        self.update_nodes(obs)

    def update_nodes(self, obs):
        """Update the set of remembered mining nodes based on visibility and status."""
        # Add currently visible mining nodes
        for key in obs.miningNodes.keys():
            try:
                col, row = map(int, key.split(","))
                self.remembered_nodes.add((col, row))
            except ValueError:
                pass
        
        # Remove any node that has been swallowed by the scrolling southern boundary
        self.remembered_nodes = {
            (c, r) for (c, r) in self.remembered_nodes 
            if r >= obs.southBound
        }
        
        # Remove nodes that already have mines on them (regardless of owner)
        for key in obs.mines.keys():
            try:
                col, row = map(int, key.split(","))
                self.remembered_nodes.discard((col, row))
            except ValueError:
                pass

    def get_swallowed_step(self, row, current_step, current_south, scroll_counter, config):
        """Predicts the exact step when the given row will scroll below the southern boundary."""
        scroll_ramp_steps = getattr(config, "scrollRampSteps", 400)
        scroll_start_interval = getattr(config, "scrollStartInterval", 4)
        scroll_end_interval = getattr(config, "scrollEndInterval", 1)
        
        def get_scroll_interval(s):
            if s >= scroll_ramp_steps:
                return scroll_end_interval
            progress = s / max(1, scroll_ramp_steps)
            interval = scroll_start_interval - (scroll_start_interval - scroll_end_interval) * progress
            return max(scroll_end_interval, round(interval))
            
        south = current_south
        counter = scroll_counter
        step = current_step
        
        while step <= 500:
            if south > row:
                return step
            counter -= 1
            if counter <= 0:
                south += 1
                counter = get_scroll_interval(step)
            step += 1
        return 501

    def get_build_choice(self, obs, cartographer, friendly_units, config, should_build_worker=False):
        """
        Evaluates current resources and unit count to determine the optimal build action.
        Returns:
            1 (Scout), 2 (Worker), 3 (Miner), or None
        """
        step = obs.step
        
        # 1. Step 400 Financial Freeze
        if step >= 400:
            return None
            
        factory_uid = None
        for uid, unit in friendly_units.items():
            if unit["type"] == 0:
                factory_uid = uid
                break
                
        if not factory_uid:
            return None
            
        factory = friendly_units[factory_uid]
        
        # Spawning cooldown check
        if factory["build_cd"] > 0:
            return None
            
        # Update our mining node tracking
        self.update_nodes(obs)
        
        # Count currently active friendly robots
        active_scouts = sum(1 for u in friendly_units.values() if u["type"] == 1)
        active_workers = sum(1 for u in friendly_units.values() if u["type"] == 2)
        active_miners = sum(1 for u in friendly_units.values() if u["type"] == 3)
        
        scout_cost = getattr(config, "scoutCost", 50)
        worker_cost = getattr(config, "workerCost", 200)
        miner_cost = getattr(config, "minerCost", 300)
        
        # Helper: check if factory has enough energy (with a 100 energy safety margin)
        def can_afford(cost):
            return factory["energy"] > cost + 100

        # --- A. Scout Cap Utility ---
        scout_utility = 0.0
        if step < 150 and can_afford(scout_cost):
            if active_scouts < 1:
                scout_utility = 1.0
            elif active_scouts == 1:
                scout_utility = 0.2
            else:
                scout_utility = 0.0

        # --- B. Worker Emergency/Offensive Utility ---
        worker_utility = 0.0
        if can_afford(worker_cost):
            if should_build_worker and active_workers == 0:
                worker_utility = 0.95
            else:
                if active_workers == 0:
                    # Run pathfinding to see if Factory has any path to move northward
                    scroll_counter = getattr(obs, "scrollCounter", 4)
                    paths = find_reachable_paths(
                        cartographer, (factory["col"], factory["row"]),
                        step, obs.southBound, scroll_counter,
                        getattr(config, "factoryMovePeriod", 2), config, max_depth=15,
                        initial_jump_cd=factory["jump_cd"]
                    )
                    # If no reachable cell has a row strictly higher than current row, we are blocked
                    has_forward_path = any(pos[1] > factory["row"] for pos in paths.keys())
                    if not has_forward_path:
                        worker_utility = 0.9

        # --- C. Miner ROI Utility ---
        miner_utility = 0.0
        if can_afford(miner_cost):
            scroll_counter = getattr(obs, "scrollCounter", 4)
            factory_pos = (factory["col"], factory["row"])
            
            # Check all known nodes and evaluate if any are viable and untargeted
            for node in self.remembered_nodes:
                # Only target nodes strictly north of the Factory plus a buffer of 3
                if node[1] < factory_pos[1] + 3:
                    continue
                # 1. Skip if already mined
                if f"{node[0]},{node[1]}" in obs.mines:
                    continue
                
                # 2. Skip if an existing miner is already at this node
                miner_already_there = any(
                    (u["col"], u["row"]) == node and u["type"] == 3 
                    for u in friendly_units.values()
                )
                if miner_already_there:
                    continue
                
                # 3. Calculate path distance for a Miner (move period = 2)
                path = find_path(
                    cartographer, factory_pos, node,
                    step, obs.southBound, scroll_counter,
                    2, config
                )
                if path is None:
                    continue
                # Reject paths that go too far south of the Factory
                min_row = min(pos[1] for pos in path)
                if min_row < factory_pos[1] - 1:
                    continue
                    
                path_len = len(path)
                arrival_turns = 2 * path_len + 1  # 2 turns per step + 1 turn to transform
                
                factory_move_period = getattr(config, "factoryMovePeriod", 2)
                expected_factory_row = factory_pos[1] + (arrival_turns // factory_move_period)
                if node[1] < expected_factory_row:
                    continue
                
                t_swallowed = self.get_swallowed_step(
                    node[1], step, obs.southBound, scroll_counter, config
                )
                surviving_turns = t_swallowed - step
                
                # ROI condition: Surviving Turns - Arrival Turns > 8
                if surviving_turns - arrival_turns > 8:
                    miner_utility = 0.8
                    break

        # Select the choice with the highest utility
        utilities = {
            1: scout_utility,
            2: worker_utility,
            3: miner_utility
        }
        
        best_type = max(utilities, key=utilities.get)
        if utilities[best_type] > 0.0:
            return best_type
        return None

    def get_liquidation_targets(self, obs, cartographer, friendly_units, config):
        """
        Post-step 400 Capital Liquidation: identify friendly mines with accumulated
        energy so the Factory can route over them and vacuum the capital for the
        end-game tiebreaker score.
        Returns:
            list of (col, row, energy) sorted by energy descending.
        """
        targets = []
        for key, mine_data in obs.mines.items():
            try:
                col, row = map(int, key.split(","))
            except ValueError:
                continue

            mine_energy = mine_data[0]
            mine_owner = mine_data[2]

            # Only harvest our own mines that have energy
            if mine_owner == obs.player and mine_energy > 0:
                # Skip mines that are about to be swallowed
                if row <= obs.southBound + 2:
                    continue
                targets.append((col, row, mine_energy))

        # Sort by energy descending — harvest the richest mines first
        targets.sort(key=lambda t: -t[2])
        return targets
