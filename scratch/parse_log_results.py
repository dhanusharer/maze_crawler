import re

log_path = "C:/Users/DHANUSH A G/.gemini/antigravity-ide/brain/2ebd0f84-c6f0-4316-ac5b-785eb1b08a62/.system_generated/tasks/task-1538.log"

with open(log_path, "r") as f:
    lines = f.readlines()

current_seed = None
for line in lines:
    m = re.search(r"Evaluating Seed (\d+)", line)
    if m:
        current_seed = m.group(1)
        print(f"\nSeed {current_seed} started...")
    
    if "Simulation Finished" in line:
        print(f"  {line.strip()}")
    if "SUCCESS:" in line or "FAILURE:" in line:
        print(f"  Result: {line.strip()}")
