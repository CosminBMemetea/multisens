"""Pure decision logic for synchronization status - no rclpy/message_filters/
diagnostic_msgs import, on purpose, so this is testable with plain pytest
and no live ROS environment. sync_status_node.py computes the watchdog/group
state (which genuinely does need live subscriptions) and hands it to
compute_sync_status(), then marshals the plain result into a
diagnostic_msgs/DiagnosticStatus - that marshaling is the only ROS-specific
part left in the node.
"""
from typing import Optional


def compute_sync_status(
    modalities: list[str],
    missing: list[str],
    stale: list[str],
    group_is_fresh: bool,
    max_skew_ms: Optional[float],
    offsets_ms: dict[str, float],
    tolerance_ms: float,
    group_rate_hz: float,
    stale_after_sec: float,
) -> dict:
    """Returns {'level': 'ok'|'warn'|'error', 'message': str, 'fields': dict}
    - 'fields' is the exact set of KeyValue entries the node publishes."""
    fields = {
        'tolerance_ms': f'{tolerance_ms:.1f}',
        'synchronized_group_rate_hz': f'{group_rate_hz:.1f}',
        'missing_sensors': ','.join(missing) if missing else 'none',
        'stale_sensors': ','.join(stale) if stale else 'none',
    }

    within_tolerance = False
    if group_is_fresh:
        within_tolerance = max_skew_ms <= tolerance_ms
        fields['max_skew_ms'] = f'{max_skew_ms:.1f}'
        for modality in modalities:
            offset = offsets_ms.get(modality)
            fields[f'offset_ms_{modality}'] = f'{offset:.1f}' if offset is not None else 'unavailable'
    else:
        fields['max_skew_ms'] = 'unavailable'
        for modality in modalities:
            fields[f'offset_ms_{modality}'] = 'unavailable'

    if not group_is_fresh:
        level = 'error'
        message = f'no synchronized group in last {stale_after_sec:.0f}s (missing: {missing or "none"})'
    elif missing:
        level = 'error'
        message = f'missing sensors: {missing}'
    elif stale or not within_tolerance:
        level = 'warn'
        message = f'stale: {stale or "none"}, within_tolerance={within_tolerance}'
    else:
        level = 'ok'
        message = f'synchronized within {tolerance_ms:.0f}ms tolerance'

    return {'level': level, 'message': message, 'fields': fields}
