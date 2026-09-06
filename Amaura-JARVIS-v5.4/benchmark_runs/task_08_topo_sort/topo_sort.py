from collections import deque

def topological_sort(num_nodes: int, edges: list[tuple[int, int]]) -> list[int]:
    # Initialize in-degree count and adjacency list
    in_degree = [0] * num_nodes
    adj_list = [[] for _ in range(num_nodes)]
    
    # Build adjacency list and in-degree count
    for u, v in edges:
        adj_list[u].append(v)
        in_degree[v] += 1
    
    # Initialize queue with nodes having zero in-degree
    queue = deque([node for node in range(num_nodes) if in_degree[node] == 0])
    topo_order = []
    
    # Process nodes in queue
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        
        # Reduce in-degree for neighbors
        for neighbor in adj_list[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    # Check for cycle
    if len(topo_order) != num_nodes:
        return []
    
    return topo_order