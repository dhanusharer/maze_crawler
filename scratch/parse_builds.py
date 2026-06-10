log_path = "run_tactics.log"

print("=== Factory Trace (Steps 138 to 165) ===")
with open(log_path, 'r', encoding='utf-16') as f:
    for line in f:
        if "DEBUG_FACTORY" in line:
            parts = line.strip().split()
            step = int(parts[2])
            # Check for P0 (pos col <= 9)
            pos_part = parts[4] # pos: (x,y)
            col = int(pos_part.split('(')[1].split(',')[0])
            if 138 <= step <= 165 and col <= 9:
                print(line.strip())
