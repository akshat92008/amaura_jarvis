def render_tree(tree_dict: dict, indent: str = '') -> str:
    """Render a dictionary tree structure as an ASCII indented string.

    Args:
        tree_dict: Dictionary representing the tree structure
        indent: Current indentation string

    Returns:
        str: ASCII representation of the tree
    """
    tree_str = ''
    for i, (key, value) in enumerate(tree_dict.items()):
        # Determine if this is the last item in the current level
        is_last = i == len(tree_dict) - 1
        
        # Add the current node with appropriate prefix
        tree_str += f"{indent}{'└── ' if is_last else '├── '}{key}\n"
        
        # Recursively add children if they exist
        if isinstance(value, dict):
            new_indent = indent + ('    ' if is_last else '│   ')
            tree_str += render_tree(value, new_indent)
    
    return tree_str


def main():
    # Example tree structure
    example_tree = {
        'root': {
            'child1': {
                'grandchild1': {},
                'grandchild2': {}
            },
            'child2': {
                'grandchild3': {}
            }
        }
    }
    
    # Render and print the tree
    print(render_tree(example_tree))

if __name__ == '__main__':
    main()
