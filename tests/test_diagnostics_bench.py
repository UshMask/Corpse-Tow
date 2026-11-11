"""Tests for the offline diagnostics bench measurement protocol.

These tests execute the real runners on tiny scenarios; they do not just inspect
dictionaries. They lock in:
* one repetition key (`repeats`) and the actual executed repeat count;
* batch means vs real per-tick percentile samples (histogram fed by raw samples);
* the timer path not changing simulation results, plus measured timer overhead;
* fresh-fixture-per-repeat determinism (checkpoint hashes across repeats);
* backend/expected-work rejection;
* interleaved MP measurement with delivery included, freshness, updated bodies
  and active presentation paths, including the labelled state-loss variant;
* JSON schema v2 and the bench SHA-256 in the output document.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
TESTS = ROOT / 'tests'
for path in (str(TOOLS), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import diagnostics_bench as bench


def tiny_scenario(**overrides):
    scenario = bench._scenario(
        'test.tiny', 'authority', 'tiny protocol self-check', 'self-check',
        build=bench.chain_scene(4), frame=bench.STRAIGHT_FRAME, warmup=3, repeats=5,
        frames=3, expected_work=bench.work(4, 4, 1), expect_motion=True,
        validation_frames=3)
    scenario['profile_frames'] = 0
    scenario.update(overrides)
    return scenario


def tiny_mp_scenario(variant='live', kind=None, **overrides):
    scenario = dict(
        id='test.mp.' + variant, mode='mp', kind=kind or ('mp-' + variant),
        variant=variant, description='tiny MP protocol self-check',
        warmup=2, repeats=2, frames=3, expected_work=bench.work(8, 8, 1), dtMs=100,
        validation_frames=4, profile_frames=0)
    scenario.update(overrides)
    return scenario


_CACHE = {}


def tiny_result():
    """Run the tiny SP scenario once and reuse it across read-only assertions."""
    if 'result' not in _CACHE:
        _CACHE['result'] = bench.run_authority_scenario(
            tiny_scenario(), True, False, expected_backend=bench.DEFAULT_EXPECTED_BACKEND)
    return _CACHE['result']


class DiagnosticBenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    # ------------------------------------------------------------------
    # 1. Unified repetition key.
    # ------------------------------------------------------------------
    def test_scenario_list_uses_one_repeats_key_and_covers_the_scaling_matrix(self):
        scenarios = bench.scenario_list(True)
        self.assertTrue(scenarios)
        for scenario in scenarios:
            self.assertIn('repeats', scenario, scenario['id'])
            self.assertNotIn('reps', scenario, scenario['id'])
            self.assertIsInstance(scenario['repeats'], int)
            self.assertGreaterEqual(scenario['repeats'], 1)
            self.assertIn('warmup', scenario)
            self.assertIn('frames', scenario)
            self.assertIn('expected_work', scenario)
            self.assertIn('dtMs', scenario)
        by_id = {scenario['id']: scenario for scenario in scenarios}
        for scenario_id in ('scale.chains.1x32', 'scale.chains.2x32', 'scale.chains.4x32'):
            self.assertEqual(by_id[scenario_id]['kind'], 'controlled-scaling')
        self.assertEqual(by_id['scale.chains.1x32']['expected_work']['bodies'], 32)
        self.assertEqual(by_id['scale.chains.2x32']['expected_work']['bodies'], 64)
        self.assertEqual(by_id['scale.chains.4x32']['expected_work']['bodies'], 128)
        self.assertEqual(by_id['bodies.32.individual']['kind'], 'scaling-comparison')
        self.assertEqual(by_id['bodies.32.chain']['kind'], 'scaling-comparison')
        for scenario_id in ('bodies.32.chain.turn', 'bodies.32.chain.brake',
                            'bodies.32.chain.backwards', 'bodies.32.chain.obstacle',
                            'bodies.128.groups4', 'bodies.128.groups4.turn'):
            self.assertEqual(by_id[scenario_id]['kind'], 'stress', scenario_id)
        self.assertEqual(by_id['mp.live.2clients.8']['kind'], 'mp-live')
        self.assertEqual(by_id['mp.idle.2clients.8']['kind'], 'mp-idle')
        self.assertEqual(by_id['mp.loss.2clients.8']['kind'], 'mp-loss')
        self.assertEqual(by_id['smoke.tiny']['kind'], 'self-check')

    def test_scenario_repeats_helper_rejects_missing_or_invalid_values(self):
        self.assertEqual(bench.scenario_repeats({'id': 'x', 'repeats': 4}), 4)
        for bad in ({}, {'repeats': 0}, {'repeats': -1}, {'repeats': '3'},
                    {'repeats': True}, {'reps': 3}):
            with self.assertRaises(ValueError):
                bench.scenario_repeats(dict(bad, id='bad'))

    def test_runner_executes_the_unified_repeat_count(self):
        result = tiny_result()
        self.assertEqual(result['executedRepeats'], 5)
        self.assertEqual(result['batchMeanMs']['count'], 5)
        self.assertEqual(len(result['batchMeanMs']['values']), 5)
        self.assertEqual(result['tickMs']['count'], 5 * 3)
        self.assertEqual(len(result['tickMs']['perRepeat']), 5)
        for row in result['tickMs']['perRepeat']:
            self.assertEqual(row['count'], 3)

    # ------------------------------------------------------------------
    # 2. Batch means vs real per-tick percentiles.
    # ------------------------------------------------------------------
    def test_tick_percentiles_are_fed_by_raw_per_tick_samples(self):
        result = tiny_result()
        batch = result['batchMeanMs']
        tick = result['tickMs']
        self.assertEqual(batch['kind'], 'batch-mean')
        self.assertEqual(tick['kind'], 'per-tick')
        self.assertIn('raw per-frame', tick['source'])
        self.assertEqual(tick['timerCallsPerSample'], 1)
        # Per-tick count must be repeats*frames, not one mean per repeat.
        self.assertEqual(tick['count'], result['executedRepeats'] * result['measuredFramesPerRepeat'])
        self.assertGreater(tick['count'], batch['count'])
        # The histogram must account for every raw sample.
        histogram = tick['histogram']
        self.assertIsNotNone(histogram)
        self.assertEqual(sum(histogram['counts']), tick['count'])
        self.assertGreater(len(tick['samplesMs']), 0)
        self.assertLessEqual(len(tick['samplesMs']), tick['sampleLimit'])
        for key in ('min', 'p50', 'p95', 'p99', 'max', 'mean', 'stdDev'):
            self.assertIn(key, tick)
        self.assertGreaterEqual(tick['p95'], tick['p50'])
        self.assertGreaterEqual(tick['p99'], tick['p95'])
        for row in tick['perRepeat']:
            self.assertGreaterEqual(row['p95'], row['p50'])

    def test_tick_summary_uses_raw_samples_not_batch_means(self):
        tick = bench.summarize_ticks([1.0, 2.0, 3.0, 4.0, 100.0], [[1.0, 2.0], [3.0, 4.0, 100.0]])
        self.assertEqual(tick['kind'], 'per-tick')
        self.assertEqual(tick['count'], 5)
        self.assertEqual(tick['p50'], 3.0)
        self.assertEqual(tick['p95'], 100.0)
        self.assertEqual(tick['max'], 100.0)
        self.assertEqual(sum(tick['histogram']['counts']), 5)
        self.assertEqual([row['count'] for row in tick['perRepeat']], [2, 3])
        batch = bench.summarize_batch([10.0, 20.0, 30.0])
        self.assertEqual(batch['kind'], 'batch-mean')
        self.assertEqual(batch['count'], 3)
        self.assertEqual(batch['median'], 20.0)
        self.assertEqual(batch['values'], [10.0, 20.0, 30.0])

    def test_non_simulated_timer_overhead_is_measured(self):
        overhead = bench.measure_timer_overhead(True)
        self.assertIn('micro', overhead)
        micro = overhead['micro']
        self.assertGreater(micro['medianDeltaNsPerTick'], 0.0)
        self.assertLess(micro['medianDeltaNsPerTick'], 1e6, 'per-tick clock call must be sub-millisecond')
        clock = bench.clock_overhead(None)
        self.assertIsNone(clock)

    def test_timer_does_not_change_simulation_results(self):
        from test_link_runtime import environment
        scenario = tiny_scenario(repeats=2, frames=2, warmup=2, validation_frames=2)
        plain = environment()
        instrumented = environment()
        try:
            bench.prepare_sp(plain, scenario)
            bench.prepare_sp(instrumented, scenario)
            self.assertEqual(plain.eval('__benchCheckpoint()'), instrumented.eval('__benchCheckpoint()'))
            plain.eval('__benchPlainBatch(4)')
            instrumented.eval('__benchTickBatch(4)')
            self.assertEqual(plain.eval('__benchCheckpoint()'), instrumented.eval('__benchCheckpoint()'))
            self.assertEqual(bench.to_py(plain.eval('__benchStats()')),
                             bench.to_py(instrumented.eval('__benchStats()')))
        finally:
            del plain
            del instrumented

    # ------------------------------------------------------------------
    # 3. Deterministic independent repeats.
    # ------------------------------------------------------------------
    def test_fresh_fixture_per_repeat_gives_identical_checkpoints(self):
        from test_link_runtime import environment
        created = {'count': 0}

        def factory():
            created['count'] += 1
            return environment()

        scenario = tiny_scenario(repeats=3, frames=2, warmup=2, validation_frames=2)
        result = bench.run_authority_scenario(scenario, True, False,
                                              fixture_factory=factory,
                                              expected_backend=bench.DEFAULT_EXPECTED_BACKEND)
        self.assertEqual(result['executedRepeats'], 3)
        # 3 measured repeats + 1 validation fixture; profiling is disabled.
        self.assertEqual(created['count'], 4)
        determinism = result['determinism']
        self.assertIn('fresh', determinism['scheme'])
        self.assertTrue(determinism['warmupExcludedFromMeasurement'])
        self.assertTrue(determinism['identicalBefore'], determinism['checkpointBeforeHashes'])
        self.assertTrue(determinism['identicalAfter'], determinism['checkpointAfterHashes'])
        self.assertEqual(len(determinism['checkpointBeforeHashes']), 3)
        self.assertEqual(len(set(determinism['checkpointBeforeHashes'])), 1)
        self.assertEqual(len(set(determinism['checkpointAfterHashes'])), 1)
        self.assertTrue(result['validation']['ok'], [c for c in result['validation']['checks'] if not c['ok']])

    def test_expected_work_and_backend_mismatch_are_rejected(self):
        from test_link_runtime import environment
        determinism = {'identicalBefore': True, 'identicalAfter': True,
                       'checkpointBeforeHashes': [], 'checkpointAfterHashes': []}
        wrong_work = tiny_scenario(expected_work={'bodies': 4, 'links': 99, 'groups': 1, 'records': 4})
        validation = bench.validate_sp(wrong_work, True, environment,
                                       bench.DEFAULT_EXPECTED_BACKEND, determinism)
        self.assertFalse(validation['ok'])
        failed = {check['check'] for check in validation['checks'] if not check['ok']}
        self.assertIn('topology.links', failed)
        wrong_backend = bench.validate_sp(tiny_scenario(), True, environment,
                                          'java-persistent', determinism)
        self.assertFalse(wrong_backend['ok'])
        failed = {check['check'] for check in wrong_backend['checks'] if not check['ok']}
        self.assertIn('backend', failed)

    # ------------------------------------------------------------------
    # 4. Live interleaved MP measurement.
    # ------------------------------------------------------------------
    def test_mp_live_interleaves_ticks_and_delivery_and_stays_fresh(self):
        result = bench.run_mp_scenario(tiny_mp_scenario('live'), True, False,
                                       expected_backend=bench.DEFAULT_EXPECTED_BACKEND)
        self.assertEqual(result['executedRepeats'], 2)
        self.assertEqual(result['mode'], 'mp')
        self.assertEqual(len(result['roles']), 3)
        for role in result['roles']:
            self.assertEqual(role['ownTickMs']['count'], 2 * 3)
            self.assertIn('batchMeanMs', role)
        self.assertIn('delivery', result['setup'])
        self.assertGreater(result['delivery']['packets']['delivered'], 0)
        self.assertGreater(result['delivery']['serverToClients']['count'], 0)
        self.assertGreater(result['delivery']['clientsToServer']['count'], 0)
        validation = result['validation']
        self.assertTrue(validation['ok'], [c for c in validation['checks'] if not c['ok']])
        for role in ('owner', 'friend'):
            self.assertLessEqual(validation['freshnessMaxAgeMs'][role], 3000.0)
            self.assertGreater(validation['updatedBodies'][role], 0)
            self.assertGreater(validation['presentationFrames'][role], 0)
            probe = validation['clientStats'][role]
            self.assertGreater(probe['rows'], 0)
            self.assertEqual(probe['rows'], probe['resolvedRows'])
        self.assertTrue(result['determinism']['identicalBefore'])
        self.assertTrue(result['determinism']['identicalAfter'])

    def test_mp_loss_scenario_is_labelled_and_recovers(self):
        result = bench.run_mp_scenario(tiny_mp_scenario('loss'), True, False,
                                       expected_backend=bench.DEFAULT_EXPECTED_BACKEND)
        self.assertEqual(result['kind'], 'mp-loss')
        self.assertEqual(result['variant'], 'loss')
        self.assertGreater(result['delivery']['packets']['dropped'], 0)
        validation = result['validation']
        self.assertGreater(validation['droppedPackets'], 0)
        self.assertTrue(validation['ok'], [c for c in validation['checks'] if not c['ok']])
        for role in ('owner', 'friend'):
            self.assertLessEqual(validation['freshnessMaxAgeMs'][role], 3000.0)
            self.assertGreater(validation['updatedBodies'][role], 0)

    # ------------------------------------------------------------------
    # 5. JSON document and bench identity.
    # ------------------------------------------------------------------
    def test_cli_writes_schema_v2_with_bench_hash_and_unambiguous_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            status = bench.main(['--quick', '--no-mp', '--only', 'smoke.tiny',
                                 '--no-profile', '--phase', 'adhoc',
                                 '--output', directory])
            self.assertEqual(status, 0)
            document = json.loads((Path(directory) / 'raw.json').read_text(encoding='utf-8'))
        self.assertEqual(document['schema'], bench.SCHEMA)
        self.assertEqual(document['schemaVersion'], 2)
        expected_hash = hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest()
        self.assertEqual(document['bench']['sha256'], expected_hash)
        self.assertEqual(document['environment']['source']['bench']['sha256'], expected_hash)
        self.assertEqual(document['selfCheck']['failed'], 0)
        self.assertEqual(document['failures'], [])
        self.assertIn('lua-reference', document['backend']['observed'])
        scenarios = {scenario['id']: scenario for scenario in document['scenarios']}
        result = scenarios['smoke.tiny']
        self.assertEqual(result['executedRepeats'], 7)
        self.assertEqual(result['batchMeanMs']['count'], 7)
        self.assertEqual(result['tickMs']['count'], 7 * 4)
        self.assertNotIn('msPerFrame', result)
        self.assertIn('timerOverhead', document)
        self.assertIn('clockOverhead', document)
        self.assertIn('backend', result)
        self.assertIn('validation', result)


if __name__ == '__main__':
    unittest.main()
