# multisens-sdk

Stable, plugin-facing contracts for [MultiSens](https://github.com/CosminBMemetea/multisens)
external integrations. Imports nothing from MultiSens core (`backend.app.*`,
`frontend`, `ros2_ws` internals) - verified by a dedicated import-boundary
test in the main repository's own backend test suite.

Full architecture, plugin taxonomy, trust model, and contract reference:
[`docs/plugin-sdk.md`](https://github.com/CosminBMemetea/multisens/blob/main/docs/plugin-sdk.md)
in the main repository.

This package is versioned independently of the MultiSens application
release. Plugin/host compatibility is governed by `MULTISENS_PLUGIN_API_VERSION`
(`multisens_sdk.MULTISENS_PLUGIN_API_VERSION`), not by this package's own
version number or MultiSens's own `0.x` release number.
