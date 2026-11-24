"""Prerequisites from optional development tools or historical release bundles."""
import importlib.util
from pathlib import Path
from unittest import SkipTest


def optional_file(path):
    location = Path(__file__).resolve().parents[1] / path
    if not location.exists():
        raise SkipTest(f'Optional test input not installed: {path}')
    return location


def load_optional_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, optional_file(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
