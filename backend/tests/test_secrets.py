"""Phase 95 (v0.9): `*_env` secret-reference resolution."""
import pytest
from app.plugins.secrets import resolve_secret_env_refs
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
