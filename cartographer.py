class Cartographer:
    WALL_N = 1
    WALL_E = 2
    WALL_S = 4
    WALL_W = 8
    
    DIR_WALL_BIT = {
        "NORTH": WALL_N,
        "EAST": WALL_E,
        "SOUTH": WALL_S,
        "WEST": WALL_W
    }
    
    OPPOSITE_DIR = {
        "NORTH": "SOUTH",
        "SOUTH": "NORTH",
        "EAST": "WEST",
        "WEST": "EAST"
    }
    
    DIR_OFFSETS = {
        "NORTH": (0, 1),
        "SOUTH": (0, -1),
        "EAST": (1, 0),
        "WEST": (-1, 0)
    }

    def __init__(self, width=20, height=20):
        self.width = width
        self.height = height
        # Global map of walls: (col, row) -> wall_bitfield
        self.global_map = {}
        # Keep track of bounds
        self.south_bound = 0
        self.north_bound = height - 1

    def update(self, obs):
        """Update global map with observation data."""
        self.south_bound = obs.southBound
        self.north_bound = obs.northBound
        
        # obs.walls contains flat array from southBound to northBound
        # Index: (row - southBound) * width + col
        for idx, val in enumerate(obs.walls):
            if val != -1:
                col = idx % self.width
                row = self.south_bound + (idx // self.width)
                self.global_map[(col, row)] = val

    def get_wall(self, col, row):
        return self.global_map.get((col, row), -1)

    def is_wall(self, col, row, direction):
        """Check if there is a wall in the given direction from (col, row)."""
        bit = self.DIR_WALL_BIT.get(direction, 0)
        # Check source cell
        if (col, row) in self.global_map:
            if self.global_map[(col, row)] & bit:
                return True
        # Check target cell
        dc, dr = self.DIR_OFFSETS.get(direction, (0, 0))
        target_pos = (col + dc, row + dr)
        opp_dir = self.OPPOSITE_DIR.get(direction, "")
        opp_bit = self.DIR_WALL_BIT.get(opp_dir, 0)
        if target_pos in self.global_map:
            if self.global_map[target_pos] & opp_bit:
                return True
        return False

    def is_walkable(self, col, row, direction):
        """Check if we can move from (col, row) in the given direction based on mapped walls."""
        dc, dr = self.DIR_OFFSETS[direction]
        nc, nr = col + dc, row + dr
        if nc < 0 or nc >= self.width or nr < 0:
            return False
        return not self.is_wall(col, row, direction)

    def get_mapped_count(self):
        return len(self.global_map)
