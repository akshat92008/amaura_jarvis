def compare_env_files(example_content: str, actual_content: str) -> dict:
    # Parse example content into a dictionary
    example_lines = example_content.splitlines()
    example_env = {}
    for line in example_lines:
        if line.strip() and not line.startswith('#'):
            key, value = line.split('=', 1)
            example_env[key.strip()] = value.strip()

    # Parse actual content into a dictionary
    actual_lines = actual_content.splitlines()
    actual_env = {}
    for line in actual_lines:
        if line.strip() and not line.startswith('#'):
            key, value = line.split('=', 1)
            actual_env[key.strip()] = value.strip()

    # Compare the dictionaries
    missing_keys = [key for key in example_env if key not in actual_env]
    extra_keys = [key for key in actual_env if key not in example_env]
    matching_keys = [key for key in example_env if key in actual_env and example_env[key] == actual_env[key]]

    return {
        'missing_keys': missing_keys,
        'extra_keys': extra_keys,
        'matching_keys': matching_keys
    }