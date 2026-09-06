def validate_dict(data: dict, schema: dict) -> tuple[bool, list[str]]:    """Validate a dictionary against a schema.

    Args:
        data: The dictionary to validate.
        schema: The schema to validate against.

    Returns:
        A tuple containing a boolean indicating whether the validation passed, and a list of error messages.
    """
    errors = []

    for key, expected_type in schema.items():
        if key not in data:
            errors.append(f"Missing required key: {key}")
            continue

        value = data[key]
        if not isinstance(value, expected_type):
            errors.append(f"Invalid type for key '{key}': expected {expected_type.__name__}, got {type(value).__name__}")

    return len(errors) == 0, errors