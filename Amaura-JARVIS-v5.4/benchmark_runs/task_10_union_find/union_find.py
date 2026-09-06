class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, p: int) -> int:
        while self.parent[p] != p:
            self.parent[p] = self.parent[self.parent[p]]  # Path compression
            p = self.parent[p]
        return p

    def union(self, p: int, q: int) -> bool:
        root_p = self.find(p)
        root_q = self.find(q)
        if root_p == root_q:
            return False  # Already connected
        
        # Union by rank
        if self.rank[root_p] > self.rank[root_q]:
            self.parent[root_q] = root_p
        elif self.rank[root_p] < self.rank[root_q]:
            self.parent[root_p] = root_q
        else:
            self.parent[root_q] = root_p
            self.rank[root_p] += 1
        return True

    def connected(self, p: int, q: int) -> bool:
        return self.find(p) == self.find(q)
