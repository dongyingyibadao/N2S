import importlib.util
import re
from pathlib import Path


class PluginError(RuntimeError):
    pass


def load_plugin(path, required_functions):
    path = Path(path).resolve()
    module_name = "n2s_rule_" + re.sub(r"[^a-zA-Z0-9_]", "_", str(path))
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot load plugin: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise PluginError(f"failed to import plugin {path}: {error}") from error
    missing = [name for name in required_functions if not callable(getattr(module, name, None))]
    if missing:
        raise PluginError(f"plugin {path} is missing callables: {', '.join(missing)}")
    return module


def load_rule_plugins(package, manifest):
    automation = manifest["automation"]
    return {
        "detector": load_plugin(package / automation["detector"], ["detect"]),
        "codemod": load_plugin(package / automation["codemod"], ["transform"]),
        "validator": load_plugin(package / automation["validator"], ["validate_before", "validate_after"]),
    }
