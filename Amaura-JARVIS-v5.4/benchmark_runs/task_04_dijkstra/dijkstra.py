def dijkstra(graph: dict[str, dict[str, float]], start: str) -> dict[str, float]:
    """
    Calculate the shortest path distances from a starting node to all other nodes in a weighted graph.
    
    Args:
        graph: A dictionary representing the graph where keys are node names and values are dictionaries
               of neighboring nodes and their edge weights.
        start: The starting node name.
    
    Returns:
        A dictionary mapping each node to its shortest distance from the start node.
    """
    # Initialize distances with infinity for all nodes except the start node
    distances = {node: float('infinity') for node in graph}
    distances[start] = 0
    
    # Priority queue to process nodes in order of their current shortest distance
    priority_queue = [(0, start)]
    
    while priority_queue:
        current_distance, current_node = priority_queue.pop(0)
        
        # Skip if we've already found a better path
        if current_distance > distances[current_node]:
            continue
        
        # Explore neighbors
        for neighbor, weight in graph[current_node].items():
            distance = current_distance + weight
            
            # Update distance if a shorter path is found
            if distance < distances[neighbor]:
                distances[neighbor] = distance
                priority_queue.append((distance, neighbor))
    
    return distances
