"""Deterministic Lua/Python regression set for GitHub Actions.

Runs only tests that use the real modules with the isolated lupa Lua 5.1 fixture.
It does not launch Project Zomboid, the Java bridge or a network, so native
validators remain a separate local release check.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = (
    'test_link_graph',
    'test_graph_deletion',
    'test_link_service',
    'test_shared_rope',
    'test_equipment',
    'test_save_jobs',
    'test_mp_budget',
    'test_link_multiplayer',
    'test_link_performance',
    'test_diagnostics',
    'test_diagnostics_bench',
)


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
