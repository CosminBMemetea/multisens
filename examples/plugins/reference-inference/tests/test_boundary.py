"""The actual clean-room test (mirrors
examples/plugins/environment-sensor/tests/test_boundary.py exactly):
this plugin's own source files must import nothing from
`backend.app`/`frontend`/`ros2_ws` internals - only `multisens_sdk` and
the standard library. AST-based, same approach
`backend/tests/test_sdk_boundary.py` uses for `multisens_sdk` itself.
"""
import ast
import importlib.util
from pathlib import Path

FORBIDDEN_TOP_LEVEL_IMPORTS = ('app', 'backend', 'frontend', 'ros2_ws')


def _package_dir() -> Path:
    spec = importlib.util.find_spec('multisens_reference_inference')
    assert spec is not None and spec.submodule_search_locations, \
        'multisens_reference_inference is not importable - install it first (see README.md)'
    return Path(next(iter(spec.submodule_search_locations)))


def _imported_top_level_names(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split('.')[0])
    return names


def test_plugin_source_files_import_nothing_from_multisens_internals():
    package_dir = _package_dir()
    py_files = sorted(package_dir.rglob('*.py'))
    assert py_files, f'no .py files found under {package_dir} - the search path itself is broken'
    for py_file in py_files:
        forbidden = _imported_top_level_names(py_file) & set(FORBIDDEN_TOP_LEVEL_IMPORTS)
        assert not forbidden, f'{py_file} imports forbidden module(s): {forbidden}'


def test_plugin_only_depends_on_multisens_sdk_and_stdlib():
    package_dir = _package_dir()
    allowed_stdlib = {
        'json', 'time', 'urllib', 'typing', '__future__', 'multisens_sdk',
    }
    for py_file in sorted(package_dir.rglob('*.py')):
        imported = _imported_top_level_names(py_file)
        unexpected = imported - allowed_stdlib
        assert not unexpected, f'{py_file} imports unexpected module(s) beyond multisens_sdk/stdlib: {unexpected}'
