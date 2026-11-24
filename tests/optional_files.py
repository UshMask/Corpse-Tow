"""Prerequisites from the private development tools or published release bundles."""
from pathlib import Path
from unittest import SkipTest


def optional_file(path):
    location = Path(__file__).resolve().parents[1] / path
    if not location.exists():
        raise SkipTest(f'Optional test input not installed: {path}')
    return location
