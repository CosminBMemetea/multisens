"""Secret-reference resolution for connector configuration (v0.9, Phase
95). `config/sensors.yaml` stays a git-tracked file - a `password: hunter2`
entry there would be a committed secret. The `<field>_env` convention
(`password_env: CAMERA_PASSWORD`) lets a config value be a *reference* to
an environment variable instead, resolved here at connect time only,
never persisted anywhere and never echoed back through any API/log -
this is the only place a `*_env` reference is ever turned into a real
value.

`redact_secrets` (v0.9, Phase 102) is the outbound counterpart: scrubs
secret-shaped values before they leave the process through an API
response, so the "never echoed back" guarantee above holds for the new
`/api/plugins`/`/api/connectors` routes too.
"""
from __future__ import annotations

import os
from typing import Any

from multisens_sdk import ConnectorConfigError

ENV_REF_SUFFIX = '_env'
# Case-insensitive substring match, deliberately broad (v0.9, Phase 102,
# issue #103) - `password_env`/`api_key`/`auth_token` must all be caught
# by the same check that catches a literal `password`, so redaction never
# depends on which of the two forms a plugin author chose.
SECRET_KEY_PATTERNS = ('password', 'token', 'secret', 'key')
REDACTED = '***REDACTED***'


def resolve_secret_env_refs(config: dict[str, Any]) -> dict[str, Any]:
    """Returns a new dict: every `<field>_env` key is replaced by
    `<field>` holding the named environment variable's actual value; the
    `_env` key itself and the raw variable name are dropped, never
    forwarded. A referenced variable that isn't set is a clean
    `ConnectorConfigError` - never a silent empty string standing in for
    a real secret. Fields with no `_env` suffix pass through unchanged."""
    resolved: dict[str, Any] = {}
    for key, value in config.items():
        if key.endswith(ENV_REF_SUFFIX) and isinstance(value, str):
            field_name = key[:-len(ENV_REF_SUFFIX)]
            env_value = os.environ.get(value)
            if env_value is None:
                raise ConnectorConfigError(
                    f"environment variable '{value}' (referenced by config field '{key}') is not set"
                )
            resolved[field_name] = env_value
        else:
            resolved[key] = value
    return resolved


def redact_secrets(value: Any) -> Any:
    """Recursively replaces any dict value whose key matches
    `SECRET_KEY_PATTERNS` with `REDACTED`, for anything about to leave the
    process through an API response (v0.9, Phase 102) - `resolve_secret_env_refs`
    above is the opposite direction (turns a reference into a real value at
    connect time); this is the one place a value coming back *out* is
    scrubbed before a browser ever sees it. Applied to connector `config`,
    plugin `capabilities`, and connector `health.details` alike - anywhere
    a plugin's own dict could carry a secret through."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if any(p in k.lower() for p in SECRET_KEY_PATTERNS) else redact_secrets(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value
