"""Phase 64-65: resource-observation domain shapes, validation, and
persistence. Phase 64 locked in the reviewed shape (issue #65); Phase 65
(issue #66) adds validation and persistence.
"""
import typing
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domain.models import Scenario, Session
from app.domain.resources import (
    SUPPORTED_RESOURCE_METRICS,
    UNKNOWN_PLATFORM_ID,
    ExecutionPlatform,
    ResourceObservation,
    ResourceQuality,
)
from app.persistence import db as db_module
from app.persistence import repository as repo


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


# --- Phase 65: cross-field validation ---------------------------------------

def test_unavailable_quality_rejects_a_real_value():
    with pytest.raises(ValidationError, match='must be None'):
        _observation(quality='unavailable', value=1.0)


def test_measured_quality_rejects_a_missing_value():
    with pytest.raises(ValidationError, match='must not be None'):
        _observation(quality='measured', value=None)


@pytest.mark.parametrize('field', ['unit', 'source', 'platform_id'])
def test_empty_identity_fields_are_rejected(field):
    with pytest.raises(ValidationError, match='must not be empty'):
        _observation(**{field: '   '})


def test_sample_count_below_one_is_rejected():
    with pytest.raises(ValidationError, match='sample_count'):
        _observation(sample_count=0)


def test_started_at_after_ended_at_is_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match='started_at'):
        _observation(started_at=now, ended_at=now - timedelta(seconds=1))


def test_started_at_equal_ended_at_is_allowed():
    # An instantaneous/point sample is a valid window, not an error.
    now = datetime.now(timezone.utc)
    obs = _observation(started_at=now, ended_at=now)
    assert obs.started_at == obs.ended_at


# --- Phase 65: persistence ---------------------------------------------------

def _seed_scenario_and_session(conn, session_id='s1') -> None:
    repo.create_scenario(conn, Scenario(id='sc1', name='demo scenario'))
    repo.create_session(conn, Session(
        id=session_id, name='demo session', scenario_id='sc1', started_at=datetime.now(timezone.utc),
    ))


def test_resource_observations_round_trip_byte_identical(tmp_path):
    conn = db_module.connect(str(tmp_path / 'test.db'))
    _seed_scenario_and_session(conn)

    written = [
        _observation(id='obs-1', session_id='s1', metric='cpu_percent', value=31.2, quality='measured'),
        _observation(
            id='obs-2', session_id='s1', metric='network_receive_mbps', value=None,
            quality='unavailable', configuration_id=None,
        ),
    ]
    repo.insert_resource_observations_batch(conn, written)

    read_back = repo.list_resource_observations(conn, session_id='s1')
    assert len(read_back) == 2
    by_id = {o.id: o for o in read_back}
    for original in written:
        assert by_id[original.id] == original


def test_list_resource_observations_filters_by_configuration_and_metric(tmp_path):
    conn = db_module.connect(str(tmp_path / 'test.db'))
    _seed_scenario_and_session(conn)
    repo.insert_resource_observations_batch(conn, [
        _observation(id='obs-front', session_id='s1', configuration_id='cfg-front', metric='cpu_percent'),
        _observation(id='obs-rear', session_id='s1', configuration_id='cfg-rear', metric='cpu_percent'),
        _observation(id='obs-front-net', session_id='s1', configuration_id='cfg-front', metric='memory_mb'),
    ])

    front_only = repo.list_resource_observations(conn, session_id='s1', configuration_id='cfg-front')
    assert {o.id for o in front_only} == {'obs-front', 'obs-front-net'}

    cpu_only = repo.list_resource_observations(conn, session_id='s1', metric='cpu_percent')
    assert {o.id for o in cpu_only} == {'obs-front', 'obs-rear'}

    both = repo.list_resource_observations(conn, session_id='s1', configuration_id='cfg-front', metric='cpu_percent')
    assert {o.id for o in both} == {'obs-front'}


def test_resource_observation_with_null_configuration_id_round_trips(tmp_path):
    conn = db_module.connect(str(tmp_path / 'test.db'))
    _seed_scenario_and_session(conn)
    repo.insert_resource_observations_batch(conn, [
        _observation(id='obs-unattributed', session_id='s1', configuration_id=None),
    ])
    read_back = repo.list_resource_observations(conn, session_id='s1')
    assert read_back[0].configuration_id is None
