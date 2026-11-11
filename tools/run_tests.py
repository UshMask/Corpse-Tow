"""Daily behavior checks; --full also runs the long motion matrices."""
import argparse
from pathlib import Path
import sys
import unittest


# Keep item, persistence, cancellation and SP/MP contracts in the daily suite.
FULL_ONLY = {
    'test_contact_resistance.ContactResistanceTests.test_current_dense_chains_load_only_through_taut_ropes',
    'test_contact_resistance.ContactResistanceTests.test_independent_and_mixed_groups_retain_full_steady_load',
    'test_contact_resistance.ContactResistanceTests.test_load_change_does_not_change_poses_at_turn_reverse_or_variable_steps',
    'test_link_obstacles.LinkObstacleTests.test_one_eight_thirty_two_bodies_pause_at_varied_tick_rates',
}


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    discovered = list(cases(unittest.defaultTestLoader.discover(str(root / 'tests'))))
    missing = FULL_ONLY - {test.id() for test in discovered}
    if missing:
        parser.error('Update stale full-only test IDs: ' + ', '.join(sorted(missing)))
    selected = [test for test in discovered if args.full or test.id() not in FULL_ONLY]
    print(f"Scope: {'full' if args.full else 'quick'}; selected {len(selected)}/{len(discovered)} tests", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
