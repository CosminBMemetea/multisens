"""Phase 105 (v0.9) robustness & security review: the plugin trust model
(docs/plugin-sdk.md#trust-model), exercised concretely rather than only
documented. Confirms behavior matches exactly what is documented - not
better (no accidental sandboxing that would silently break a legitimate
plugin's normal filesystem/environment access) and not worse (no
accidental extra permission or automated vetting beyond "runs as the
backend process itself, discovered through the ordinary
duplicate/compatibility checks every other plugin goes through").
"""
import os
from types import SimpleNamespace

from app.plugins.connector_instance import ConnectorInstance
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, ConnectorHealth, ConnectorState, PluginDescriptor, PluginType


class _MaliciousLookingButHarmlessPlugin:
    """Does everything the documented trust model explicitly permits
    ("filesystem, network, environment variables, everything") - reads
    an OS environment variable directly (bypassing the `*_env` convention
    entirely, which is a connector-config-layer convenience, never an
    enforced boundary - see secrets.py's own docstring) and writes a
    file. Harmless here: the env var and file are both test-local and
    contain no real secret or meaningful data. Proves the trust model is
    exactly as documented - MultiSens does not intercept, block, or
    sandbox any of this."""
    def __init__(self, tmp_path):
        self._tmp_path = tmp_path
        self._state = ConnectorState.STOPPED
        self.env_value_read: str | None = None
        self.file_written = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.sensor.malicious-looking', name='Malicious-looking (harmless) test plugin',
            version='1.0.0', plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )

    def configure(self, sensor_id: str, config: dict) -> None:
        self.env_value_read = os.environ.get('MULTISENS_TEST_TRUST_MODEL_PROBE')
        (self._tmp_path / 'plugin-wrote-this.txt').write_text('harmless proof-of-full-filesystem-access')
        self.file_written = True

    def start(self) -> None:
        self._state = ConnectorState.RUNNING

    def stop(self) -> None:
        self._state = ConnectorState.STOPPED

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=self._state)

    def sample(self):
        return None


def test_trusted_plugin_reads_environment_variables_directly_no_sandboxing(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_TEST_TRUST_MODEL_PROBE', 'read-directly-not-via-the-_env-convention')
    plugin = _MaliciousLookingButHarmlessPlugin(tmp_path)
    instance = ConnectorInstance('test_sensor', 'acme.sensor.malicious-looking', plugin)
    instance.configure({})  # must not raise, must not be intercepted
    assert plugin.env_value_read == 'read-directly-not-via-the-_env-convention'


def test_trusted_plugin_writes_to_the_filesystem_no_sandboxing(tmp_path):
    plugin = _MaliciousLookingButHarmlessPlugin(tmp_path)
    instance = ConnectorInstance('test_sensor', 'acme.sensor.malicious-looking', plugin)
    instance.configure({})
    assert plugin.file_written is True
    assert (tmp_path / 'plugin-wrote-this.txt').read_text() == 'harmless proof-of-full-filesystem-access'


def test_trusted_plugin_registers_through_the_ordinary_path_no_extra_or_reduced_scrutiny(tmp_path):
    # Not better, not worse: this plugin goes through the exact same
    # discovery checks (duplicate plugin_id, API-version compatibility)
    # as any other plugin - no "does this look malicious" scanning
    # exists anywhere in discover_plugins(), matching the trust model's
    # own "only install plugins you trust" framing rather than
    # implying automated vetting that was never built.
    plugin = _MaliciousLookingButHarmlessPlugin(tmp_path)
    entry_point = SimpleNamespace(
        name='acme.sensor.malicious-looking', load=lambda: plugin,
        dist=SimpleNamespace(name='acme-pkg', version='1.0.0'),
    )
    registry = discover_plugins(entry_points=[entry_point])
    record = registry.get('acme.sensor.malicious-looking')
    assert record.status == PluginStatus.AVAILABLE
    assert record.error is None
