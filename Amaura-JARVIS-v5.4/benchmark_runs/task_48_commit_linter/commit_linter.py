def lint_commit_message(message: str) -> tuple[bool, str]:
    """
    Lint a commit message to ensure it follows conventional commit format.
    
    Args:
        message: The commit message to lint
    
    Returns:
        A tuple containing:
        - bool: True if valid, False if invalid
        - str: Validation message or error details
    """
    # Check for empty message
    if not message.strip():
        return False, "Commit message cannot be empty"
    
    # Split into parts
    parts = message.split(':', 1)
    if len(parts) != 2:
        return False, "Commit message must follow format: type(scope): subject"
    
    header, body = parts
    header = header.strip()
    body = body.strip()
    
    # Validate header format
    if '(' not in header or ')' not in header:
        return False, "Header must include scope in parentheses: type(scope)"
    
    # Extract type and scope
    type_scope, subject = header.split('(', 1)
    if ')' not in type_scope:
        return False, "Scope must be enclosed in parentheses"
    
    commit_type, scope = type_scope.split(')', 1)
    scope = scope.strip()
    commit_type = commit_type.strip()
    
    # Validate commit type
    valid_types = {'feat', 'fix', 'docs', 'refactor', 'test', 'chore'}
    if commit_type not in valid_types:
        return False, f"Invalid commit type '{commit_type}'. Must be one of: {', '.join(valid_types)}"
    
    # Validate subject
    if not subject.strip():
        return False, "Subject cannot be empty"
    
    # Check subject length
    if len(subject) > 50:
        return False, "Subject should be 50 characters or less"
    
    # Check for body if present
    if body:
        if len(body.split('\n')) > 1:
            # Check body line length
            for line in body.split('\n'):
                if len(line) > 72:
                    return False, "Body lines should be 72 characters or less"
    
    return True, "Commit message follows conventional commit format"
