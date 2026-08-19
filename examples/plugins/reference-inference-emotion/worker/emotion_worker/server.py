"""Thin re-export of the shared worker-side toolkit (multisens_worker_kit,
issue #141) - see state.py's own docstring in this package for why."""
from multisens_worker_kit.server import make_handler, serve

__all__ = ['make_handler', 'serve']
