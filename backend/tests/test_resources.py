"""Phase 64: resource-observation domain shapes. Locks in the reviewed
design (issue #65) so later phases (65-70) build against an
already-agreed shape - no algorithm/validation logic exists yet, only
field presence, types, and the documented constants.
"""
import typing
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.resources import (
    SUPPORTED_RESOURCE_METRICS,
    UNKNOWN_PLATFORM_ID,
    ExecutionPlatform,
    ResourceObservation,
    ResourceQuality,
)


def _observation(**overrides) -> ResourceObservation:
    defaults = dict(
        id='obs-1', session_id='s1', configuration_id='cfg-a', metric='cpu_percent',
        value=31.2, unit='%', quality='measured', source='psutil.cpu_percent',
        platform_id='macbook-m2-dockerdesktop',
        started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
    )
    return ResourceObservation(**{**defaults, **overrides})


# --- ResourceQuality / SUPPORTED_RESOURCE_METRICS ---------------------------

def test_resource_quality_has_exactly_four_values():
    assert set(typing.get_args(ResourceQuality)) == {'measured', 'declared', 'estimated', 'unavailable'}


def test_supported_resource_metrics_is_exactly_the_reviewed_six():
    assert SUPPORTED_RESOURCE_METRICS == {
        'cpu_percent': '%',
        'memory_mb': 'MB',
        'network_receive_mbps': 'Mbps',
        'network_transmit_mbps': 'Mbps',
        'fps': 'fps',
        'pipeline_latency_ms': 'ms',
    }


def test_supported_resource_metrics_excludes_deferred_metrics():
    # GPU/power/temperature/storage-write are deliberately not in v0.7's
    # scope (architecture review, "what I would remove") - no trustworthy
    # source exists in the current dev environment.
    deferred = {'gpu_percent', 'gpu_memory_mb', 'power_w', 'temperature_c', 'storage_write_mbps'}
    assert deferred.isdisjoint(SUPPORTED_RESOURCE_METRICS)


# --- ResourceObservation shape ----------------------------------------------

def test_resource_observation_round_trips_all_fields():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ended = datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc)
    obs = ResourceObservation(
        id='obs-1', session_id='s1', configuration_id='cfg-front-rear', metric='network_receive_mbps',
        value=9.7, unit='Mbps', quality='measured', source='psutil.net_io_counters',
        platform_id='macbook-m2-dockerdesktop', started_at=started, ended_at=ended,
        sample_count=5, metadata={'resolution': '640x480', 'target_fps': 30},
    )
    assert obs.id == 'obs-1'
    assert obs.session_id == 's1'
    assert obs.configuration_id == 'cfg-front-rear'
    assert obs.metric == 'network_receive_mbps'
    assert obs.value == 9.7
    assert obs.unit == 'Mbps'
    assert obs.quality == 'measured'
    assert obs.source == 'psutil.net_io_counters'
    assert obs.platform_id == 'macbook-m2-dockerdesktop'
    assert obs.started_at == started
    assert obs.ended_at == ended
    assert obs.sample_count == 5
    assert obs.metadata == {'resolution': '640x480', 'target_fps': 30}


def test_resource_observation_defaults():
    obs = ResourceObservation(
        id='obs-1', session_id='s1', metric='cpu_percent', value=None, unit='%',
        quality='unavailable', source='psutil.cpu_percent', platform_id=UNKNOWN_PLATFORM_ID,
        started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
    )
    assert obs.configuration_id is None
    assert obs.sample_count == 1
    assert obs.metadata == {}


def test_resource_observation_value_none_is_distinct_from_zero():
    # Both must be constructible and distinguishable - None means "no
    # value," 0.0 means "measured, and the answer was zero." Phase 65
    # enforces value is None iff quality == 'unavailable'; this phase
    # only proves the shape can represent both without collapsing them.
    zero = _observation(value=0.0, quality='measured')
    missing = _observation(value=None, quality='unavailable')
    assert zero.value == 0.0
    assert zero.value is not None
    assert missing.value is None


def test_resource_observation_metric_is_an_open_string_not_a_closed_enum():
    # Same open-vocabulary posture as AcceptanceCriterion.metric - the
    # domain shape itself doesn't restrict to SUPPORTED_RESOURCE_METRICS;
    # that validation belongs to the API boundary (Phase 70), not here.
    obs = _observation(metric='some_future_metric_not_in_the_supported_set')
    assert obs.metric == 'some_future_metric_not_in_the_supported_set'


def test_resource_observation_requires_metric():
    with pytest.raises(ValidationError):
        ResourceObservation(
            id='obs-1', session_id='s1', value=1.0, unit='%', quality='measured',
            source='x', platform_id='x', started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )


# --- ExecutionPlatform shape ------------------------------------------------

def test_execution_platform_round_trips_all_fields():
    platform = ExecutionPlatform(
        id='jetson-orin-ubuntu', display_name='Jetson Orin, Ubuntu', architecture='arm64',
        os='Ubuntu 22.04', metadata={'runtime': 'Docker', 'ros_distro': 'humble'},
    )
    assert platform.id == 'jetson-orin-ubuntu'
    assert platform.display_name == 'Jetson Orin, Ubuntu'
    assert platform.architecture == 'arm64'
    assert platform.os == 'Ubuntu 22.04'
    assert platform.metadata == {'runtime': 'Docker', 'ros_distro': 'humble'}


def test_execution_platform_metadata_defaults_to_empty_dict():
    platform = ExecutionPlatform(id='x', display_name='X', architecture='arm64', os='Linux')
    assert platform.metadata == {}


def test_unknown_platform_id_is_a_stable_named_constant():
    assert UNKNOWN_PLATFORM_ID == 'unknown'
