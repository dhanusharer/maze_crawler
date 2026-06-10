import re

log_path = "C:/Users/DHANUSH A G/.gemini/antigravity-ide/brain/2ebd0f84-c6f0-4316-ac5b-785eb1b08a62/.system_generated/tasks/task-987.log"

factory_lines = []
with open(log_path, "r") as f:
    for line in f:
        if "Factory:" in line and "Step" in line:
            # e.g., [Step 043 | Baseline (P1)] Factory: (17, 7) | E: 857 | Scouts: 2 | Workers: 0 | Miners: 0 | Action: IDLE
            match = re.search(r"\[Step (\d+) \| ([^\]]+)\] Factory: \(([^)]+)\) \| E: (\d+) \| .*? \| Action: (\w+)", line)
            if match:
                step = int(match.group(1))
                player = match.group(2)
                pos = match.group(3)
                energy = int(match.group(4))
                action = match.group(5)
                if step >= 200:
                    factory_lines.append((step, player, pos, energy, action))

for step in sorted(list(set(s for s, _, _, _, _ in factory_lines))):
    p0_info = next((f for f in factory_lines if f[0] == step and "Tactical" in f[1]), None)
    p1_info = next((f for f in factory_lines if f[0] == step and "Baseline" in f[1]), None)
    
    p0_str = f"P0 (Tactical): {p0_info[2]} {p0_info[4]}" if p0_info else ""
    p1_str = f"P1 (Baseline): {p1_info[2]} {p1_info[4]}" if p1_info else ""
    print(f"Step {step:03d} | {p0_str:25s} | {p1_str}")
