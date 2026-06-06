import os
import sys
import time
import multiprocessing
import math
from kaggle_environments import make

# Add current directory to path so dynamic imports work
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

# Elo helper functions
def calculate_expected_score(rating_a, rating_b):
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))

def update_elo(rating_a, rating_b, score_a, k_factor=32):
    expected = calculate_expected_score(rating_a, rating_b)
    new_rating = rating_a + k_factor * (score_a - expected)
    return new_rating

def run_match_worker(args):
    """
    Worker function to run a single match.
    args: (seed, worker_threshold, safety_buffer, opponent_type)
    opponent_type: "baseline" or "random"
    """
    seed, worker_threshold, safety_buffer, opponent_type = args
    
    # Force fresh import of submission inside child process
    try:
        if 'submission' in sys.modules:
            del sys.modules['submission']
        import submission
    except Exception as e:
        return {
            "seed": seed,
            "winner": -1,
            "reward_p0": -1,
            "reward_p1": -1,
            "steps": 0,
            "p0_status": "IMPORT_ERROR",
            "p1_status": "IMPORT_ERROR",
            "max_turn_time_p0": 0.0,
            "casualties_p0": 0,
            "violations_p0": 0,
            "error": f"Import error: {str(e)}"
        }
    
    # Configure parameters
    submission.TACTICS_PARAMS["WORKER_THRESHOLD"] = worker_threshold
    submission.TACTICS_PARAMS["SAFETY_BUFFER"] = safety_buffer
    
    # Reset persistent states
    submission.player_cartographers.clear()
    submission.controllers.clear()
    
    player_cartographers_baseline = {}
    controllers_baseline = {}
    
    # Audit tracking variables
    friendly_fire_casualties = {0: 0, 1: 0}
    previous_robots = {0: {}, 1: {}}
    previous_actions = {0: {}, 1: {}}
    build_actions_after_400 = {0: 0, 1: 0}
    max_turn_time = [0.0]
    
    DIR_OFFSETS = {
        "NORTH": (0, 1),
        "SOUTH": (0, -1),
        "EAST": (1, 0),
        "WEST": (-1, 0)
    }
    
    def audit_agent(obs, config, player, agent_fn):
        t0 = time.perf_counter()
        try:
            actions = agent_fn(obs, config)
        except Exception as e:
            raise e
        duration = time.perf_counter() - t0
        if duration > max_turn_time[0]:
            max_turn_time[0] = duration
            
        # friendly fire audit
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
                    dc, dr = DIR_OFFSETS[act]
                    t_col, t_row = p_col + dc, p_row + dr
                elif act.startswith("JUMP_"):
                    d = act.split("_")[1]
                    dc, dr = DIR_OFFSETS[d]
                    t_col, t_row = p_col + dc * 2, p_row + dr * 2
                prev_targets[p_uid] = (t_col, t_row)
                
            for p_uid, (p_col, p_row, p_type) in prev.items():
                if p_uid not in current_uids:
                    if p_row >= obs.southBound:
                        target_cell = prev_targets.get(p_uid, (p_col, p_row))
                        collision = False
                        for other_uid, other_target in prev_targets.items():
                            if other_uid != p_uid and other_target == target_cell:
                                collision = True
                                break
                        if collision:
                            friendly_fire_casualties[player] += 1
                            
        previous_robots[player] = current_friendly
        previous_actions[player] = actions.copy()
        
        # Step 400 action violations audit
        if obs.step >= 400:
            for uid, action in actions.items():
                if any(x in action for x in ["BUILD", "REMOVE"]):
                    build_actions_after_400[player] += 1
                    
        return actions
        
    def main_agent(obs, config):
        return audit_agent(obs, config, obs.player, submission.agent)
        
    def baseline_agent(obs, config):
        player = obs.player
        if player not in player_cartographers_baseline:
            player_cartographers_baseline[player] = submission.Cartographer(width=config.width, height=config.height)
            controllers_baseline[player] = submission.TrafficController(enable_tactics=False)
            
        cartographer = player_cartographers_baseline[player]
        controller = controllers_baseline[player]
        cartographer.update(obs)
        
        def baseline_fn(o, c):
            return controller.process_turn(o, cartographer, c)
            
        return audit_agent(obs, config, player, baseline_fn)
        
    env = make("crawl", configuration={"randomSeed": seed}, debug=False)
    
    if opponent_type == "baseline":
        opp = baseline_agent
    elif opponent_type == "random":
        opp = "random"
    else:
        opp = "random"
        
    try:
        env.run([main_agent, opp])
        state = env.state
        reward_p0 = state[0].reward if state[0].reward is not None else 0
        reward_p1 = state[1].reward if state[1].reward is not None else 0
        p0_status = state[0].status
        p1_status = state[1].status
        steps = env.steps[-1][0].observation.step
        
        if reward_p0 < 0 and reward_p1 < 0:
            winner = -1
        elif reward_p0 < 0:
            winner = 1
        elif reward_p1 < 0:
            winner = 0
        else:
            if reward_p0 > reward_p1:
                winner = 0
            elif reward_p1 > reward_p0:
                winner = 1
            else:
                winner = -1
                
        return {
            "seed": seed,
            "winner": winner,
            "reward_p0": reward_p0,
            "reward_p1": reward_p1,
            "steps": steps,
            "p0_status": p0_status,
            "p1_status": p1_status,
            "max_turn_time_p0": max_turn_time[0],
            "casualties_p0": friendly_fire_casualties[0],
            "violations_p0": build_actions_after_400[0],
            "error": None
        }
    except Exception as e:
        import traceback
        return {
            "seed": seed,
            "winner": -1,
            "reward_p0": -1,
            "reward_p1": -1,
            "steps": 0,
            "p0_status": "ERROR",
            "p1_status": "ERROR",
            "max_turn_time_p0": 0.0,
            "casualties_p0": 0,
            "violations_p0": 0,
            "error": str(e) + "\n" + traceback.format_exc()
        }

def evaluate_configuration(worker_threshold, safety_buffer, base_seed=100, num_matches=20):
    """Runs a series of matches against baseline and computes ELO and other metrics."""
    seeds = [base_seed + i for i in range(num_matches)]
    jobs = [(seed, worker_threshold, safety_buffer, "baseline") for seed in seeds]
    
    # We use a multiprocessing Pool to execute matches in parallel
    num_cpus = min(multiprocessing.cpu_count(), 8)
    print(f"Evaluating WT={worker_threshold}, SB={safety_buffer} using {num_cpus} processes...", flush=True)
    
    with multiprocessing.Pool(processes=num_cpus) as pool:
        results = pool.map(run_match_worker, jobs)
        
    wins = 0
    losses = 0
    draws = 0
    total_steps = 0
    max_turn_time = 0.0
    total_casualties = 0
    total_violations = 0
    elo = 1000.0
    baseline_elo = 1000.0
    
    for r in results:
        if r["error"]:
            print(f"  [Seed {r['seed']}] Error occurred: {r['error']}")
            losses += 1
            elo = update_elo(elo, baseline_elo, 0.0)
            continue
            
        winner = r["winner"]
        if winner == 0:
            wins += 1
            score = 1.0
        elif winner == 1:
            losses += 1
            score = 0.0
        else:
            draws += 1
            score = 0.5
            
        elo = update_elo(elo, baseline_elo, score)
        total_steps += r["steps"]
        max_turn_time = max(max_turn_time, r["max_turn_time_p0"])
        total_casualties += r["casualties_p0"]
        total_violations += r["violations_p0"]
        
    win_rate = (wins + 0.5 * draws) / num_matches if num_matches > 0 else 0.0
    avg_steps = total_steps / num_matches if num_matches > 0 else 0.0
    
    print(f"  Results: Wins: {wins} | Losses: {losses} | Draws: {draws} | Win Rate: {win_rate:.1%}")
    print(f"  Elo Rating: {elo:.1f} (vs Baseline 1000.0)")
    print(f"  Max Turn Time: {max_turn_time:.3f}s | Total Casualties: {total_casualties} | Total Violations: {total_violations}")
    print("-" * 50, flush=True)
    
    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": win_rate,
        "elo": elo,
        "max_turn_time": max_turn_time,
        "total_casualties": total_casualties,
        "total_violations": total_violations,
        "avg_steps": avg_steps
    }

def main():
    # Verify submission.py exists
    if not os.path.exists("submission.py"):
        print("Error: submission.py must be compiled before running crucible.")
        sys.exit(1)
        
    print("=" * 60, flush=True)
    print("CRUCIBLE HYPERPARAMETER TUNING & EVALUATION RUNNER", flush=True)
    print("=" * 60, flush=True)
    
    # Define hyperparameter grid
    worker_thresholds = [2, 3]
    safety_buffers = [2, 3]
    
    best_config = None
    best_elo = -1.0
    results_grid = {}
    
    for wt in worker_thresholds:
        for sb in safety_buffers:
            stats = evaluate_configuration(wt, sb, base_seed=200, num_matches=20)
            results_grid[(wt, sb)] = stats
            if stats["elo"] > best_elo:
                best_elo = stats["elo"]
                best_config = (wt, sb)
                
    print("\n" + "=" * 60, flush=True)
    print("TUNING SUMMARY", flush=True)
    print("=" * 60, flush=True)
    for (wt, sb), stats in results_grid.items():
        print(f"WT={wt}, SB={sb} -> Elo: {stats['elo']:.1f} | Win Rate: {stats['win_rate']:.1%} | Max Time: {stats['max_turn_time']:.3f}s | Casualties: {stats['total_casualties']}")
        
    print("-" * 60, flush=True)
    print(f"Best Configuration: WORKER_THRESHOLD={best_config[0]}, SAFETY_BUFFER={best_config[1]} (Elo: {best_elo:.1f})", flush=True)
    print("=" * 60, flush=True)
    
    # Compile final submission.py with the best configuration!
    print(f"Compiling final submission.py with WT={best_config[0]} and SB={best_config[1]}...", flush=True)
    from compiler import compile_submission
    compile_submission(worker_threshold=best_config[0], safety_buffer=best_config[1], output_path="submission.py")
    
    print("\nVerify syntax of final compiled file...", flush=True)
    import py_compile
    py_compile.compile("submission.py")
    print("Final validation: syntax of submission.py is CORRECT!")
    print("Crucible tuning completed successfully!", flush=True)

if __name__ == '__main__':
    # Required for Windows multiprocessing compatibility
    multiprocessing.freeze_support()
    main()
