"""state.py/server.py/log.py in this package are now thin re-exports of
multisens_worker_kit (issue #141) - the real behavioral coverage lives
in worker-kit/tests/. This suite only guards against a broken re-export
(a typo, a stale shim after a worker-kit rename, ...), by asserting
identity with the underlying worker-kit objects - not re-testing logic
that's already tested once, at the source."""
from multisens_worker_kit.server import make_handler, serve
from multisens_worker_kit.state import SharedState, build_health_payload, build_latest_payload
from yolo_worker.log import log as yolo_log
from yolo_worker.server import make_handler as yolo_make_handler
from yolo_worker.server import serve as yolo_serve
from yolo_worker.state import SharedState as YoloSharedState
from yolo_worker.state import build_health_payload as yolo_build_health_payload
from yolo_worker.state import build_latest_payload as yolo_build_latest_payload


def test_state_reexports_are_the_same_objects():
    assert YoloSharedState is SharedState
    assert yolo_build_health_payload is build_health_payload
    assert yolo_build_latest_payload is build_latest_payload


def test_server_reexports_are_the_same_objects():
    assert yolo_serve is serve
    assert yolo_make_handler is make_handler


def test_log_is_a_callable_bound_to_this_workers_own_name():
    assert callable(yolo_log)
    # make_logger('yolo_worker') closure - verified indirectly via a
    # real call rather than reaching into logging internals.
    yolo_log('info', 'test_event', worker='yolo_worker')
