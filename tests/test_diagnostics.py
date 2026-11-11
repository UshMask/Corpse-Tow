"""Bounded offline diagnostics: opt-in, aggregated, zero overhead when disabled."""
import json
import time
import unittest
from test_link_runtime import environment


def diagnostics(lua):
    return lua.eval("require('CVP_Diagnostics')")


SETUP = r'''
    function getTimestampMs() return now end
    __diag = require('CVP_Diagnostics')
'''


class DiagnosticsTests(unittest.TestCase):
    def fixture(self):
        lua = environment()
        lua.globals().benchClockMs = lambda: time.perf_counter() * 1000
        lua.execute(SETUP)
        return lua

    def test_disabled_by_default_and_installs_no_wrappers(self):
        lua = self.fixture()
        lua.execute('''
            assert(__diag.enabled() == false)
            local before = Sim.tick
            local D = require('CVP_Diagnostics')
            assert(D.enabled() == false and Sim.tick == before)
            assert(D.mark() == nil)
            local ok, value = pcall(function() return D.time('phase', function() return 1, 2, 3 end) end)
            assert(ok)
            assert(not D.enabled())
            -- Calling the disabled API records nothing and never raises.
            D.count('idle.count'); D.sample('idle.phase', 1); D.bytes('publish', 10)
            local snapshot = D.snapshot()
            assert(#snapshot.phases == 0 and #snapshot.counters == 0)
        ''')

    def test_enable_records_aggregates_and_disable_restores_exact_methods(self):
        lua = self.fixture()
        lua.execute('''
            local tick = Sim.tick
            local samples = H.samples
            assert(__diag.enable({clock = function() return benchClockMs() end}) ~= nil)
            assert(__diag.enabled())
            link(C, A, rope); link(A, B, chain)
            for i = 1, 12 do car.x = car.x + 0.05; run() end
            local snapshot = __diag.snapshot()
            assert(#snapshot.phases > 0 and #snapshot.counters > 0)
            local phases, counters, gauges = {}, {}, {}
            for _, row in ipairs(snapshot.phases) do phases[row.name] = row end
            for _, row in ipairs(snapshot.counters) do counters[row.name] = row end
            for _, row in ipairs(snapshot.gauges) do gauges[row.name] = row end
            assert(phases['tick'] and phases['tick'].unit == 'ms' and phases['tick'].count == 12)
            assert(phases['sim.tick'] and phases['sim.tick'].count > 0)
            assert(phases['capture'] and phases['capture'].count > 0)
            assert(phases['publish'] and phases['publish'].count > 0)
            assert(counters['sim.tick.calls'].count > 0)
            assert(counters['capture.frames'].count > 0)
            assert(counters['publish.frames'].count > 0)
            assert(counters['sim.bodyLoopPasses.estimated'].count > 0)
            assert(counters['host.samples.calls'].count > 0)
            assert(gauges['sim.records'] and gauges['sim.records'].value == 2)
            assert(gauges['capture.bodies'] and gauges['capture.bodies'].value >= 1)
            local publishBytes = counters['network.bytes.estimate.publish']
            assert(publishBytes and publishBytes.count > 0 and publishBytes.unit:find('bytes') ~= nil)
            -- Snapshot fields are documented and stable.
            assert(snapshot.schema == 'cvp-diagnostics' and snapshot.version == 1)
            assert(snapshot.memory and type(snapshot.memory.available) == 'boolean')
            assert(snapshot.hooks.installed > 0)
            assert(__diag.disable())
            assert(not __diag.enabled())
            assert(Sim.tick == tick and H.samples == samples)
            local after = __diag.snapshot()
            assert(#after.counters == #snapshot.counters)
            for _, row in ipairs(after.counters) do
                assert(row.count == counters[row.name].count, 'counter changed while disabled: ' .. row.name)
            end
        ''')
        snapshot = lua.eval('__diag.snapshot()')
        self.assertTrue(snapshot is not None)

    def test_reset_does_not_forget_wrappers_and_cycles_do_not_stack(self):
        """enable -> reset -> disable restores exactly; repeated cycles do not stack."""
        lua = self.fixture()
        lua.execute('''
            local tick = Sim.tick
            local body = H.body
            local capture = require('CVP_SimulationFrame').capture
            __diag.enable({memory = false, clock = function() return benchClockMs() end})
            local installed = #__diag.installed
            assert(installed > 0)
            -- Measurement reset must not touch lifecycle state.
            __diag.reset()
            assert(#__diag.installed == installed, 'reset forgot installed wrappers')
            assert(__diag.disable(), 'disable after reset failed')
            assert(not __diag.enabled())
            assert(Sim.tick == tick and H.body == body, 'reset/disable left a wrapper installed')
            assert(require('CVP_SimulationFrame').capture == capture)
            assert(#__diag.installed == 0 and __diag.snapshot().hooks.installed == 0)

            -- Enable twice: the first wrapper must be removed before the second is added.
            __diag.enable({memory = false, clock = function() return benchClockMs() end})
            assert(Sim.tick ~= tick)
            __diag.enable({memory = false, clock = function() return benchClockMs() end})
            assert(Sim.tick ~= tick and #__diag.installed == __diag.hookCount,
                're-enable stacked wrappers')
            assert(__diag.disable())
            assert(Sim.tick == tick and H.body == body)
            assert(require('CVP_SimulationFrame').capture == capture)
            assert(#__diag.installed == 0)
        ''')

    def test_ring_buffer_and_aggregates_are_bounded(self):
        lua = self.fixture()
        lua.execute('''
            __diag.enable({samples = 32, memory = false})
            for i = 1, 1000 do __diag.sample('bounded.phase', i) end
            local row
            for _, candidate in ipairs(__diag.snapshot().phases) do
                if candidate.name == 'bounded.phase' then row = candidate end
            end
            assert(row and row.count == 32 and row.dropped == 968)
            assert(row.min >= 969 and row.max == 1000)
            assert(row.median >= row.min and row.median <= row.max)
            assert(row.p95 >= row.median and row.p99 >= row.p95)
            __diag.disable()
        ''')

    def test_phase_and_counter_maps_overflow_without_growing(self):
        lua = self.fixture()
        lua.execute('''
            __diag.enable({samples = 8, maxPhases = 4, maxCounters = 8, memory = false})
            for i = 1, 20 do __diag.sample('phase-' .. i, i); __diag.count('metric-' .. i) end
            local snapshot = __diag.snapshot()
            assert(#snapshot.phases == 4)
            assert(#snapshot.counters == 8)
            assert(snapshot.overflow.phases == 16 and snapshot.overflow.counters == 12)
            __diag.disable()
        ''')

    def test_percentiles_use_nearest_rank_on_retained_samples(self):
        lua = self.fixture()
        values = lua.eval('''(function()
            __diag.enable({samples = 256, memory = false})
            for i = 1, 100 do __diag.sample('rank.phase', i) end
            local row
            for _, candidate in ipairs(__diag.snapshot().phases) do
                if candidate.name == 'rank.phase' then row = candidate end
            end
            __diag.disable()
            return row
        end)()''')
        self.assertEqual(values['count'], 100)
        self.assertAlmostEqual(values['min'], 1)
        self.assertAlmostEqual(values['max'], 100)
        self.assertAlmostEqual(values['mean'], 50.5)
        self.assertAlmostEqual(values['median'], 51)
        self.assertAlmostEqual(values['p95'], 95)
        self.assertAlmostEqual(values['p99'], 99)

    def test_count_units_and_bytes_are_labelled(self):
        lua = self.fixture()
        lua.execute('''
            __diag.enable({memory = false})
            __diag.count('network.publish.pages', 3)
            __diag.count('network.publish.pages', 2)
            __diag.count('save.wait.ms', 17, 'ms')
            __diag.bytes('publish', 512)
            local counters = {}
            for _, row in ipairs(__diag.snapshot().counters) do counters[row.name] = row end
            assert(counters['network.publish.pages'].count == 5 and counters['network.publish.pages'].unit == 'count')
            assert(counters['save.wait.ms'].count == 17 and counters['save.wait.ms'].unit == 'ms')
            assert(counters['network.bytes.estimate.publish'].count == 512)
            assert(counters['network.bytes.estimate.publish'].unit:find('estimate') ~= nil)
            __diag.disable()
        ''')

    def test_time_mark_and_time_to_measure_selected_work(self):
        lua = self.fixture()
        lua.execute('''
            __diag.enable({clock = function() return benchClockMs() end, memory = false})
            local value, second = __diag.time('manual.phase', function(a, b) return a + b, a * b end, 2, 3)
            assert(value == 5 and second == 6)
            local mark = __diag.mark()
            for i = 1, 1000 do local x = i * i end
            __diag.timeTo('manual.mark', mark)
            local phases = {}
            for _, row in ipairs(__diag.snapshot().phases) do phases[row.name] = row end
            assert(phases['manual.phase'] and phases['manual.phase'].count == 1)
            assert(phases['manual.mark'] and phases['manual.mark'].count == 1)
            assert(phases['manual.mark'].max >= 0)
            __diag.disable()
        ''')

    def test_player_action_to_confirmed_result_latency(self):
        lua = self.fixture()
        lua.execute('''
            __diag.enable({clock = function() return benchClockMs() end, memory = false})
            R.saveJob = {player = player}
            local outcome
            R:submit(player, 'prepare', {target = A, gear = rope:getID()}, function(ok) outcome = ok end)
            R.saveJob = nil
            assert(outcome == false)
            local latency, counters = 0, {}
            for _, row in ipairs(__diag.snapshot().phases) do
                if row.name == 'action.latency' then latency = row.count end
            end
            for _, row in ipairs(__diag.snapshot().counters) do counters[row.name] = row.count end
            assert(latency >= 1 and counters['action.rejected'] >= 1 and counters['action.requests'] >= 1)
            assert(not counters['action.confirmed'])
            __diag.disable()
        ''')

    def test_report_and_json_are_deterministic_and_parseable(self):
        lua = self.fixture()
        lua.execute('''
            __diag.enable({memory = false})
            __diag.sample('tick', 1.5); __diag.count('ticks')
            __diag.gauge('links', 3)
            __diag.disable()
        ''')
        text = lua.eval("require('CVP_Diagnostics').report()")
        self.assertIn('[cvp diagnostics]', text)
        self.assertIn('phases (ms)', text)
        self.assertIn('counters:', text)
        payload = lua.eval("require('CVP_Diagnostics').toJson()")
        document = json.loads(payload)
        self.assertEqual(document['schema'], 'cvp-diagnostics')
        self.assertEqual(document['version'], 1)
        self.assertIn('phases', document)
        self.assertIn('counters', document)

    def test_disabled_hot_path_is_not_wrapped_and_enabled_run_keeps_behavior(self):
        lua = self.fixture()
        lua.execute('''
            local tick = getTimestampMs
            local frame = R.tick
            __diag.enable({memory = false})
            assert(R.tick ~= frame)
            link(C, A, rope)
            local before = body.x
            for i = 1, 10 do car.x = car.x + 0.05; run() end
            assert(body.x > before + 0.01, 'diagnostics changed simulation behavior')
            __diag.disable()
            assert(R.tick == frame)
        ''')
        # The clock override is opt-in, never a global replacement.
        lua.execute("assert(getTimestampMs() == now)")

    def test_zero_overhead_when_disabled_on_hot_path(self):
        lua = self.fixture()
        lua.execute('''
            local tick = Sim.tick
            local body = H.body
            local serviceTick = S.tick
            local capture = require('CVP_SimulationFrame').capture
            -- Requiring and querying diagnostics must not replace any hot method.
            assert(__diag.enabled() == false)
            assert(Sim.tick == tick and H.body == body and S.tick == serviceTick)
            assert(require('CVP_SimulationFrame').capture == capture)
            for i = 1, 10 do car.x = car.x + 0.05; run() end
            assert(Sim.tick == tick and H.body == body and S.tick == serviceTick)
            assert(require('CVP_SimulationFrame').capture == capture)
        ''')


if __name__ == '__main__':
    unittest.main()
