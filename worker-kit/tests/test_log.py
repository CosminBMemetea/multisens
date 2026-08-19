"""New coverage (issue #141) - log.py itself had no dedicated test in
either reference worker before this extraction; only exercised
incidentally through worker CLI usage. `make_logger` is the one piece
of behavior that actually changed shape during extraction (a factory
instead of one hardcoded module-level logger), so it gets direct tests."""
import logging

from multisens_worker_kit.log import make_logger


def test_make_logger_returns_a_callable_bound_to_the_given_name(caplog):
    log = make_logger('test_worker_a')
    with caplog.at_level(logging.INFO, logger='test_worker_a'):
        log('info', 'startup', sensor_id='rgb')
    assert len(caplog.records) == 1
    assert caplog.records[0].name == 'test_worker_a'
    assert "event=startup sensor_id='rgb'" in caplog.records[0].message


def test_two_loggers_have_independent_rate_limit_state(caplog):
    log_a = make_logger('test_worker_b')
    log_b = make_logger('test_worker_c')
    with caplog.at_level(logging.INFO):
        log_a('info', 'reconnecting', rate_limit_s=60.0)
        log_a('info', 'reconnecting', rate_limit_s=60.0)  # suppressed - same logger, same event, within window
        log_b('info', 'reconnecting', rate_limit_s=60.0)  # not suppressed - independent logger's own rate-limit state
    messages = [r.message for r in caplog.records]
    assert messages.count('event=reconnecting ') == 2


def test_rate_limit_zero_never_suppresses(caplog):
    log = make_logger('test_worker_d')
    with caplog.at_level(logging.INFO, logger='test_worker_d'):
        log('info', 'tick')
        log('info', 'tick')
    assert len(caplog.records) == 2
