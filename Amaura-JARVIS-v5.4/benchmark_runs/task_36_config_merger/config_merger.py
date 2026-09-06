import os
from typing import Dict, Any

def merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two configuration dictionaries.

    Args:
        base: The base configuration dictionary.
        override: The override configuration dictionary.

    Returns:
        A new dictionary with the merged configurations.
    """
    merged = base.copy()
    for key, value in override.items():
        if (key in merged and isinstance(merged[key], dict)
                and isinstance(value, dict)):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value
    return merged

def interpolate_env_vars(config: Dict[str, Any], env: Dict[str, str]) -> Dict[str, Any]:
    """Replace environment variable placeholders in a configuration dictionary.

    Args:
        config: The configuration dictionary containing placeholders like `${VAR}`.
        env: The environment variables to use for interpolation.

    Returns:
        A new dictionary with placeholders replaced by environment variables.
    """
    interpolated = {}
    for key, value in config.items():
        if isinstance(value, dict):
            interpolated[key] = interpolate_env_vars(value, env)
        elif isinstance(value, str):
            # Replace all occurrences of ${VAR} with the corresponding environment variable
            for var_name, var_value in env.items():
                placeholder = f"${{{var_name}}}"
                if placeholder in value:
                    value = value.replace(placeholder, var_value)
            interpolated[key] = value
        else:
            interpolated[key] = value
    return interpolated

# Example usage
if __name__ == "__main__":
    base_config = {
        "database": {
            "host": "localhost",
            "port": 5432,
            "credentials": {
                "username": "admin",
                "password": "${DB_PASSWORD}"
            }
        },
        "logging": {
            "level": "info",
            "file": "${LOG_FILE}"
        }
    }

    override_config = {
        "database": {
            "port": 5433,
            "credentials": {
                "password": "${NEW_DB_PASSWORD}"
            }
        },
        "logging": {
            "level": "debug"
        },
        "timeout": 30
    }

    env_vars = {
        "DB_PASSWORD": "old_secret",
        "NEW_DB_PASSWORD": "new_secret",
        "LOG_FILE": "/var/log/app.log"
    }

    merged = merge_configs(base_config, override_config)
    interpolated = interpolate_env_vars(merged, env_vars)

    print("Merged Config:", merged)
    print("Interpolated Config:", interpolated)
