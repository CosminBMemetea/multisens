"""Phase 95 (v0.9): `*_env` secret-reference resolution. Phase 102 adds
`redact_secrets` - the outbound counterpart used by `/api/plugins` and
`/api/connectors` (issue #103's own explicit redaction requirement).
"""
import pytest
from app.plugins.secrets import REDACTED, redact_secrets, resolve_secret_env_refs
from multisens_sdk import ConnectorConfigError


def test_plain_fields_pass_through_unchanged():
    config = {'uri': 'rtsp://example/rgb', 'transport': 'tcp'}
    assert resolve_secret_env_refs(config) == config


def test_env_ref_resolves_to_the_actual_value_under_the_stripped_field_name(monkeypatch):
    monkeypatch.setenv('CAMERA_PASSWORD', 'hunter2')
    resolved = resolve_secret_env_refs({'uri': 'rtsp://example/rgb', 'password_env': 'CAMERA_PASSWORD'})
    assert resolved == {'uri': 'rtsp://example/rgb', 'password': 'hunter2'}
    # The _env key itself and the raw variable name are never forwarded.
    assert 'password_env' not in resolved
    assert 'CAMERA_PASSWORD' not in resolved.values()


def test_missing_env_var_raises_connector_config_error_not_a_silent_empty_string(monkeypatch):
    monkeypatch.delenv('DOES_NOT_EXIST_VAR', raising=False)
    with pytest.raises(ConnectorConfigError, match='DOES_NOT_EXIST_VAR'):
        resolve_secret_env_refs({'token_env': 'DOES_NOT_EXIST_VAR'})


def test_multiple_env_refs_all_resolve_independently(monkeypatch):
    monkeypatch.setenv('CAM_USER', 'admin')
    monkeypatch.setenv('CAM_PASS', 'hunter2')
    resolved = resolve_secret_env_refs({'username_env': 'CAM_USER', 'password_env': 'CAM_PASS', 'port': 554})
    assert resolved == {'username': 'admin', 'password': 'hunter2', 'port': 554}


def test_non_string_env_value_is_not_treated_as_a_reference():
    # A field that merely happens to be named "*_env" but isn't a string
    # (e.g. a genuinely-named numeric field) is passed through as-is,
    # never mistaken for an environment-variable reference.
    resolved = resolve_secret_env_refs({'retry_count_env': 3})
    assert resolved == {'retry_count_env': 3}


# --- v0.9, Phase 102: redact_secrets ----------------------------------------

def test_redact_secrets_leaves_ordinary_fields_untouched():
    config = {'uri': 'rtsp://example/rgb', 'transport': 'tcp', 'port': 554}
    assert redact_secrets(config) == config


def test_redact_secrets_redacts_a_literal_secret_value():
    redacted = redact_secrets({'uri': 'rtsp://example/rgb', 'password': 'hunter2'})
    assert redacted == {'uri': 'rtsp://example/rgb', 'password': REDACTED}
    assert 'hunter2' not in str(redacted)


def test_redact_secrets_redacts_an_env_reference_too_never_just_the_literal_form():
    # The *_env form names an environment variable, not the secret itself
    # - still redacted, since the variable *name* can be sensitive/
    # identifying on its own and issue #103 requires both forms caught by
    # the same check.
    redacted = redact_secrets({'password_env': 'CAMERA_PASSWORD'})
    assert redacted == {'password_env': REDACTED}


@pytest.mark.parametrize('key', ['password', 'Password', 'API_KEY', 'auth_token', 'client_secret', 'secretValue'])
def test_redact_secrets_matches_case_insensitively_and_as_a_substring(key):
    assert redact_secrets({key: 'sensitive-value'}) == {key: REDACTED}


def test_redact_secrets_recurses_into_nested_dicts_and_lists():
    nested = {
        'connector': {
            'plugin': 'acme.sensor.camera',
            'config': {'uri': 'rtsp://x', 'password': 'hunter2'},
        },
        'cameras': [
            {'id': 'front', 'token': 'abc123'},
            {'id': 'rear', 'token': 'def456'},
        ],
    }
    redacted = redact_secrets(nested)
    assert redacted['connector']['config'] == {'uri': 'rtsp://x', 'password': REDACTED}
    assert redacted['cameras'] == [{'id': 'front', 'token': REDACTED}, {'id': 'rear', 'token': REDACTED}]
    assert 'hunter2' not in str(redacted)
    assert 'abc123' not in str(redacted)
