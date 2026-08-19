"""Thin re-export of the shared worker-side toolkit (multisens_worker_kit,
issue #141) - see state.py's own docstring in this package for why.
`log` stays a plain module-level callable (not the factory itself), so
every existing `from emotion_worker.log import log` call site - and its
`log('info', 'startup', ...)` call shape - is completely unaffected."""
from multisens_worker_kit.log import make_logger

log = make_logger('emotion_worker')

__all__ = ['log']
