"""Phase 93 (v0.9): the SDK boundary test. `multisens_sdk` is supposed to
be importable and usable by an external plugin without ever reaching into
MultiSens internals - this walks every module actually shipped in the
installed `multisens_sdk` package and asserts none of them import
`app`/`backend`/`frontend`/`ros2_ws`. AST-based (parses import statements
without a second execution pass), so this works identically whether
`multisens_sdk` was installed as a regular package (the Docker image, see
backend/Dockerfile) or via `PYTHONPATH` against a live `sdk/` checkout
(local dev iteration).

The second half proves this was a *relocation*, not a duplicate: every
backend re-export (`app.domain.models.GroundTruth`, ...) must be the
literal same class object as its `multisens_sdk` counterpart, never two
independently-defined shapes that could silently drift apart.
"""
import ast
import importlib.util
from pathlib import Path

FORBIDDEN_TOP_LEVEL_IMPORTS = ('app', 'backend', 'frontend', 'ros2_ws')


def _sdk_package_dir() -> Path:
    spec = importlib.util.find_spec('multisens_sdk')
    assert spec is not None and spec.submodule_search_locations, 'multisens_sdk is not importable'
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


def test_multisens_sdk_is_importable():
    import multisens_sdk  # noqa: F401


def test_multisens_sdk_source_files_import_nothing_backend_internal():
    sdk_dir = _sdk_package_dir()
    py_files = sorted(sdk_dir.rglob('*.py'))
    assert py_files, f'no .py files found under {sdk_dir} - the search path itself is broken'
    for py_file in py_files:
        forbidden = _imported_top_level_names(py_file) & set(FORBIDDEN_TOP_LEVEL_IMPORTS)
        assert not forbidden, f'{py_file} imports forbidden module(s): {forbidden}'


def test_public_api_surface_matches_documented_names():
    # docs/plugin-sdk.md's own __init__.py docstring lists the exact
    # public surface a plugin author is meant to import - this pins it
    # down so a future phase can't silently narrow or rename it.
    import multisens_sdk
    expected = {
        'MULTISENS_PLUGIN_API_VERSION', 'PluginType', 'PluginDescriptor', 'PluginError',
        'ConnectorConfigError', 'ConnectorState', 'ConnectorHealth', 'SensorSample',
        'GroundTruth', 'Prediction', 'EvaluationResult', 'ResourceObservation', 'ResourceQuality',
        'MetricValue', 'MatchResult', 'MatchedPair', 'EvaluatorOutput', 'EvaluatorPlugin',
        'MetricDescriptor', 'SensorConnector', 'PredictionConnector', 'GroundTruthConnector',
        'ResourceCollector', 'ResourceMetricDescriptor',
    }
    assert set(multisens_sdk.__all__) == expected
    for name in expected:
        assert hasattr(multisens_sdk, name), f'multisens_sdk.{name} is declared in __all__ but not importable'


def test_backend_reexports_are_the_same_objects_not_copies():
    from app.domain.evaluator_output import Evaluator, EvaluatorOutput
    from app.domain.matching import MatchedPair, MatchResult
    from app.domain.models import EvaluationResult, GroundTruth, Prediction
    from app.domain.resources import ResourceObservation
    from multisens_sdk.evaluators import EvaluatorOutput as SdkEvaluatorOutput
    from multisens_sdk.evaluators import EvaluatorPlugin as SdkEvaluatorPlugin
    from multisens_sdk.matching import MatchedPair as SdkMatchedPair
    from multisens_sdk.matching import MatchResult as SdkMatchResult
    from multisens_sdk.models import EvaluationResult as SdkEvaluationResult
    from multisens_sdk.models import GroundTruth as SdkGroundTruth
    from multisens_sdk.models import Prediction as SdkPrediction
    from multisens_sdk.models import ResourceObservation as SdkResourceObservation

    assert GroundTruth is SdkGroundTruth
    assert Prediction is SdkPrediction
    assert EvaluationResult is SdkEvaluationResult
    assert ResourceObservation is SdkResourceObservation
    assert MatchedPair is SdkMatchedPair
    assert MatchResult is SdkMatchResult
    assert Evaluator is SdkEvaluatorPlugin
    assert EvaluatorOutput is SdkEvaluatorOutput


def test_derive_configuration_id_is_the_same_function_not_a_copy():
    from app.domain.models import derive_configuration_id
    from multisens_sdk.models import derive_configuration_id as sdk_derive_configuration_id
    assert derive_configuration_id is sdk_derive_configuration_id
