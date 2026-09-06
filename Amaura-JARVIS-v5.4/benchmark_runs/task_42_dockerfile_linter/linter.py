def lint_dockerfile(content: str) -> list[str]:
    """Lint a Dockerfile for common issues.

    Args:
        content: The content of the Dockerfile as a string.

    Returns:
        A list of linting issues found.
    """
    issues = []
    lines = content.split('\n')

    # Check for :latest base image tags
    for line in lines:
        if line.strip().startswith('FROM') and ':latest' in line:
            issues.append("Avoid using ':latest' tag in base image. Use a specific version.")
            break

    # Check for missing USER directive
    has_user = any(line.strip().startswith('USER') for line in lines)
    if not has_user:
        issues.append("Missing USER directive. Consider adding a non-root user.")

    return issues
