def simple_diff(old_lines: list[str], new_lines: list[str]) -> list[str]:
    """Generate a simple diff between two lists of strings.

    Args:
        old_lines: List of strings representing the old version.
        new_lines: List of strings representing the new version.

    Returns:
        List of strings with diff markers (' ', '-', '+').
    """
    diff_result = []
    i = j = 0
    
    while i < len(old_lines) and j < len(new_lines):
        if old_lines[i] == new_lines[j]:
            diff_result.append(f' {old_lines[i]}')
            i += 1
            j += 1
        elif old_lines[i] in new_lines[j:]:
            # Line exists in new version but is out of order
            diff_result.append(f'-{old_lines[i]}')
            i += 1
        else:
            # Line is new in the new version
            diff_result.append(f'+{new_lines[j]}')
            j += 1
    
    # Handle remaining lines in old version
    while i < len(old_lines):
        diff_result.append(f'-{old_lines[i]}')
        i += 1
    
    # Handle remaining lines in new version
    while j < len(new_lines):
        diff_result.append(f'+{new_lines[j]}')
        j += 1
    
    return diff_result
