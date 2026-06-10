import re
log_path = "C:/Users/DHANUSH A G/.gemini/antigravity-ide/brain/2ebd0f84-c6f0-4316-ac5b-785eb1b08a62/.system_generated/tasks/task-1494.log"
in_seed_509 = False
with open(log_path, "r") as f:
    for line in f:
        if "Assassination Test (Seed 509)" in line:
            in_seed_509 = True
            print("=== START SEED 509 ===")
            continue
        if in_seed_509:
            if "Tactical (P0)" in line or "DEBUG_FACTORY" in line or "DEBUG_WORKER" in line or "DEBUG_SCOUT" in line:
                m = re.search(r"Step (\d+)", line)
                if m and int(m.group(1)) >= 350:
                    print(line.strip())












