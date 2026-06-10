import sys
import os
from kaggle_environments import make

# Add current directory to path
sys.path.append(os.path.abspath(os.path.dirname(__file__) + "/.."))
import test_tactics

seeds = [505, 506, 507, 508, 509]
wins = 0

for seed in seeds:
    print(f"\nEvaluating Seed {seed}...")
    success = test_tactics.run_assassination_test(seed)
    if success:
        wins += 1

print(f"\nFinal Result: {wins}/{len(seeds)} wins!")
sys.exit(0 if wins == len(seeds) else 1)
