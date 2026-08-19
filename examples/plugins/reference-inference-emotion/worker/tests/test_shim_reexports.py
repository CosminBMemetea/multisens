"""state.py/server.py/log.py in this package are now thin re-exports of
multisens_worker_kit (issue #141) - the real behavioral coverage lives
in worker-kit/tests/. This suite only guards against a broken re-export
(a typo, a stale shim after a worker-kit rename, ...), by asserting
identity with the underlying worker-kit objects - not re-testing logic
that's already tested once, at the source."""
from emotion_worker.log import log as emotion_log
from emotion_worker.server import make_handler as emotion_make_handler
from emotion_worker.server import serve as emotion_serve
from emotion_worker.state import SharedState as EmotionSharedState
from emotion_worker.state import build_health_payload as emotion_build_health_payload
from emotion_worker.state import build_latest_payload as emotion_build_latest_payload
from multisens_worker_kit.server import make_handler, serve
from multisens_worker_kit.state import SharedState, build_health_payload, build_latest_payload


def test_state_reexports_are_the_same_objects():
    assert EmotionSharedState is SharedState
    assert emotion_build_health_payload is build_health_payload
    assert emotion_build_latest_payload is build_latest_payload


def test_server_reexports_are_the_same_objects():
    assert emotion_serve is serve
    assert emotion_make_handler is make_handler


def test_log_is_a_callable_bound_to_this_workers_own_name():
    assert callable(emotion_log)
    # make_logger('emotion_worker') closure - verified indirectly via a
    # real call rather than reaching into logging internals.
    emotion_log('info', 'test_event', worker='emotion_worker')
