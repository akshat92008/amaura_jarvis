def parse_cron_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """Parse a cron field string and return the set of matching values.

    Args:
        field_str: The cron field string (e.g., '*/5', '1-10', '*')
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        set[int]: Set of matching values

    Raises:
        ValueError: If the field string is invalid
    """
    result = set()

    if field_str == '*':
        return set(range(min_val, max_val + 1))

    for part in field_str.split(','):
        if '/' in part:
            step_part, step = part.split('/')
            step = int(step)

            if step_part == '*':
                start = min_val
            else:
                start = int(step_part)

            for value in range(start, max_val + 1, step):
                if value <= max_val:
                    result.add(value)
        elif '-' in part:
            start, end = map(int, part.split('-'))
            result.update(range(start, end + 1))
        else:
            result.add(int(part))

    return result


def parse_cron_expression(cron_expr: str) -> dict[str, set[int]]:
    """Parse a full cron expression and return a dictionary of field sets.

    Args:
        cron_expr: The full cron expression (e.g., '*/5 * * * *')

    Returns:
        dict[str, set[int]]: Dictionary of field sets with keys 'minute', 'hour', etc.

    Raises:
        ValueError: If the cron expression is invalid
    """
    fields = cron_expr.split()
    if len(fields) != 5:
        raise ValueError("Cron expression must have exactly 5 fields")

    minute = parse_cron_field(fields[0], 0, 59)
    hour = parse_cron_field(fields[1], 0, 23)
    day_of_month = parse_cron_field(fields[2], 1, 31)
    month = parse_cron_field(fields[3], 1, 12)
    day_of_week = parse_cron_field(fields[4], 0, 6)

    return {
        'minute': minute,
        'hour': hour,
        'day_of_month': day_of_month,
        'month': month,
        'day_of_week': day_of_week,
    }
