"""Reproducible offline Lua performance matrix for Corpse Tow (NOT game FPS).

This tool measures the mod's Lua-side authority/presentation work in the isolated
lupa Lua 5.1 engine model used by the Python test suite. It never launches the
game, so Kahlua, Bullet physics, Java bridge cost and rendering are out of scope.
Only relative comparisons made with this exact protocol on one machine are
meaningful; results must not be reported as in-game FPS.

Measurement design (schema version 2):

* Every measured repeat builds a fresh fixture/VM from the same seed, settings,
  build script and warmup. Setup and warmup are outside the measured batch, and
  repeat N cannot see the state left by repeat N-1. A canonical checkpoint is
  hashed after warmup and after the measured frames; all repeats must be
  identical or the run is rejected.
* A measured batch returns BOTH its mean (one batch sample per repeat) and the
  raw per-frame durations collected inside Lua with ``benchClock``. Batch means
  are reported as ``batchMeanMs``; p50/p95/p99 come from the raw per-frame
  samples in ``tickMs`` and are never derived from batch means. The clock call
  cost is measured and reported separately, and no Python timer is installed in
  the solver/tether loop.
* MP scenarios interleave every frame: server tick -> deliver server packets ->
  client ticks -> deliver client packets. Whole-frame timings include packet
  delivery; delivery cost is also reported separately. Live, idle and state-loss
  variants are separate labelled scenarios.
* Every scenario records the actual solver backend, group/body/link/record
  counts, dt, expected substeps and expected work, and is rejected when the
  backend, topology or simulation activity does not match expectations.

Output: one JSON document with environment fingerprint (including the SHA-256 of
this bench file), protocol, optional per-phase profile rows and optional
CVP_Diagnostics snapshot.

Usage:
    .venv/Scripts/python.exe -B tools/diagnostics_bench.py --output local/runs/some-run
    .venv/Scripts/python.exe -B tools/diagnostics_bench.py --quick --no-mp
    .venv/Scripts/python.exe -B tools/diagnostics_bench.py --diagnostics --phase after
"""
import argparse
import datetime
import gc
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / 'tests'

SCHEMA = 'cvp-offline-diagnostics'
SCHEMA_VERSION = 2

DEFAULT_EXPECTED_BACKEND = 'lua-reference'
BACKEND_CHOICES = ('lua-reference', 'java-persistent', 'java-nonpersistent', 'any')

TICK_SAMPLE_LIMIT = 512
HISTOGRAM_BUCKETS = 64

CHECKPOINT_FIELDS = [
    'now', 'car.x/y', 'player.x/y', 'body.x/y/z/angle/world',
    'graph.links[id].revision/a/b/material/length',
    'sim.groups/sim.index/sim.records[x/y/z/angle/vx/vy/angularVelocity/takeup/ax/ay/length/maxGapSquared/reaction/loadMass/taut/blocked/failed/connected/correctionStep]',
    'runtime.motionElapsed/motionWallTime/motionPhysicsTime/lastPhysicsElapsed',
    'service.dirty/persistedRevision/index', 'host.generation/nextDiscovery', 'uuidSequence',
]

# ---------------------------------------------------------------------------
# Lua groundwork shared by every SP scenario. `benchClock` is injected from
# Python (time.perf_counter) because Lua 5.1 os.clock has ~1 ms granularity on
# Windows. The mod itself is never modified for measuring; phase wrappers are
# installed only during the short profile/diagnostics batch and then removed.
# ---------------------------------------------------------------------------
COMMON_LUA = r'''
__fi = 0
local __R = R

local function __num(value)
    if value ~= value then return 'nan' end
    if value == math.huge then return 'inf' end
    if value == -math.huge then return '-inf' end
    return string.format('%.17g', value)
end

local function __add(rows, key, value)
    if value == nil then return end
    local kind = type(value)
    if kind == 'number' then
        rows[#rows + 1] = key .. '=' .. __num(value)
    elseif kind == 'string' or kind == 'boolean' then
        rows[#rows + 1] = key .. '=' .. tostring(value)
    else
        rows[#rows + 1] = key .. '=<' .. kind .. '>'
    end
end

function __benchStats()
    local service = __R.service
    local links = 0
    for _ in pairs(service.graph.links) do links = links + 1 end
    local sim = __R.simulation
    local groups, records, multi = 0, 0, 0
    for _, group in ipairs(sim.groups) do
        groups = groups + 1
        records = records + #group.records
        if #group.records > 1 then multi = multi + 1 end
    end
    return {links = links, groups = groups, records = records, groupsWithMultipleRecords = multi,
        bodies = __all and #__all or 2}
end

function __benchBackend()
    local native = CVPSolverNative
    local useLua = (not native) or (not not CVPSolverUseLua)
    local name
    if useLua then
        name = 'lua-reference'
    elseif type(native.solvePersistent) == 'function' then
        name = 'java-persistent'
    else
        name = 'java-nonpersistent'
    end
    local version
    if native and type(native.version) == 'function' then
        local ok, value = pcall(native.version)
        if ok then version = tostring(value) end
    end
    return {name = name, native = native ~= nil,
        solvePersistent = native ~= nil and type(native.solvePersistent) == 'function',
        useLuaOverride = not not CVPSolverUseLua, version = version}
end

-- A fresh VM starts from the fixture's fixed initial RNG. Reset it explicitly so
-- the seed is part of the recorded protocol rather than an implicit fixture fact.
function __benchSeed()
    uuidSequence = 0
    forcedRandom = nil
    randomID = nil
    return {seed = 0, uuidSequence = 0}
end

function __benchExtra() return {} end

function __benchAddBody(i)
    local b = corpse()
    b.netID = tostring(100 + i)
    b.md.CVPBodyKey = 'body-' .. i
    b.getSquare = body.getSquare
    b.setSquare = body.setSquare
    b.getStaticMovingObjectIndex = body.getStaticMovingObjectIndex
    b.getAngle = body.getAngle
    sq:addCorpse(b)
    return b
end

function __benchBuildBodies(positions)
    local all = {body, body2}
    for i = 3, #positions do all[i] = __benchAddBody(i) end
    for i = 1, #positions do
        local p = positions[i]
        move(all[i], p[1], p[2])
    end
    __all = all
    H.discover()
    return all
end

function __benchRef(b)
    return {kind = 'body', key = b.md.CVPBodyKey, point = 'feet'}
end

function __benchLink(a, b)
    local function ref(v)
        if v == 'vehicle' then return C end
        return __benchRef(__all[v])
    end
    local gear = item('Base.Rope')
    storage:AddItem(gear)
    return link(ref(a), ref(b), gear)
end

-- One plain batch mean: the tight loop used for the A/B instrumentation delta.
function __benchPlainBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do __benchFrame() end
    return (benchClock() - started) * 1000 / frames
end

-- Per-frame raw samples. The clock call happens once per frame outside the
-- measured frame body; no Python timer is installed inside tether()/solver code.
function __benchTickBatch(frames)
    __fi = 0
    local started = benchClock()
    local previous = started
    local ticks = {}
    for i = 1, frames do
        __benchFrame()
        local at = benchClock()
        ticks[i] = (at - previous) * 1000
        previous = at
    end
    local finished = benchClock()
    return {batchMeanMs = (finished - started) * 1000 / frames, tickMs = ticks, count = frames}
end

function __benchWarm(frames)
    for _ = 1, frames do __benchFrame() end
    return true
end

-- Canonical state digest. Only numbers/strings/booleans are serialized so a
-- table address (which is process-specific) can never leak into a hash.
function __benchCheckpoint()
    local rows = {}
    __add(rows, 'now', now)
    __add(rows, 'car.x', car.x)
    __add(rows, 'car.y', car.y)
    __add(rows, 'player.x', player.x)
    __add(rows, 'player.y', player.y)
    for i, b in ipairs(__all or {body, body2}) do
        __add(rows, 'body.' .. i .. '.x', b.x)
        __add(rows, 'body.' .. i .. '.y', b.y)
        __add(rows, 'body.' .. i .. '.z', b.z or 0)
        __add(rows, 'body.' .. i .. '.world', b.world ~= false)
        if b.getAngle then __add(rows, 'body.' .. i .. '.angle', b:getAngle()) end
    end
    if __R then
        if __R.service then
            local graph = __R.service.graph
            local ids = {}
            for id in pairs(graph.links) do ids[#ids + 1] = tostring(id) end
            table.sort(ids)
            for _, id in ipairs(ids) do
                local row = graph.links[id]
                __add(rows, 'link.' .. id .. '.revision', row.revision)
                for _, side in ipairs({'a', 'b'}) do
                    local endpoint = row[side]
                    if endpoint then
                        __add(rows, 'link.' .. id .. '.' .. side .. '.kind', endpoint.kind)
                        __add(rows, 'link.' .. id .. '.' .. side .. '.key', endpoint.key)
                        __add(rows, 'link.' .. id .. '.' .. side .. '.x', endpoint.x)
                        __add(rows, 'link.' .. id .. '.' .. side .. '.y', endpoint.y)
                        __add(rows, 'link.' .. id .. '.' .. side .. '.z', endpoint.z)
                    end
                end
                __add(rows, 'link.' .. id .. '.material', row.material)
                __add(rows, 'link.' .. id .. '.length', row.length)
            end
            __add(rows, 'service.dirty', __R.service.dirty and true or false)
            __add(rows, 'service.persistedRevision', __R.service.persistedRevision)
            __add(rows, 'service.hasIndex', __R.service.index ~= nil)
        end
        if __R.simulation then
            local sim = __R.simulation
            __add(rows, 'sim.groups', #sim.groups)
            __add(rows, 'sim.hasIndex', sim.index ~= nil)
            local ids = {}
            for id in pairs(sim.records) do ids[#ids + 1] = tostring(id) end
            table.sort(ids)
            for _, id in ipairs(ids) do
                local r = sim.records[id]
                for _, field in ipairs({'x', 'y', 'z', 'angle', 'vx', 'vy', 'angularVelocity',
                        'takeup', 'ax', 'ay', 'length', 'maxGapSquared', 'reaction', 'loadMass',
                        'taut', 'blocked', 'failed', 'connected', 'correctionStep'}) do
                    __add(rows, 'rec.' .. id .. '.' .. field, r[field])
                end
            end
        end
        __add(rows, 'runtime.motionElapsed', __R.motionElapsed)
        __add(rows, 'runtime.motionWallTime', __R.motionWallTime)
        __add(rows, 'runtime.motionPhysicsTime', __R.motionPhysicsTime)
        __add(rows, 'runtime.lastPhysicsElapsed', __R.lastPhysicsElapsed)
        __add(rows, 'runtime.error', __R.error and tostring(__R.error) or 'nil')
    end
    if H then
        __add(rows, 'host.generation', H.generation)
        __add(rows, 'host.nextDiscovery', H.nextDiscovery)
    end
    __add(rows, 'uuidSequence', uuidSequence)
    return table.concat(rows, '\n')
end

function __benchState()
    local state = {bodies = {}, links = 0, groups = 0, records = 0, bodiesCount = 0,
        calculating = false, error = false}
    local stats = __benchStats()
    state.links = stats.links
    state.groups = stats.groups
    state.records = stats.records
    state.bodiesCount = stats.bodies
    for i, b in ipairs(__all or {body, body2}) do
        state.bodies[i] = {x = b.x, y = b.y, z = b.z or 0,
            angle = b.getAngle and b:getAngle() or 0, world = b.world ~= false}
    end
    state.calculating = __R.simulation.calculating ~= nil
    state.error = __R.error and tostring(__R.error) or false
    return state
end

__probe = nil
function __benchProbeStart()
    __probe = {groupCalls = 0, coreCalls = 0, simTicks = 0, restore = {}}
    local function wrap(owner, key, counter)
        if not owner or type(owner[key]) ~= 'function' then return end
        local original = owner[key]
        __probe.restore[#__probe.restore + 1] = {owner = owner, key = key, original = original}
        owner[key] = function(...)
            __probe[counter] = __probe[counter] + 1
            return original(...)
        end
    end
    wrap(__R.simulation, 'tick', 'simTicks')
    local okGroup, GroupConstraints = pcall(require, 'CVP_GroupConstraints')
    if okGroup then wrap(GroupConstraints, 'step', 'groupCalls') end
    local okCore, Core = pcall(require, 'CVP_Core')
    if okCore then wrap(Core, 'advance', 'coreCalls') end
    return true
end

function __benchProbeFinish()
    local result = {groupCalls = __probe.groupCalls, coreCalls = __probe.coreCalls,
        simTicks = __probe.simTicks}
    for i = #__probe.restore, 1, -1 do
        local entry = __probe.restore[i]
        entry.owner[entry.key] = entry.original
    end
    __probe = nil
    return result
end

function __benchValidationRun(frames)
    __fi = 0
    __benchProbeStart()
    local states = {}
    for i = 1, frames do
        __benchFrame()
        states[i] = __benchState()
    end
    local probe = __benchProbeFinish()
    return {states = states, probe = probe, stats = __benchStats(),
        backend = __benchBackend(), finalState = __benchState()}
end

__phaseRows = {}
__phaseRestore = {}
function __benchPhaseBegin(hooks)
    __phaseRows = {}
    __phaseRestore = {}
    for _, hook in ipairs(hooks) do
        local owner = assert(loadstring('return ' .. hook.target))()
        local original = owner[hook.key]
        if type(original) == 'function' then
            local row = {name = hook.name, calls = 0, ms = 0}
            __phaseRows[#__phaseRows + 1] = row
            local wrapper = function(...)
                local started = benchClock()
                local a, b, c = original(...)
                row.ms = row.ms + (benchClock() - started) * 1000
                row.calls = row.calls + 1
                return a, b, c
            end
            local hadRaw = rawget(owner, hook.key) ~= nil
            __phaseRestore[#__phaseRestore + 1] = {owner = owner, key = hook.key, original = original, hadRaw = hadRaw}
            owner[hook.key] = wrapper
        end
    end
    return #__phaseRows
end
function __benchPhaseEnd()
    for _, entry in ipairs(__phaseRestore) do
        if entry.hadRaw then entry.owner[entry.key] = entry.original
        else entry.owner[entry.key] = nil end
    end
    __phaseRestore = {}
    return __phaseRows
end
'''

INNER_PHASES = [
    ("require('CVP_LinkJoints')", 'length', 'joints.length'),
    ("require('CVP_Core')", 'advance', 'core.advance'),
    ("require('CVP_GroupConstraints')", 'step', 'groupConstraints.step'),
    ("require('CVP_Rope')", 'separate', 'rope.separate'),
    ("require('CVP_Load')", 'refresh', 'load.refresh'),
    ("require('CVP_Load')", 'connect', 'load.connect'),
    ("require('CVP_LinkObstacles')", 'check', 'obstacles.check'),
    ("require('CVP_Geometry')", 'capture', 'geometry.capture'),
    ("require('CVP_VehicleTrajectory')", 'advance', 'trajectory.advance'),
    ("require('CVP_VehicleTrajectory')", 'sample', 'trajectory.sample'),
    ('H', 'body', 'host.body'),
    ('H', 'bodyPoint', 'host.bodyPoint'),
    ('H', 'sample', 'host.sample'),
    ('Sim', 'prepareGroup', 'sim.prepareGroup'),
]

AUTHORITY_PHASES = INNER_PHASES + [
    ('R', 'tick', 'tick'),
    ('R', 'simulate', 'tick.simulate'),
    ('R', 'publishFrame', 'publish'),
    ('R', 'samples', 'tick.samples'),
    ('R', 'discover', 'tick.discover'),
    ("require('CVP_SimulationFrame')", 'capture', 'capture'),
    ('Sim', 'tick', 'sim.tick'),
    ('Sim', 'build', 'sim.build'),
    ('Sim', 'apply', 'sim.apply'),
    ('S', 'tick', 'service.tick'),
    ('S', 'flush', 'service.flush'),
    ('H', 'samples', 'host.samples'),
    ("require('CVP_LinkJoints')", 'place', 'joints.place'),
]

PRESENTATION_PHASES = AUTHORITY_PHASES + [
    ('Renderer', 'update', 'presentation.update'),
]

CLIENT_PHASES = [
    ('CVPRuntime.handlers', 'OnTick', 'client.OnTick'),
    ('R', 'tick', 'tick'),
    ("require('CVP_SimulationFrame')", 'capture', 'capture'),
]

MP_SERVER_PHASES = [
    ('CVPMPServer', 'tick', 'mp.server.tick'),
    ('R', 'tick', 'tick'),
    ('R', 'simulate', 'tick.simulate'),
    ("require('CVP_SimulationFrame')", 'capture', 'capture'),
    ('CVPMPServer', 'capture', 'mp.server.capture'),
    ('CVPMPServer', 'publish', 'mp.server.publish'),
    ('R.simulation', 'tick', 'sim.tick'),
    ('R.service', 'tick', 'service.tick'),
    ('R.host', 'samples', 'host.samples'),
]

MP_CLIENT_PHASES = [
    ('CVPMPClient', 'tick', 'mp.client.tick'),
]


def phases_for_mode(mode):
    if mode == 'presentation':
        return PRESENTATION_PHASES
    if mode == 'client':
        return CLIENT_PHASES
    return AUTHORITY_PHASES


# ---------------------------------------------------------------------------
# Geometry helpers.
# ---------------------------------------------------------------------------
def individual_positions(count):
    """Bodies on one or two rings around the vehicle anchor, all within rope reach."""
    positions = []
    if count <= 4:
        radius = 5.0
        for i in range(count):
            angle = 2 * math.pi * i / count
            positions.append((2 + radius * math.cos(angle), radius * math.sin(angle)))
        return positions
    inner = 16
    outer = count - inner
    for i in range(inner):
        angle = 2 * math.pi * i / inner
        positions.append((2 + 7.0 * math.cos(angle), 7.0 * math.sin(angle)))
    for i in range(outer):
        angle = 2 * math.pi * (i + 0.5) / outer
        positions.append((2 + 10.2 * math.cos(angle), 10.2 * math.sin(angle)))
    return positions


def chain_positions(start, direction, count, spacing=3.0):
    positions = []
    for i in range(count):
        positions.append((start[0] + direction[0] * spacing * i,
                          start[1] + direction[1] * spacing * i))
    return positions


def positions_lua(positions):
    rows = ','.join('{%.6f,%.6f}' % (x, y) for x, y in positions)
    return 'local __positions = {%s}\n__benchBuildBodies(__positions)\n' % rows


def links_lua(links):
    rows = []
    for a, b in links:
        left = "'vehicle'" if a == 'vehicle' else str(a)
        right = str(b)
        rows.append('__benchLink(%s,%s)' % (left, right))
    return '\n'.join(rows) + '\n'


def individual_scene(count):
    positions = individual_positions(count)
    links = [('vehicle', i + 1) for i in range(count)]
    return positions_lua(positions) + links_lua(links)


def chain_scene(count, start=(-2.0, 0.0), direction=(-1.0, 0.0)):
    """Chain behind the vehicle anchor so a forward drive keeps the rope taut."""
    positions = chain_positions(start, direction, count)
    links = [('vehicle', 1)]
    for i in range(1, count):
        links.append((i, i + 1))
    return positions_lua(positions) + links_lua(links)


def groups_scene(chains):
    """chains: list of (start, direction, count). Returns setup Lua."""
    positions = []
    links = []
    offset = 0
    for start, direction, count in chains:
        positions.extend(chain_positions(start, direction, count))
        links.append(('vehicle', offset + 1))
        for i in range(1, count):
            links.append((offset + i, offset + i + 1))
        offset += count
    return positions_lua(positions) + links_lua(links)


# Identical 32-body chain starts for the controlled 1/2/4 scaling matrix. Every
# chain has the same relative geometry and the same straight input; only the
# lateral offset from the vehicle differs, so measured work scales with chain
# count. Chains trail behind the vehicle so the forward drive keeps them taut.
CONTROLLED_CHAIN_STARTS = [
    (-2.0, 0.0),
    (-2.0, 5.0),
    (-2.0, -5.0),
    (-2.0, 10.0),
]


def controlled_scene(chains):
    return groups_scene([(CONTROLLED_CHAIN_STARTS[i], (-1.0, 0.0), 32) for i in range(chains)])


def work(bodies, links, groups):
    return {'bodies': bodies, 'links': links, 'groups': groups, 'records': links}


STRAIGHT_FRAME = 'car.x = car.x + 0.05\nrun()'
# Smooth circular arc from the restored warm pose: heading grows 0.02 rad/frame at
# 1 m/s, so the repeat never teleports the vehicle away from its chain.
TURN_FRAME = '''__fi = __fi + 1
local heading = 0.02 * __fi
car.x = car.x + 0.05 * math.cos(heading)
car.y = car.y + 0.05 * math.sin(heading)
run()'''
BRAKE_FRAME = '''__fi = __fi + 1
local speed = math.max(0.002, 0.05 * (1 - (__fi - 1) / 60))
car.x = car.x + speed
run()'''
BACKWARDS_FRAME = 'car.x = car.x - 0.01\nrun()'
OBSTACLE_FRAME = 'car.x = car.x + 0.01\nrun()'
IDLE_FRAME = 'run()'
GRID_KEYS = '{}'


def expected_substeps(dt_ms):
    """Same formula as CVP_LinkSimulation: steps = max(1, ceil(dt*100 - 1e-9))."""
    return max(1, int(math.ceil(dt_ms / 1000.0 * 100 - 1e-9)))


def scenario_repeats(scenario):
    """The single repetition key used by every mode.

    scenario_list writes ``repeats`` and runners read ``repeats`` through this
    helper. A missing or invalid value is a protocol error, not a silent default.
    """
    value = scenario.get('repeats')
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('scenario %r must define a positive integer repeats key, got %r'
                         % (scenario.get('id'), value))
    return value


def _scenario(id, mode, description, kind, build='', frame=IDLE_FRAME, warmup=0, repeats=3,
              frames=1, expected_work=None, expect_motion=False, sim_ticks_per_frame=1,
              validate_substeps=True, phases=None, extra=None, after_warmup=None,
              dt_ms=50, expected_backend=None, validation_frames=None, warmup_frame=None):
    scenario = dict(id=id, mode=mode, kind=kind, description=description, build=build,
                    frame=frame, warmup=warmup, repeats=repeats, frames=frames,
                    expected_work=expected_work or work(2, 0, 0),
                    expect_motion=expect_motion, sim_ticks_per_frame=sim_ticks_per_frame,
                    validate_substeps=validate_substeps, dtMs=dt_ms)
    if phases is not None:
        scenario['phases'] = phases
    if extra is not None:
        scenario['extra'] = extra
    if after_warmup is not None:
        scenario['after_warmup'] = after_warmup
    if expected_backend is not None:
        scenario['expected_backend'] = expected_backend
    if validation_frames is not None:
        scenario['validation_frames'] = validation_frames
    if warmup_frame is not None:
        scenario['warmup_frame'] = warmup_frame
    return scenario


def scenario_list(quick):
    """Full reproducible matrix. Frame counts scale down with --quick.

    Kind labels keep the three scaling questions separate:
      controlled-scaling   identical 32-body chain counts 1/2/4 (same input)
      scaling-comparison   32 independent links vs one 32-body chain
      stress               mixed directions, turn, brake, reverse, obstacles
      model                targeted path scenarios (save, chunk, graph copy, ...)
      mp-live/mp-idle/mp-loss   interleaved MP variants
    """
    # Quick mode is a smoke protocol: taut chains are genuinely expensive per
    # frame (~0.2 s for 32 dragged bodies in the lupa fixture), so quick scales
    # the frame counts down hard while keeping >=2 repeats and full validation.
    chain_warm = 8 if quick else 20
    chain_frames = 6 if quick else 20
    chain_reps = 2 if quick else 3
    heavy_frames = 6 if quick else 14
    heavy_reps = 2
    heavy_warm = 8 if quick else 16
    idle_frames = 200 if quick else 400
    individual_frames = 40 if quick else 150
    individual_reps = 3 if quick else 5
    individual32_frames = 40 if quick else 100
    presentation_individual_frames = 30 if quick else 60
    scenarios = [
        _scenario('idle.authority', 'authority',
                  'Mod enabled, 0 links: idle authority tick (~1 discovery/s)', 'baseline',
                  frame=IDLE_FRAME, warmup=50, repeats=5, frames=idle_frames,
                  expected_work=work(2, 0, 0), expect_motion=False, sim_ticks_per_frame=0,
                  phases=[('R', 'tick', 'tick'), ('Sim', 'tick', 'sim.tick'),
                          ('S', 'tick', 'service.tick')]),
        _scenario('bodies.4.individual', 'authority',
                  '4 bodies, 4 independent vehicle links', 'baseline',
                  build=individual_scene(4), frame=STRAIGHT_FRAME, warmup=40 if quick else 80,
                  repeats=individual_reps, frames=individual_frames,
                  expected_work=work(4, 4, 4), expect_motion=True),
        _scenario('bodies.32.individual', 'authority',
                  '32 bodies, 32 independent vehicle links (allowed default config)', 'scaling-comparison',
                  build=individual_scene(32), frame=STRAIGHT_FRAME, warmup=40 if quick else 60,
                  repeats=3 if quick else 4, frames=individual32_frames,
                  expected_work=work(32, 32, 32), expect_motion=True),
        _scenario('bodies.32.chain', 'authority',
                  'One 32-body chain, straight drive (same input as bodies.32.individual)',
                  'scaling-comparison',
                  build=chain_scene(32), frame=STRAIGHT_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames,
                  expected_work=work(32, 32, 1), expect_motion=True),
        _scenario('bodies.32.chain.turn', 'authority',
                  'One 32-body chain, circular turn (stress: turn)', 'stress',
                  build=chain_scene(32), frame=TURN_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames, warmup_frame=STRAIGHT_FRAME,
                  expected_work=work(32, 32, 1), expect_motion=True, validation_frames=8),
        _scenario('bodies.32.chain.brake', 'authority',
                  'One 32-body chain, decelerating from 1 m/s (stress: brake)', 'stress',
                  build=chain_scene(32), frame=BRAKE_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames, warmup_frame=STRAIGHT_FRAME,
                  expected_work=work(32, 32, 1), expect_motion=True, validation_frames=8),
        _scenario('bodies.32.chain.backwards', 'authority',
                  'One 32-body chain, reversing (stress: backwards)', 'stress',
                  build=chain_scene(32), frame=BACKWARDS_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames, warmup_frame=STRAIGHT_FRAME,
                  expected_work=work(32, 32, 1), expect_motion=True, validation_frames=8),
        _scenario('bodies.32.chain.obstacle', 'authority',
                  'One 32-body chain with every square solid (stress: obstacle/blocked path)', 'stress',
                  build=chain_scene(32), frame=OBSTACLE_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames,
                  expected_work=work(32, 32, 1), expect_motion=False,
                  validate_substeps=False, after_warmup='blocked = true'),
        _scenario('bodies.128.groups4', 'authority',
                  '128 bodies in 4 32-body chains, mixed directions (stress: mixed directions)', 'stress',
                  build=groups_scene([((4.0, 0.0), (1.0, 0.0), 32), ((-2.0, 0.0), (-1.0, 0.0), 32),
                                      ((2.0, 3.0), (0.0, 1.0), 32), ((2.0, -3.0), (0.0, -1.0), 32)]),
                  frame=STRAIGHT_FRAME, warmup=heavy_warm, repeats=heavy_reps, frames=heavy_frames,
                  expected_work=work(128, 128, 4), expect_motion=True),
        _scenario('bodies.128.groups4.turn', 'authority',
                  '128 bodies in 4 chains, circular turn (stress: mixed + turn)', 'stress',
                  build=groups_scene([((4.0, 0.0), (1.0, 0.0), 32), ((-2.0, 0.0), (-1.0, 0.0), 32),
                                      ((2.0, 3.0), (0.0, 1.0), 32), ((2.0, -3.0), (0.0, -1.0), 32)]),
                  frame=TURN_FRAME, warmup=heavy_warm, repeats=heavy_reps, frames=heavy_frames,
                  expected_work=work(128, 128, 4), expect_motion=True, validation_frames=8),
        _scenario('requests.excess', 'authority',
                  '32-body chain with an outstanding save job: 8 excess submit attempts per frame',
                  'model',
                  build=chain_scene(32) + 'rejections = 0\n',
                  frame='''R.saveJob = {player = player}
for _ = 1, 8 do
    R:submit(player, 'prepare', {target = A, gear = rope:getID()}, function(ok)
        if ok == false then rejections = rejections + 1 end
    end)
end
R.saveJob = nil
car.x = car.x + 0.05
run()''',
                  warmup=8 if quick else 20, repeats=2 if quick else 3,
                  frames=8 if quick else 20,
                  expected_work=work(32, 32, 1), expect_motion=True,
                  extra='return {rejections = rejections, saveQueueLength = #R.saveQueue}'),
        _scenario('chunk.unavailable', 'authority',
                  '4-body scene, one body unavailable 10/40 frames (chunk unload approximation)',
                  'model',
                  build=individual_scene(4) + 'chunkBody = bodies[3]\n',
                  frame='''__fi = __fi + 1
local phaseMod = (__fi - 1) % 40
chunkBody.world = not (phaseMod >= 10 and phaseMod < 20)
car.x = car.x + 0.05
run()''',
                  warmup=50 if quick else 80, repeats=3 if quick else 4,
                  frames=50 if quick else 80,
                  expected_work={'bodies': 4, 'links': 4, 'groups': 4, 'records': None},
                  expect_motion=True, validate_substeps=False,
                  extra='return {scenario = "chunk.unavailable"}'),
        _scenario('reconnect.players', 'authority',
                  '4-body scene, player disconnects 5/30 frames then reconnects (recovery/save approximation)',
                  'model',
                  build=individual_scene(4),
                  frame='''__fi = __fi + 1
if (__fi - 1) % 30 < 5 then
    now = now + 50
    local ok = R:tick({}, 0.05)
    if not ok and not R.retryAt then error('disconnect tick failed') end
else
    car.x = car.x + 0.05
    run()
end''',
                  warmup=60 if quick else 80, repeats=3 if quick else 4,
                  frames=50 if quick else 60,
                  expected_work=work(4, 4, 4), expect_motion=True, validate_substeps=False),
        _scenario('save.flush', 'authority',
                  '32-body chain, forced ledger flush every frame (fixture persistence model included; see limitations)',
                  'model',
                  build=chain_scene(32),
                  frame='''car.x = car.x + 0.05
now = now + 50
S.dirty = true
assert(S:flush())''',
                  warmup=50 if quick else 60, repeats=3 if quick else 4,
                  frames=30 if quick else 40,
                  expected_work={'bodies': 32, 'links': 32, 'groups': 0, 'records': 0},
                  expect_motion=False, sim_ticks_per_frame=0, validate_substeps=False),
        _scenario('graph.copy', 'authority',
                  '32-body chain, deep graph copy every frame (pure Lua serialization proxy)',
                  'model',
                  build=chain_scene(32),
                  frame='''car.x = car.x + 0.05
run()
G.copy(S.graph)''',
                  warmup=8 if quick else 20, repeats=2 if quick else 3,
                  frames=8 if quick else 20,
                  expected_work=work(32, 32, 1), expect_motion=True),
        _scenario('presentation.0links', 'presentation',
                  'Presentation update with no links (client idle visual path)', 'baseline',
                  build='', frame='now = now + 50\nrender()', warmup=50, repeats=5,
                  frames=idle_frames, expected_work=work(2, 0, 0), expect_motion=False,
                  sim_ticks_per_frame=0),
        _scenario('presentation.32.chain', 'presentation',
                  'Full SP frame model: authority tick plus presentation update for a 32-body chain',
                  'baseline',
                  build=chain_scene(32), frame='car.x = car.x + 0.05\nrun()\nrender()',
                  warmup=chain_warm, repeats=chain_reps, frames=chain_frames,
                  expected_work=work(32, 32, 1), expect_motion=True),
        _scenario('presentation.32.individual', 'presentation',
                  'Full SP frame model: authority tick plus presentation for 32 independent links (crowded mode)',
                  'baseline',
                  build=individual_scene(32), frame='car.x = car.x + 0.02\nrun()\nrender()',
                  warmup=40 if quick else 60, repeats=3,
                  frames=presentation_individual_frames,
                  expected_work=work(32, 32, 32), expect_motion=True),
        _scenario('client.0links.idle', 'client',
                  'Real client OnTick entry point with no links (full mod frame, idle)', 'baseline',
                  build='', frame='now = now + 16\ncallbacks.OnTick()\nassert(not CVPRuntime.error)',
                  warmup=100, repeats=5, frames=idle_frames, expected_work=work(2, 0, 0),
                  expect_motion=False, sim_ticks_per_frame=0),
        # Controlled scaling matrix: identical 32-body chains, identical input.
        _scenario('scale.chains.1x32', 'authority',
                  'Controlled scaling: one identical 32-body chain', 'controlled-scaling',
                  build=controlled_scene(1), frame=STRAIGHT_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames,
                  expected_work=work(32, 32, 1), expect_motion=True),
        _scenario('scale.chains.2x32', 'authority',
                  'Controlled scaling: two identical 32-body chains', 'controlled-scaling',
                  build=controlled_scene(2), frame=STRAIGHT_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames,
                  expected_work=work(64, 64, 2), expect_motion=True),
        _scenario('scale.chains.4x32', 'authority',
                  'Controlled scaling: four identical 32-body chains', 'controlled-scaling',
                  build=controlled_scene(4), frame=STRAIGHT_FRAME, warmup=chain_warm,
                  repeats=chain_reps, frames=chain_frames,
                  expected_work=work(128, 128, 4), expect_motion=True),
        # MP matrix: interleaved server/client frames including packet delivery.
        _scenario('mp.live.2clients.8', 'mp',
                  'MP live: server tick -> deliver -> owner/friend ticks -> deliver, 8-body chain, moving',
                  'mp-live', warmup=10, repeats=2 if quick else 3, frames=40 if quick else 40,
                  expected_work=work(8, 8, 1), dt_ms=100),
        _scenario('mp.idle.2clients.8', 'mp',
                  'MP idle: same interleaved delivery with a stationary server (idle heartbeat path)',
                  'mp-idle', warmup=10, repeats=2 if quick else 3, frames=40 if quick else 40,
                  expected_work=work(8, 8, 1), dt_ms=100),
        _scenario('mp.loss.2clients.8', 'mp',
                  'MP state-loss: every second server state/motion packet is dropped (labelled loss variant)',
                  'mp-loss', warmup=10, repeats=2 if quick else 3, frames=40 if quick else 40,
                  expected_work=work(8, 8, 1), dt_ms=100),
    ]
    for scenario in scenarios:
        if scenario['mode'] == 'mp':
            scenario['variant'] = scenario['kind'].split('-', 1)[1]
    if quick:
        scenarios.insert(-3, _scenario(
            'smoke.tiny', 'authority', 'Instrumentation self-check: 4-body chain, tiny protocol',
            'self-check', build=chain_scene(4), frame=STRAIGHT_FRAME, warmup=3, repeats=7,
            frames=4, expected_work=work(4, 4, 1), expect_motion=True, validation_frames=3))
    return scenarios


# ---------------------------------------------------------------------------
# Generic helpers.
# ---------------------------------------------------------------------------
def to_py(value):
    if hasattr(value, 'items'):
        items = list(value.items())
        try:
            keys = sorted(int(k) for k in (key for key, _ in items))
        except (TypeError, ValueError):
            keys = None
        if keys == list(range(1, len(items) + 1)):
            return [to_py(value) for _, value in sorted(items, key=lambda kv: int(kv[0]))]
        return {str(key): to_py(item) for key, item in items}
    return value


def git(*args):
    try:
        return subprocess.check_output(['git'] + list(args), cwd=str(ROOT),
                                       stderr=subprocess.DEVNULL).decode('utf-8', 'replace').strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def digest_text(text):
    if not isinstance(text, str):
        text = str(text)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


TRACKED_LUA = [
    'CorpseProxyLab/42/media/lua/shared/CVP_LinkRuntime.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_LinkSimulation.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_LinkPresentation.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_SimulationFrame.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_LinkHost.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_SimulationClock.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_Diagnostics.lua',
    'CorpseProxyLab/42/media/lua/client/CVP_Motion.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_LinkService.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_LinkGraph.lua',
    'CorpseProxyLab/42/media/lua/shared/CVP_Equipment.lua',
    'CorpseProxyLab/42/media/lua/server/CVP_MPServer.lua',
    'CorpseProxyLab/42/media/lua/client/CVP_MPClient.lua',
]


def environment_info(lua=None):
    memory = None
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            memory = {'totalBytes': int(status.ullTotalPhys),
                      'availableBytes': int(status.ullAvailPhys),
                      'loadPercent': int(status.dwMemoryLoad)}
    except Exception:
        memory = None
    dirty = [line[3:] for line in git('status', '--porcelain').splitlines() if line[:2].strip()]
    files = {}
    for relative in TRACKED_LUA:
        path = ROOT / relative
        if path.exists():
            files[relative] = {'sha256': sha256(path), 'bytes': path.stat().st_size}
    bench_path = Path(__file__).resolve()
    info = {
        'measuredAt': datetime.datetime.now().astimezone().isoformat(),
        'kind': 'offline-lua-model',
        'interpreter': 'lupa Lua 5.1 embedded in Python (NO game, NO Kahlua, NO Java bridge)',
        'luaVersion': lua.eval('_VERSION') if lua is not None else None,
        'python': sys.version.split()[0],
        'lupa': None,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'processor': os.environ.get('PROCESSOR_IDENTIFIER') or platform.processor(),
        'cpuCount': os.cpu_count(),
        'memory': memory,
        'source': {
            'branch': git('branch', '--show-current'),
            'commit': git('rev-parse', 'HEAD'),
            'dirty': bool(dirty),
            'dirtyPaths': sorted(dirty),
            'files': files,
            'bench': {
                'file': 'tools/diagnostics_bench.py',
                'sha256': sha256(bench_path),
                'schemaVersion': SCHEMA_VERSION,
            },
        },
        'gameVersion': 'Project Zomboid Build 42.21 (not executed by this tool)',
    }
    try:
        import lupa
        info['lupa'] = getattr(lupa, '__version__', None)
    except ImportError:
        pass
    return info


def clock_overhead(lua):
    """Measure the cost of one Python clock call from Lua, as used per tick."""
    if lua is None:
        return None
    lua.globals().benchClock = time.perf_counter
    value = lua.eval('''(function()
        local started = benchClock()
        for _ = 1, 10000 do benchClock() end
        return (benchClock() - started) / 10000 * 1e6
    end)()''')
    python_call_us = None
    try:
        noop = lua.eval('(function() return 0 end)')
        started = time.perf_counter()
        for _ in range(1000):
            noop()
        python_call_us = (time.perf_counter() - started) / 1000.0 * 1e6
    except Exception:
        python_call_us = None
    return {'usPerCall': float(value), 'calls': 10000,
            'pythonLuaCallUs': python_call_us,
            'timerCallsPerTick': 1,
            'note': 'one benchClock() call per measured frame; no timer inside tether()'}


def _close(lua):
    try:
        del lua
    finally:
        gc.collect()


def sp_fixture(mode):
    if mode == 'authority':
        from test_link_runtime import environment
        return environment
    if mode == 'presentation':
        from test_link_presentation import scene
        return scene
    if mode == 'client':
        from test_link_client import client
        return client
    raise ValueError('unknown SP mode %r' % (mode,))


def prepare_sp(lua, scenario):
    """Fresh fixture -> seed -> build -> frame function -> warmup. Returns the seed block."""
    lua.globals().benchClock = time.perf_counter
    lua.execute(COMMON_LUA)
    seed = to_py(lua.eval('__benchSeed()'))
    if scenario.get('build'):
        lua.execute(scenario['build'])
    lua.execute('function __benchFrame()\n%s\nend' % scenario['frame'])
    lua.execute('function __benchExtra() %s end' % scenario.get('extra', 'return {}'))
    warmup = int(scenario.get('warmup', 0))
    warmup_frame = scenario.get('warmup_frame')
    if warmup and warmup_frame:
        lua.execute('__benchMeasuredFrame = __benchFrame')
        lua.execute('function __benchFrame()\n%s\nend' % warmup_frame)
        lua.eval('__benchWarm(%d)' % warmup)
        lua.execute('__benchFrame = __benchMeasuredFrame')
        lua.execute('__benchMeasuredFrame = nil')
    elif warmup:
        lua.eval('__benchWarm(%d)' % warmup)
    after_warmup = scenario.get('after_warmup')
    if after_warmup:
        lua.execute(after_warmup)
    return seed


def lua_hooks(hook_list):
    rows = ','.join('{target=%s,key=%s,name=%s}' % (
        json_quote_lua(target), json_quote_lua(key), json_quote_lua(name))
        for target, key, name in hook_list)
    return '{%s}' % rows


def json_quote_lua(text):
    return json.dumps(text, ensure_ascii=True)


def convert_phase_rows(rows, frames):
    result = []
    for row in rows:
        row = to_py(row)
        calls = row.get('calls', 0)
        ms = row.get('ms', 0.0)
        result.append({
            'name': row.get('name'),
            'calls': calls,
            'callsPerFrame': calls / frames if frames else None,
            'msPerFrame': ms / frames if frames else None,
            'msPerCall': (ms / calls) if calls else None,
        })
    return result


def evaluate_stats(lua, extra_lua=None):
    stats = to_py(lua.eval('__benchStats()'))
    stats = {str(k): v for k, v in stats.items()}
    if extra_lua:
        extra = to_py(lua.eval('(function() %s end)()' % extra_lua))
        stats['extra'] = extra
    return stats


def run_profiled(lua, phases, frames):
    if not phases or frames <= 0:
        return [], 0
    lua.eval('__benchPhaseBegin(%s)' % lua_hooks(phases))
    try:
        per_frame = float(lua.eval('__benchPlainBatch(%d)' % frames))
    finally:
        rows = to_py(lua.eval('__benchPhaseEnd()'))
    return convert_phase_rows(rows, frames), per_frame


def diagnostics_snapshot(lua, frames):
    try:
        module = lua.eval("package.loaded['CVP_Diagnostics'] or require('CVP_Diagnostics')")
    except Exception:
        return None
    lua.globals().benchClock = time.perf_counter
    try:
        lua.execute("""
            local D = require('CVP_Diagnostics')
            D.enable({clock = function() return benchClock() * 1000 end})
            D.reset()
        """)
    except Exception as error:
        return {'error': 'enable failed: %r' % (error,)}
    try:
        if frames > 0:
            lua.eval('__benchPlainBatch(%d)' % frames)
        snapshot = to_py(lua.eval("require('CVP_Diagnostics').snapshot()"))
        return snapshot
    finally:
        try:
            lua.execute("require('CVP_Diagnostics').disable()")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Measurement summaries. Batch means and per-tick samples stay numerically and
# semantically separate: percentiles are computed only from raw tick samples.
# ---------------------------------------------------------------------------
def percentile(ordered, p):
    index = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def distribution(values):
    ordered = sorted(values)
    count = len(ordered)
    mean = sum(ordered) / count
    variance = sum((value - mean) ** 2 for value in ordered) / count
    return {'count': count, 'min': ordered[0], 'p50': percentile(ordered, 50),
            'p95': percentile(ordered, 95), 'p99': percentile(ordered, 99),
            'max': ordered[-1], 'mean': mean, 'stdDev': math.sqrt(variance)}


def summarize_batch(values):
    values = [float(value) for value in values]
    ordered = sorted(values)
    count = len(ordered)
    mean = sum(ordered) / count
    variance = sum((value - mean) ** 2 for value in ordered) / count
    return {
        'kind': 'batch-mean',
        'unit': 'ms/frame',
        'source': 'one mean per repeat; (batch elapsed)/(frames) inside Lua',
        'count': count,
        'min': ordered[0],
        'median': percentile(ordered, 50),
        'p95': percentile(ordered, 95),
        'max': ordered[-1],
        'mean': mean,
        'stdDev': math.sqrt(variance),
        'values': values,
    }


def histogram(values, buckets=HISTOGRAM_BUCKETS):
    if not values:
        return None
    low = min(values)
    high = max(values)
    if high <= low:
        return {'bucketCount': 1, 'minMs': low, 'maxMs': high, 'binWidthMs': 0.0,
                'counts': [len(values)]}
    width = (high - low) / buckets
    counts = [0] * buckets
    for value in values:
        index = int((value - low) / width)
        if index >= buckets:
            index = buckets - 1
        counts[index] += 1
    return {'bucketCount': buckets, 'minMs': low, 'maxMs': high,
            'binWidthMs': width, 'counts': counts}


def bounded_samples(values, limit=TICK_SAMPLE_LIMIT):
    count = len(values)
    if count <= limit:
        return [float(value) for value in values], 1
    stride = int(math.ceil(count / float(limit)))
    sampled = [float(value) for value in values[::stride][:limit]]
    return sampled, stride


def summarize_ticks(values, per_repeat):
    values = [float(value) for value in values]
    summary = distribution(values)
    repeat_rows = []
    for ticks in per_repeat:
        row = distribution([float(value) for value in ticks])
        repeat_rows.append({key: row[key] for key in
                            ('count', 'min', 'p50', 'p95', 'p99', 'max', 'mean', 'stdDev')})
    samples, stride = bounded_samples(values)
    summary.update({
        'kind': 'per-tick',
        'unit': 'ms/tick',
        'source': 'raw per-frame durations collected inside Lua with benchClock()',
        'timerCallsPerSample': 1,
        'timerOverheadIncluded': True,
        'perRepeat': repeat_rows,
        'histogram': histogram(values),
        'samplesMs': samples,
        'sampleStride': stride,
        'samplesBounded': True,
        'sampleLimit': TICK_SAMPLE_LIMIT,
    })
    return summary


def determinism_block(scheme, before, after):
    unique_before = len(set(before)) == 1
    unique_after = len(set(after)) == 1
    return {
        'scheme': scheme,
        'independent': 'fresh fixture/VM constructed for every repeat; build and warmup are outside the measured batch',
        'warmupExcludedFromMeasurement': True,
        'checkpointBeforeHashes': before,
        'checkpointAfterHashes': after,
        'identicalBefore': unique_before,
        'identicalAfter': unique_after,
        'checkpointFields': CHECKPOINT_FIELDS,
        'ok': unique_before and unique_after,
    }


def add_check(checks, name, ok, detail=None):
    checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
    return bool(ok)


NOOP_TIMER_LUA = r'''
function __benchFrame() end
function __benchPlainBatch(frames)
    local started = benchClock()
    for _ = 1, frames do __benchFrame() end
    return (benchClock() - started) * 1000 / frames
end
function __benchTickBatch(frames)
    __fi = 0
    local started = benchClock()
    local previous = started
    local ticks = {}
    for i = 1, frames do
        __benchFrame()
        local at = benchClock()
        ticks[i] = (at - previous) * 1000
        previous = at
    end
    local finished = benchClock()
    return {batchMeanMs = (finished - started) * 1000 / frames, tickMs = ticks, count = frames}
end
'''


def measure_timer_overhead(quick):
    """Measure the per-tick instrumentation cost.

    A no-op workload isolates the clock call plus sample bookkeeping exactly, so
    the micro number is not polluted by simulation-state drift. A small real
    scenario A/B run corroborates it end to end.
    """
    from test_link_runtime import environment
    iterations = 2000 if quick else 5000
    repetitions = 3 if quick else 5
    micro_deltas = []
    plain_micro = []
    tick_micro = []
    try:
        probe = environment()
        try:
            probe.globals().benchClock = time.perf_counter
            probe.execute(NOOP_TIMER_LUA)
            for repetition in range(repetitions):
                if repetition % 2 == 0:
                    plain = float(probe.eval('__benchPlainBatch(%d)' % iterations))
                    tick = float(probe.eval('__benchTickBatch(%d).batchMeanMs' % iterations))
                else:
                    tick = float(probe.eval('__benchTickBatch(%d).batchMeanMs' % iterations))
                    plain = float(probe.eval('__benchPlainBatch(%d)' % iterations))
                plain_micro.append(plain)
                tick_micro.append(tick)
                micro_deltas.append(tick - plain)
        finally:
            _close(probe)
        frames = 8 if quick else 12
        pairs = 1 if quick else 2
        e2e_plain = []
        e2e_tick = []
        e2e_deltas = []
        for _ in range(pairs):
            for instrumented in (False, True):
                lua = environment()
                try:
                    prepare_sp(lua, dict(id='timer-overhead', mode='authority',
                                         build=chain_scene(8), frame=STRAIGHT_FRAME, warmup=20))
                    expression = ('__benchTickBatch(%d).batchMeanMs' if instrumented
                                  else '__benchPlainBatch(%d)') % frames
                    value = float(lua.eval(expression))
                    (e2e_tick if instrumented else e2e_plain).append(value)
                finally:
                    _close(lua)
            e2e_deltas.append(e2e_tick[-1] - e2e_plain[-1])
    except Exception as error:
        return {'error': repr(error)}
    micro_deltas.sort()
    e2e_deltas.sort()
    micro = micro_deltas[len(micro_deltas) // 2]
    return {
        'method': 'no-op micro A/B (clock call + per-tick sample bookkeeping only) plus small real-scenario A/B',
        'micro': {
            'iterations': iterations,
            'repetitions': repetitions,
            'plainBatchMeanMs': plain_micro,
            'instrumentedBatchMeanMs': tick_micro,
            'deltaMsPerFrame': micro_deltas,
            'medianDeltaMsPerFrame': micro,
            'medianDeltaNsPerTick': micro * 1e6,
            'note': 'this is the per-frame cost added by collecting one raw tick sample',
        },
        'endToEnd': {
            'scenario': '8-body trailing chain, straight drive',
            'framesPerPair': frames,
            'pairs': pairs,
            'plainBatchMeanMs': e2e_plain,
            'instrumentedBatchMeanMs': e2e_tick,
            'deltaMsPerFrame': e2e_deltas,
            'note': 'corroboration only; scheduler noise dominates at real frame cost',
        },
        'note': 'subtract micro.medianDeltaMsPerFrame from tick means when comparing with plain batch means',
    }


def profile_sp(scenario, quick, factory):
    frames = int(scenario.get('profile_frames', 20 if not quick else 10))
    if frames <= 0 or scenario.get('no_profile'):
        return {'frames': 0, 'msPerFrame': None, 'phases': [],
                'note': 'profiling disabled'}
    lua = factory()
    try:
        prepare_sp(lua, scenario)
        phases = scenario.get('phases') or phases_for_mode(scenario['mode'])
        rows, per_frame = run_profiled(lua, phases, frames)
    finally:
        _close(lua)
    return {'frames': frames, 'msPerFrame': per_frame, 'phases': rows,
            'note': 'descriptive only: separate fresh fixture, phase wrappers add a clock call per invocation'}


def diagnostics_sp(scenario, quick, factory, with_diagnostics):
    if not with_diagnostics:
        return None
    frames = int(scenario.get('profile_frames', 10 if quick else 20))
    lua = factory()
    try:
        prepare_sp(lua, scenario)
        return diagnostics_snapshot(lua, max(1, frames))
    finally:
        _close(lua)


# ---------------------------------------------------------------------------
# Single-player scenario runner and validator.
# ---------------------------------------------------------------------------
def validate_sp(scenario, quick, factory, expected_backend, determinism):
    checks = []
    frames = int(scenario.get('validation_frames', 4 if quick else 6))
    dt_ms = int(scenario.get('dtMs', 50))
    expected_steps = expected_substeps(dt_ms)
    expected_work = scenario.get('expected_work') or {}
    lua = factory()
    try:
        prepare_sp(lua, scenario)
        run = to_py(lua.eval('__benchValidationRun(%d)' % frames))
        backend = to_py(lua.eval('__benchBackend()'))
    finally:
        _close(lua)
    stats = run.get('stats') or {}
    probe = run.get('probe') or {}
    states = run.get('states') or []
    final_state = run.get('finalState') or {}

    add_check(checks, 'backend', expected_backend in (None, 'any') or backend.get('name') == expected_backend,
              'expected=%s actual=%s version=%s' % (expected_backend, backend.get('name'), backend.get('version')))
    for key in ('bodies', 'links', 'groups', 'records'):
        expected = expected_work.get(key)
        actual = stats.get(key)
        add_check(checks, 'topology.' + key, expected is None or actual == expected,
                  'expected=%r actual=%r' % (expected, actual))
    expected_ticks = int(scenario.get('sim_ticks_per_frame', 1)) * frames
    add_check(checks, 'simulation.ticks', probe.get('simTicks') == expected_ticks,
              'expected=%d actual=%r (0 would mean a stopped simulation unless the frame does not run physics by design)'
              % (expected_ticks, probe.get('simTicks')))
    add_check(checks, 'simulation.error', final_state.get('error') in (False, None),
              'runtime.error=%r' % (final_state.get('error'),))
    if scenario.get('validate_substeps', True) and backend.get('name') == 'lua-reference':
        multi = int(stats.get('groupsWithMultipleRecords') or 0)
        single = int(stats.get('groups') or 0) - multi
        if multi:
            observed = (probe.get('groupCalls') or 0) / float(multi * frames)
            add_check(checks, 'substeps.multiRecordGroups', abs(observed - expected_steps) < 1e-6,
                      'expected=%d observed=%.6f groupCalls=%r' % (expected_steps, observed, probe.get('groupCalls')))
        if single:
            observed = (probe.get('coreCalls') or 0) / float(single * frames)
            add_check(checks, 'substeps.singleRecordGroups', abs(observed - expected_steps) < 1e-6,
                      'expected=%d observed=%.6f coreCalls=%r' % (expected_steps, observed, probe.get('coreCalls')))
        if not multi and not single:
            add_check(checks, 'substeps.noGroups', (probe.get('groupCalls') or 0) == 0 and (probe.get('coreCalls') or 0) == 0,
                      'no simulation groups')
    moved, travel = movement_summary(states)
    # Body displacement is reported for context but not used as a rejection
    # criterion: a slack chain or a blocked/back-pressure scenario can legitimately
    # show zero displacement while the solver still runs every substep. Stopped
    # simulation is detected by the tick/substep counters above instead.
    add_check(checks, 'determinism.repeatBefore', determinism.get('identicalBefore') is True,
              'hashes=%r' % (determinism.get('checkpointBeforeHashes'),))
    add_check(checks, 'determinism.repeatAfter', determinism.get('identicalAfter') is True,
              'hashes=%r' % (determinism.get('checkpointAfterHashes'),))
    return {
        'ok': all(check['ok'] for check in checks),
        'frames': frames,
        'checks': checks,
        'backend': backend,
        'stats': stats,
        'probe': probe,
        'expectedSubsteps': expected_steps,
        'expectedMotion': bool(scenario.get('expect_motion')),
        'bodiesMovedInValidation': moved,
        'bodyTravelInValidation': travel,
        'finalCalculating': final_state.get('calculating'),
    }


def movement_summary(states):
    if len(states) < 2:
        return 0, 0.0
    first = states[0].get('bodies') or []
    last = states[-1].get('bodies') or []
    moved = 0
    travel = 0.0
    for index in range(min(len(first), len(last))):
        a = first[index]
        b = last[index]
        delta = (abs(a.get('x', 0.0) - b.get('x', 0.0))
                 + abs(a.get('y', 0.0) - b.get('y', 0.0))
                 + abs(a.get('angle', 0.0) - b.get('angle', 0.0)))
        if delta > 1e-9:
            moved += 1
        travel += delta
    return moved, travel


def run_sp_scenario(scenario, quick, with_diagnostics, fixture_factory=None, expected_backend=None):
    mode = scenario['mode']
    factory = fixture_factory or sp_fixture(mode)
    repeats = scenario_repeats(scenario)
    frames = int(scenario['frames'])
    warmup = int(scenario.get('warmup', 0))
    expected_backend = expected_backend or scenario.get('expected_backend') or DEFAULT_EXPECTED_BACKEND
    batch_values = []
    tick_values = []
    per_repeat_ticks = []
    before_hashes = []
    after_hashes = []
    seed = None
    stats_last = None
    backend_last = None
    for _ in range(repeats):
        lua = factory()
        try:
            seed = prepare_sp(lua, scenario)
            before_hashes.append(digest_text(lua.eval('__benchCheckpoint()')))
            measured = to_py(lua.eval('__benchTickBatch(%d)' % frames))
            batch_values.append(float(measured['batchMeanMs']))
            ticks = [float(value) for value in measured['tickMs']]
            tick_values.extend(ticks)
            per_repeat_ticks.append(ticks)
            after_hashes.append(digest_text(lua.eval('__benchCheckpoint()')))
            stats_last = evaluate_stats(lua, scenario.get('extra'))
            backend_last = to_py(lua.eval('__benchBackend()'))
        finally:
            _close(lua)
    determinism = determinism_block('fresh-sp-fixture-per-repeat', before_hashes, after_hashes)
    validation = validate_sp(scenario, quick, factory, expected_backend, determinism)
    profile = profile_sp(scenario, quick, factory)
    diagnostics = diagnostics_sp(scenario, quick, factory, with_diagnostics)
    return {
        'id': scenario['id'],
        'mode': mode,
        'kind': scenario['kind'],
        'description': scenario['description'],
        'backend': backend_last,
        'setup': {
            'fixture': mode,
            'dtMs': int(scenario.get('dtMs', 50)),
            'substepsPerFrame': expected_substeps(int(scenario.get('dtMs', 50))),
            'seed': seed,
            'expectedWork': scenario.get('expected_work'),
            'repeatScheme': 'fresh fixture per repeat; setup/build/warmup excluded from the measured batch',
        },
        'executedRepeats': repeats,
        'measuredFramesPerRepeat': frames,
        'warmupFrames': warmup,
        'batchMeanMs': summarize_batch(batch_values),
        'tickMs': summarize_ticks(tick_values, per_repeat_ticks),
        'determinism': determinism,
        'validation': validation,
        'stats': stats_last,
        'profile': profile,
        'diagnostics': diagnostics,
    }


def run_authority_scenario(scenario, quick, with_diagnostics, fixture_factory=None, expected_backend=None):
    return run_sp_scenario(scenario, quick, with_diagnostics, fixture_factory, expected_backend)


def run_presentation_scenario(scenario, quick, with_diagnostics, fixture_factory=None, expected_backend=None):
    return run_sp_scenario(scenario, quick, with_diagnostics, fixture_factory, expected_backend)


def run_client_scenario(scenario, quick, with_diagnostics, fixture_factory=None, expected_backend=None):
    return run_sp_scenario(scenario, quick, with_diagnostics, fixture_factory, expected_backend)


# ---------------------------------------------------------------------------
# MP model: every measured frame interleaves server tick, server packet
# delivery, client ticks and client-to-server delivery. Delivery time is part of
# the frame measurement and is also reported separately.
# ---------------------------------------------------------------------------
MP_SETUP_LUA = r'''
function __mpBuild()
    local positions = {}
    for i = 1, 8 do
        local b = corpse()
        b.netID = tostring(200 + i)
        b.md.CVPBodyKey = 'mp-body-' .. i
        b.getSquare = body.getSquare
        b.setSquare = body.setSquare
        b.getStaticMovingObjectIndex = body.getStaticMovingObjectIndex
        b.getAngle = body.getAngle
        -- Chain trails behind the vehicle anchor (car at x=2) so the forward
        -- drive keeps every rope taut and the bodies actually move.
        local x = -1 - (i - 1) * 3
        gridSquare(math.floor(x), 0, 0):addCorpse(b)
        b.x = x; b.y = 0; b.z = 0; b.sq = gridSquare(math.floor(x), 0, 0)
        positions[i] = b
    end
    __all = {}
    for i = 1, 8 do __all[i] = positions[i] end
    H.discover()
    local previous = C
    for i = 1, 8 do
        local endpoint = {kind = 'body', key = __all[i].md.CVPBodyKey, point = 'feet'}
        local gear = item('Base.Rope'); storage:AddItem(gear)
        link(previous, endpoint, gear)
        previous = endpoint
    end
end
'''

MP_CLIENT_BODIES_LUA = r'''
function __mpClientBuild()
    local rows = {}
    for i = 1, 8 do
        local b = corpse()
        b.netID = tostring(200 + i)
        b.md.CVPBodyKey = 'mp-body-' .. i
        b.getSquare = body.getSquare
        b.setSquare = body.setSquare
        b.getStaticMovingObjectIndex = body.getStaticMovingObjectIndex
        b.getAngle = body.getAngle
        local x = -1 - (i - 1) * 3
        gridSquare(math.floor(x), 0, 0):addCorpse(b)
        b.x = x; b.y = 0; b.z = 0; b.sq = gridSquare(math.floor(x), 0, 0)
        rows[i] = b
    end
    __all = rows
end
'''

MP_PHASE_LUA = r'''
__phaseRows = {}
__phaseRestore = {}
function __benchPhaseBegin(hooks)
    __phaseRows = {}
    __phaseRestore = {}
    for _, hook in ipairs(hooks) do
        local owner = assert(loadstring('return ' .. hook.target))()
        local original = owner[hook.key]
        if type(original) == 'function' then
            local row = {name = hook.name, calls = 0, ms = 0}
            __phaseRows[#__phaseRows + 1] = row
            local wrapper = function(...)
                local started = benchClock()
                local a, b, c = original(...)
                row.ms = row.ms + (benchClock() - started) * 1000
                row.calls = row.calls + 1
                return a, b, c
            end
            local hadRaw = rawget(owner, hook.key) ~= nil
            __phaseRestore[#__phaseRestore + 1] = {owner = owner, key = hook.key, original = original, hadRaw = hadRaw}
            owner[hook.key] = wrapper
        end
    end
    return #__phaseRows
end
function __benchPhaseEnd()
    for _, entry in ipairs(__phaseRestore) do
        if entry.hadRaw then entry.owner[entry.key] = entry.original
        else entry.owner[entry.key] = nil end
    end
    __phaseRestore = {}
    return __phaseRows
end
'''

MP_ADD_LUA = r'''
local function __num(value)
    if value ~= value then return 'nan' end
    if value == math.huge then return 'inf' end
    if value == -math.huge then return '-inf' end
    return string.format('%.17g', value)
end
function __mpAdd(rows, key, value)
    if value == nil then return end
    local kind = type(value)
    if kind == 'number' then rows[#rows + 1] = key .. '=' .. __num(value)
    elseif kind == 'string' or kind == 'boolean' then rows[#rows + 1] = key .. '=' .. tostring(value)
    else rows[#rows + 1] = key .. '=<' .. kind .. '>' end
end
function __mpAddBodies(rows, prefix)
    for i, b in ipairs(__all or {}) do
        __mpAdd(rows, prefix .. i .. '.x', b.x)
        __mpAdd(rows, prefix .. i .. '.y', b.y)
        __mpAdd(rows, prefix .. i .. '.z', b.z or 0)
        if b.getAngle then __mpAdd(rows, prefix .. i .. '.angle', b:getAngle()) end
    end
end
function __mpBodyTable()
    local bodies = {}
    for i, b in ipairs(__all or {}) do
        bodies[i] = {x = b.x, y = b.y, z = b.z or 0,
            angle = b.getAngle and b:getAngle() or 0, world = b.world ~= false}
    end
    return bodies
end
'''

MP_SERVER_COMMON = MP_PHASE_LUA + MP_ADD_LUA + r'''
function __benchServerFrame()
    now = now + 100
    car.x = car.x + (__benchMotion or 0)
    CVPMPServer.tick()
end
function __benchFrame() __benchServerFrame() end
function __benchPlainBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do __benchServerFrame() end
    return (benchClock() - started) * 1000 / frames
end
function __benchWarm(frames)
    for _ = 1, frames do __benchServerFrame() end
    return true
end
function __benchStats()
    local groups, records, multi = 0, 0, 0
    for _, group in ipairs(R.simulation.groups) do
        groups = groups + 1
        records = records + #group.records
        if #group.records > 1 then multi = multi + 1 end
    end
    local links = 0
    for _ in pairs(R.service.graph.links) do links = links + 1 end
    return {links = links, groups = groups, records = records,
        groupsWithMultipleRecords = multi, bodies = __all and #__all or 0}
end
function __benchBackend()
    local native = CVPSolverNative
    local useLua = (not native) or (not not CVPSolverUseLua)
    local name
    if useLua then name = 'lua-reference'
    elseif type(native.solvePersistent) == 'function' then name = 'java-persistent'
    else name = 'java-nonpersistent' end
    local version
    if native and type(native.version) == 'function' then
        local ok, value = pcall(native.version)
        if ok then version = tostring(value) end
    end
    return {name = name, native = native ~= nil,
        solvePersistent = native ~= nil and type(native.solvePersistent) == 'function',
        useLuaOverride = not not CVPSolverUseLua, version = version}
end
function __mpCheckpoint()
    local rows = {}
    __mpAdd(rows, 'now', now)
    __mpAdd(rows, 'car.x', car.x)
    __mpAdd(rows, 'car.y', car.y)
    __mpAddBodies(rows, 'body.')
    local graph = R.service.graph
    local ids = {}
    for id in pairs(graph.links) do ids[#ids + 1] = tostring(id) end
    table.sort(ids)
    for _, id in ipairs(ids) do
        local row = graph.links[id]
        __mpAdd(rows, 'link.' .. id .. '.revision', row.revision)
        for _, side in ipairs({'a', 'b'}) do
            local endpoint = row[side]
            if endpoint then
                __mpAdd(rows, 'link.' .. id .. '.' .. side .. '.kind', endpoint.kind)
                __mpAdd(rows, 'link.' .. id .. '.' .. side .. '.key', endpoint.key)
                __mpAdd(rows, 'link.' .. id .. '.' .. side .. '.x', endpoint.x)
                __mpAdd(rows, 'link.' .. id .. '.' .. side .. '.y', endpoint.y)
            end
        end
    end
    local sim = R.simulation
    local recordIds = {}
    for id in pairs(sim.records) do recordIds[#recordIds + 1] = tostring(id) end
    table.sort(recordIds)
    for _, id in ipairs(recordIds) do
        local r = sim.records[id]
        for _, field in ipairs({'x', 'y', 'angle', 'vx', 'vy', 'angularVelocity', 'takeup',
                'ax', 'ay', 'length', 'loadMass', 'reaction', 'taut', 'blocked', 'failed'}) do
            __mpAdd(rows, 'rec.' .. id .. '.' .. field, r[field])
        end
    end
    __mpAdd(rows, 'mp.sequence', CVPMPServer.sequence)
    __mpAdd(rows, 'mp.epoch', CVPMPServer.epoch)
    __mpAdd(rows, 'runtime.error', R.error and tostring(R.error) or 'nil')
    __mpAdd(rows, 'uuidSequence', uuidSequence)
    return table.concat(rows, '\n')
end
function __mpProbe()
    local stats = __benchStats()
    stats.sequence = CVPMPServer.sequence
    stats.now = now
    stats.bodyList = __mpBodyTable()
    stats.error = R.error and tostring(R.error) or false
    return stats
end
'''

MP_CLIENT_COMMON = MP_PHASE_LUA + MP_ADD_LUA + r'''
function __benchClientFrame()
    now = now + 100
    CVPMPClient.tick()
end
function __benchFrame() __benchClientFrame() end
function __benchPlainBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do __benchClientFrame() end
    return (benchClock() - started) * 1000 / frames
end
function __benchWarm(frames)
    for _ = 1, frames do __benchClientFrame() end
    return true
end
function __benchStats()
    local links = 0
    if CVPMPClient.graph then
        for _ in pairs(CVPMPClient.graph.links or {}) do links = links + 1 end
    end
    local rows, resolved = 0, 0
    for _ in pairs(CVPMPClient.rows or {}) do rows = rows + 1 end
    for _, row in pairs(CVPMPClient.rows or {}) do if row.body then resolved = resolved + 1 end end
    local display = 0
    for _ in pairs((CVPMPClient.host and CVPMPClient.host.displayBodies) or {}) do display = display + 1 end
    local drawnCount = 0
    if drawn then for _ in pairs(drawn) do drawnCount = drawnCount + 1 end end
    return {links = links, rows = rows, resolvedRows = resolved, displayBodies = display,
        drawn = drawnCount, ready = CVPMPClient.ready == true,
        ageMs = now - (CVPMPClient.lastState or 0),
        sequence = CVPMPClient.sequence,
        revision = CVPMPClient.graph and CVPMPClient.graph.revision or nil,
        bodies = __all and #__all or 0}
end
function __mpCheckpoint()
    local rows = {}
    __mpAdd(rows, 'now', now)
    __mpAdd(rows, 'car.x', car.x)
    __mpAdd(rows, 'car.y', car.y)
    __mpAddBodies(rows, 'body.')
    __mpAdd(rows, 'client.sequence', CVPMPClient.sequence)
    __mpAdd(rows, 'client.lastState', CVPMPClient.lastState)
    __mpAdd(rows, 'client.ready', CVPMPClient.ready == true)
    __mpAdd(rows, 'client.epoch', CVPMPClient.epoch)
    __mpAdd(rows, 'client.session', CVPMPClient.session)
    __mpAdd(rows, 'client.revision', CVPMPClient.graph and CVPMPClient.graph.revision or nil)
    local rowsCount = 0
    for _ in pairs(CVPMPClient.rows or {}) do rowsCount = rowsCount + 1 end
    __mpAdd(rows, 'client.rows', rowsCount)
    local loadsCount = 0
    for _ in pairs(CVPMPClient.loads or {}) do loadsCount = loadsCount + 1 end
    __mpAdd(rows, 'client.loads', loadsCount)
    local clock = CVPMPClient.motionClock
    if type(clock) == 'table' then
        local keys = {}
        for key, value in pairs(clock) do
            if type(value) == 'number' or type(value) == 'string' then keys[#keys + 1] = tostring(key) end
        end
        table.sort(keys)
        for _, key in ipairs(keys) do __mpAdd(rows, 'clock.' .. key, clock[key]) end
    end
    __mpAdd(rows, 'uuidSequence', uuidSequence)
    return table.concat(rows, '\n')
end
function __mpProbe()
    local stats = __benchStats()
    stats.now = now
    stats.bodyList = __mpBodyTable()
    stats.error = CVPMPClient.error and tostring(CVPMPClient.error) or false
    return stats
end
'''


_MP_TAKE = None


def mp_take(target, name):
    global _MP_TAKE
    if _MP_TAKE is None:
        from test_link_multiplayer import take as take_helper
        _MP_TAKE = take_helper
    return _MP_TAKE(target, name)


def mp_deliver_server(network, drop_state=None):
    packets = mp_take(network.server, 'packets')
    delivered = 0
    dropped = 0
    for packet in packets:
        if drop_state is not None and packet.get('name') in ('state', 'motion') and drop_state(packet):
            dropped += 1
            continue
        network.receive(packet)
        delivered += 1
    server_car = network.server.globals().car
    for client in network.clients.values():
        car = client.globals().car
        car.x = server_car.x
        car.y = server_car.y
        car.z = server_car.z
    container = mp_take(network.server, 'containerPackets')
    for packet in container:
        client = network.clients[packet['who']]
        client.globals().nativePacket = client.table_from(packet)
        client.execute('''
            local inv = localPlayer:getInventory()
            if nativePacket.kind == 'remove' then
                local item = inv:getItemWithIDRecursiv(nativePacket.id)
                if item then item:getContainer():Remove(item) end
            else
                local item = equipmentDecode(nativePacket.payload)
                inv:AddItem(item)
            end
        ''')
    return {'serverPackets': len(packets), 'delivered': delivered, 'dropped': dropped,
            'containerPackets': len(container)}


def mp_deliver_clients(network):
    total = 0
    for name, client in network.clients.items():
        requests = mp_take(client, 'clientPackets')
        total += len(requests)
        if not requests:
            continue
        server = network.server
        player = server.globals().player if name == 'owner' else server.globals().player2
        local = client.globals().localPlayer
        player.x = local.x
        player.y = local.y
        player.z = local.z
        for request in requests:
            network.send(request)
    return {'clientRequests': total}


def build_mp_network(scenario, motion):
    from test_link_multiplayer import Network
    network = Network()
    server = network.server
    server.globals().benchClock = time.perf_counter
    for client in network.clients.values():
        client.globals().benchClock = time.perf_counter
    server.execute(MP_SETUP_LUA)
    server.execute('__mpBuild()')
    for client in network.clients.values():
        client.execute(MP_CLIENT_BODIES_LUA)
        client.execute('__mpClientBuild()')
    network.publish()
    server.execute(MP_SERVER_COMMON)
    for client in network.clients.values():
        client.execute(MP_CLIENT_COMMON)
    server.execute('__benchMotion = %r' % float(motion))
    return network


def mp_frame(network, drop_state=None):
    pc = time.perf_counter
    started = pc()
    network.server.eval('__benchServerFrame()')
    after_server = pc()
    delivery = mp_deliver_server(network, drop_state)
    after_server_delivery = pc()
    network.clients['owner'].eval('__benchClientFrame()')
    after_owner = pc()
    network.clients['friend'].eval('__benchClientFrame()')
    after_friend = pc()
    requests = mp_deliver_clients(network)
    finished = pc()
    return {
        'frameMs': (finished - started) * 1000.0,
        'serverMs': (after_server - started) * 1000.0,
        'ownerMs': (after_owner - after_server_delivery) * 1000.0,
        'friendMs': (after_friend - after_owner) * 1000.0,
        'serverDeliveryMs': (after_server_delivery - after_server) * 1000.0,
        'clientDeliveryMs': (finished - after_friend) * 1000.0,
        'serverPackets': delivery['serverPackets'],
        'deliveredPackets': delivery['delivered'],
        'droppedPackets': delivery['dropped'],
        'clientRequests': requests['clientRequests'],
    }


def mp_checkpoint(network):
    parts = {'server': network.server.eval('__mpCheckpoint()')}
    for name, client in network.clients.items():
        parts[name] = client.eval('__mpCheckpoint()')
    return {
        'parts': {name: digest_text(text) for name, text in parts.items()},
        'combined': digest_text(json.dumps({name: digest_text(text) for name, text in parts.items()},
                                           sort_keys=True)),
    }


class DropEveryOther(object):
    """Deterministic per-client state/motion loss for the labelled loss scenario."""

    def __init__(self, period=2):
        self.period = period
        self.counts = {}

    def __call__(self, packet):
        who = packet.get('who')
        index = self.counts.get(who, 0) + 1
        self.counts[who] = index
        return index % self.period == 0


def validate_mp(scenario, quick, expected_backend):
    variant = scenario.get('variant', 'live')
    motion = 0.05 if variant in ('live', 'loss') else 0.0
    frames = int(scenario.get('validation_frames', 8 if quick else 12))
    warmup = int(scenario.get('warmup', 10))
    expected_work = scenario.get('expected_work') or {}
    drop = DropEveryOther() if variant == 'loss' else None
    checks = []
    network = build_mp_network(scenario, motion)
    try:
        backend = to_py(network.server.eval('__benchBackend()'))
        for _ in range(warmup):
            mp_frame(network, drop)
        previous = {}
        for name, client in network.clients.items():
            previous[name] = to_py(client.eval('__mpProbe()')).get('bodyList') or []
        updates = {name: 0 for name in network.clients}
        max_age = {name: 0 for name in network.clients}
        presentation_frames = {name: 0 for name in network.clients}
        ready_frames = {name: 0 for name in network.clients}
        dropped_total = 0
        delivered_total = 0
        client_probe_last = {}
        server_probe_last = None
        server_sequence_start = to_py(network.server.eval('__mpProbe()')).get('sequence')
        server_previous = None
        server_updates = 0
        for _ in range(frames):
            sample = mp_frame(network, drop)
            dropped_total += sample['droppedPackets']
            delivered_total += sample['deliveredPackets']
            server_probe = to_py(network.server.eval('__mpProbe()'))
            server_probe_last = server_probe
            current = server_probe.get('bodyList') or []
            if server_previous is not None:
                for index in range(min(len(server_previous), len(current))):
                    a = server_previous[index]
                    b = current[index]
                    if (abs(a.get('x', 0.0) - b.get('x', 0.0)) + abs(a.get('y', 0.0) - b.get('y', 0.0))) > 1e-9:
                        server_updates += 1
            server_previous = current
            for name, client in network.clients.items():
                probe = to_py(client.eval('__mpProbe()'))
                client_probe_last[name] = probe
                age = probe.get('ageMs')
                if age is not None:
                    max_age[name] = max(max_age[name], float(age))
                if probe.get('ready') is True:
                    ready_frames[name] += 1
                if (probe.get('displayBodies') or 0) > 0 or (probe.get('drawn') or 0) > 0:
                    presentation_frames[name] += 1
                current = probe.get('bodyList') or []
                for index in range(min(len(previous[name]), len(current))):
                    a = previous[name][index]
                    b = current[index]
                    if (abs(a.get('x', 0.0) - b.get('x', 0.0)) + abs(a.get('y', 0.0) - b.get('y', 0.0))) > 1e-9:
                        updates[name] += 1
                previous[name] = current
        stats = to_py(network.server.eval('__benchStats()'))
        client_names = list(network.clients)
    finally:
        _close(network.server)
        for client in network.clients.values():
            _close(client)
        del network
        gc.collect()

    add_check(checks, 'backend', expected_backend in (None, 'any') or backend.get('name') == expected_backend,
              'expected=%s actual=%s version=%s' % (expected_backend, backend.get('name'), backend.get('version')))
    for key in ('bodies', 'links', 'groups', 'records'):
        expected = expected_work.get(key)
        add_check(checks, 'server.topology.' + key, expected is None or stats.get(key) == expected,
                  'expected=%r actual=%r' % (expected, stats.get(key)))
    add_check(checks, 'simulation.serverTicks', (server_probe_last or {}).get('now') is not None,
              'server authority ran during every measured validation frame')
    sequence_end = (server_probe_last or {}).get('sequence')
    add_check(checks, 'simulation.serverSequenceAdvanced',
              server_sequence_start is None or sequence_end is None or sequence_end > server_sequence_start,
              'sequence %r -> %r' % (server_sequence_start, sequence_end))
    if variant in ('live', 'loss'):
        add_check(checks, 'simulation.serverBodyMotion', server_updates > 0,
                  'serverBodyPoseUpdates=%d over %d frames' % (server_updates, frames))
    add_check(checks, 'delivery.packets', delivered_total > 0,
              'delivered=%d dropped=%d' % (delivered_total, dropped_total))
    if variant == 'loss':
        add_check(checks, 'delivery.lossApplied', dropped_total > 0,
                  'dropped=%d of delivered+? state/motion packets' % (dropped_total,))
    client_stats = {}
    for name in client_names:
        probe = client_probe_last.get(name) or {}
        client_stats[name] = probe
        expected_links = expected_work.get('links')
        add_check(checks, name + '.ready', probe.get('ready') is True, 'ready=%r' % (probe.get('ready'),))
        add_check(checks, name + '.freshness', max_age[name] <= 3000,
                  'maxAgeMs=%.3f (client body updates stop when >3000 ms stale)' % (max_age[name],))
        add_check(checks, name + '.graph', expected_links is None or probe.get('links') == expected_links,
                  'expected=%r actual=%r' % (expected_links, probe.get('links')))
        expected_bodies = expected_work.get('bodies')
        add_check(checks, name + '.bodies', expected_bodies is None or probe.get('bodies') == expected_bodies,
                  'expected=%r actual=%r' % (expected_bodies, probe.get('bodies')))
        add_check(checks, name + '.rowsResolved',
                  (probe.get('rows') or 0) > 0 and probe.get('rows') == probe.get('resolvedRows'),
                  'rows=%r resolved=%r' % (probe.get('rows'), probe.get('resolvedRows')))
        add_check(checks, name + '.activePresentation', presentation_frames[name] > 0,
                  'framesWithPresentation=%d displayBodies=%r drawn=%r'
                  % (presentation_frames[name], probe.get('displayBodies'), probe.get('drawn')))
        if variant in ('live', 'loss'):
            add_check(checks, name + '.updatedBodies', updates[name] > 0,
                      'bodyPoseUpdates=%d over %d frames' % (updates[name], frames))
        add_check(checks, name + '.readyFrames', ready_frames[name] > 0,
                  'readyFrames=%d/%d' % (ready_frames[name], frames))
        distances = body_distances(probe.get('bodyList') or [], (server_probe_last or {}).get('bodyList') or [])
        add_check(checks, name + '.convergence', distances['max'] <= 1.0,
                  'maxClientServerBodyDistance=%.6f (interpolation delay allowed)'
                  % (distances['max'],))
    return {
        'ok': all(check['ok'] for check in checks),
        'frames': frames,
        'checks': checks,
        'backend': backend,
        'serverStats': stats,
        'clientStats': client_stats,
        'freshnessMaxAgeMs': max_age,
        'updatedBodies': updates,
        'presentationFrames': presentation_frames,
        'readyFrames': ready_frames,
        'deliveredPackets': delivered_total,
        'droppedPackets': dropped_total,
        'serverBodyUpdates': server_updates,
        'serverSequence': {'start': server_sequence_start, 'end': sequence_end},
    }


def body_distances(client_bodies, server_bodies):
    maximum = 0.0
    count = min(len(client_bodies), len(server_bodies))
    for index in range(count):
        a = client_bodies[index]
        b = server_bodies[index]
        delta = math.sqrt((a.get('x', 0.0) - b.get('x', 0.0)) ** 2
                          + (a.get('y', 0.0) - b.get('y', 0.0)) ** 2)
        maximum = max(maximum, delta)
    return {'max': maximum, 'count': count}


def profile_mp(network, quick):
    frames = 10 if quick else 20
    roles = []
    for name, target, phases in (
            ('server', network.server, MP_SERVER_PHASES),
            ('owner', network.clients['owner'], MP_CLIENT_PHASES),
            ('friend', network.clients['friend'], MP_CLIENT_PHASES)):
        target.globals().benchClock = time.perf_counter
        rows, per_frame = run_profiled(target, phases, frames)
        roles.append({'id': 'mp.profile.' + name, 'msPerFrame': per_frame, 'phases': rows})
    return {'frames': frames, 'roles': roles,
            'note': 'descriptive only: sequential role passes on one fresh network (state advances between roles); '
                    'delivery not included; not comparable to interleaved frameMs'}


def run_mp_scenario(scenario, quick, with_diagnostics, expected_backend=None, validation_frames=None):
    variant = scenario.get('variant', 'live')
    motion = 0.05 if variant in ('live', 'loss') else 0.0
    repeats = scenario_repeats(scenario)
    frames = int(scenario['frames'])
    warmup = int(scenario.get('warmup', 0))
    expected_backend = expected_backend or scenario.get('expected_backend') or DEFAULT_EXPECTED_BACKEND
    role_keys = {'server': 'serverMs', 'owner': 'ownerMs', 'friend': 'friendMs'}
    role_ticks = {role: [] for role in role_keys}
    role_per_repeat = {role: [] for role in role_keys}
    frame_values = []
    frame_per_repeat = []
    delivery_server = []
    delivery_client = []
    delivery_server_per_repeat = []
    delivery_client_per_repeat = []
    before_hashes = []
    after_hashes = []
    totals = {'serverPackets': 0, 'delivered': 0, 'dropped': 0, 'clientRequests': 0}
    stats_last = {}
    backend_last = None
    for _ in range(repeats):
        network = build_mp_network(scenario, motion)
        try:
            for _ in range(warmup):
                mp_frame(network, None)
            before_hashes.append(mp_checkpoint(network)['combined'])
            repeat_ticks = {role: [] for role in role_keys}
            repeat_frames = []
            repeat_delivery_server = []
            repeat_delivery_client = []
            drop = DropEveryOther() if variant == 'loss' else None
            for _ in range(frames):
                sample = mp_frame(network, drop)
                repeat_frames.append(sample['frameMs'])
                delivery_server.append(sample['serverDeliveryMs'])
                delivery_client.append(sample['clientDeliveryMs'])
                repeat_delivery_server.append(sample['serverDeliveryMs'])
                repeat_delivery_client.append(sample['clientDeliveryMs'])
                for role, key in role_keys.items():
                    repeat_ticks[role].append(sample[key])
                totals['serverPackets'] += sample['serverPackets']
                totals['delivered'] += sample['deliveredPackets']
                totals['dropped'] += sample['droppedPackets']
                totals['clientRequests'] += sample['clientRequests']
            after_hashes.append(mp_checkpoint(network)['combined'])
            frame_values.extend(repeat_frames)
            frame_per_repeat.append(repeat_frames)
            delivery_server_per_repeat.append(repeat_delivery_server)
            delivery_client_per_repeat.append(repeat_delivery_client)
            for role in role_keys:
                role_ticks[role].extend(repeat_ticks[role])
                role_per_repeat[role].append(repeat_ticks[role])
            backend_last = to_py(network.server.eval('__benchBackend()'))
            stats_last = {'server': evaluate_stats(network.server)}
            for name, client in network.clients.items():
                stats_last[name] = evaluate_stats(client)
        finally:
            _close(network.server)
            for client in network.clients.values():
                _close(client)
            del network
            gc.collect()
    determinism = determinism_block('fresh-mp-network-per-repeat', before_hashes, after_hashes)
    validation_scenario = dict(scenario)
    if validation_frames is not None:
        validation_scenario['validation_frames'] = int(validation_frames)
    validation = validate_mp(validation_scenario, quick, expected_backend)
    profile_frames = int(scenario.get('profile_frames', 10 if quick else 20))
    if scenario.get('no_profile') or profile_frames <= 0:
        profile = {'frames': 0, 'roles': [], 'note': 'profiling disabled'}
        diagnostics = None
    else:
        profile_network = build_mp_network(scenario, motion)
        try:
            for _ in range(warmup):
                mp_frame(profile_network, None)
            profile = profile_mp(profile_network, quick)
            diagnostics = (diagnostics_snapshot(profile_network.server, 10 if quick else 20)
                           if with_diagnostics else None)
        finally:
            _close(profile_network.server)
            for client in profile_network.clients.values():
                _close(client)
            del profile_network
            gc.collect()
    roles = []
    for role in role_keys:
        roles.append({
            'id': scenario['id'] + '.' + role,
            'role': role,
            'description': 'MP 2-client fixture, 8-body chain, %s Lua handling only' % role,
            'ownTickMs': summarize_ticks(role_ticks[role], role_per_repeat[role]),
            'batchMeanMs': summarize_batch([sum(ticks) / len(ticks) for ticks in role_per_repeat[role]]),
            'stats': stats_last.get(role),
        })
    return {
        'id': scenario['id'],
        'mode': 'mp',
        'kind': scenario['kind'],
        'variant': variant,
        'description': scenario['description'],
        'backend': backend_last,
        'setup': {
            'fixture': 'mp-network',
            'dtMs': int(scenario.get('dtMs', 100)),
            'substepsPerFrame': expected_substeps(int(scenario.get('dtMs', 100))),
            'clients': ['owner', 'friend'],
            'expectedWork': scenario.get('expected_work'),
            'repeatScheme': 'fresh MP network (one server + two client VMs) per repeat; setup/build/warmup excluded',
            'delivery': 'every frame interleaves server tick, server->client packets, client ticks, client->server packets',
        },
        'executedRepeats': repeats,
        'measuredFramesPerRepeat': frames,
        'warmupFrames': warmup,
        'frameMs': summarize_ticks(frame_values, frame_per_repeat),
        'frameBatchMeanMs': summarize_batch([sum(values) / len(values) for values in frame_per_repeat]),
        'delivery': {
            'serverToClients': summarize_ticks(delivery_server, delivery_server_per_repeat),
            'clientsToServer': summarize_ticks(delivery_client, delivery_client_per_repeat),
            'packets': totals,
            'note': 'delivery is included in frameMs; these fields keep its cost separately measurable',
        },
        'determinism': determinism,
        'roles': roles,
        'validation': validation,
        'profile': profile,
        'diagnostics': diagnostics,
    }


# ---------------------------------------------------------------------------
# Protocol, limitations and report output.
# ---------------------------------------------------------------------------
def protocol_block(quick):
    return {
        'clock': 'Python time.perf_counter injected into Lua; per-frame batches timed inside Lua',
        'tickTimer': 'one benchClock() call per measured frame, outside the mod frame body; '
                     'no Python timer inside tether()/solver calls',
        'batchMean': 'per repeat: (batch elapsed)/(frames); the distribution across repeats is batchMeanMs',
        'tickPercentiles': 'p50/p95/p99 are computed from raw per-frame samples in tickMs; '
                           'never derived from batch means',
        'timerOverhead': 'measured separately: no-op micro A/B for the clock call plus a small real-scenario A/B',
        'repeats': 'fresh fixture/VM per repeat with the same seed/build/warmup; setup and warmup outside the batch',
        'determinism': 'checkpoint hashes after warmup and after measured frames must match across repeats',
        'phaseClock': 'same clock; inclusive nested timings must not be summed',
        'dt': 'authority SP model: 50 ms per frame (5 substeps); MP model: 100 ms per frame (10 substeps)',
        'backend': 'recorded per run (lua-reference/java-persistent/java-nonpersistent); rejected when unexpected',
        'mpDelivery': 'MP measured frames include Python packet delivery; delivery cost is also reported per phase',
        'quickMode': quick,
        'quickVsFull': 'quick mode aggressively scales frame counts/warmups; compare quick runs only against quick runs '
                       'and full runs only against full runs made with the same bench hash',
        'scope': 'Lua model only: Python engine fixture, no Kahlua, Java JAR, Bullet solver or rendering',
    }


LIMITATIONS = [
    'Offline lupa Lua 5.1 model, not Project Zomboid/Kahlua and not in-game FPS. '
    'The game runs Kahlua with a Java JAR; engine calls are Python/table stand-ins here.',
    'Engine fixture replaces Bullet, the Java solver and the renderer with plain Lua/Python tables; '
    'relative Lua-side changes are meaningful, absolute game cost is not.',
    'The offline fixture does not provide CVPSolverNative, so measured runs are expected to report '
    'lua-reference. java-persistent/java-nonpersistent can be recorded/validated but cannot be measured here.',
    'The fixture persistence layer serializes equipment through Python JSON; save.flush timing '
    'includes that model and is not representative of the game write path.',
    'MP runs use the two-client offline fixture. Packet delivery is a Python pump between Lua VMs: its cost is '
    'included in frame timings and reported separately, but it is not a network-latency or real-transport model.',
    'MP state loss drops every second server state/motion packet deterministically; it models stale/lost snapshots, '
    'not transport reordering, jitter or bandwidth limits.',
    'Per-tick samples include one Python clock call per frame (measured overhead); subtract the reported '
    'overhead when comparing tick means to plain batch means.',
    'os-level scheduling noise exists. Compare same-machine, same-protocol, same-bench-hash runs only; '
    'repeats show variance and determinism is proven by checkpoint hashes, not by timing equality.',
    'Phase profiling adds a clock call per invocation and runs on a separate fresh fixture; it is descriptive only.',
]


def summarize_validation(document):
    checks = []
    for scenario in document['scenarios']:
        validation = scenario.get('validation')
        if validation:
            checks.extend(validation.get('checks') or [])
    failed = [check for check in checks if not check.get('ok')]
    return {'checks': len(checks), 'failed': len(failed), 'ok': not failed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', required=True, help='output directory for raw.json and README.md')
    parser.add_argument('--phase', default='baseline', choices=['baseline', 'after', 'adhoc'])
    parser.add_argument('--label', default='', help='free-form run label')
    parser.add_argument('--quick', action='store_true', help='shorter protocol for smoke checks')
    parser.add_argument('--only', default='', help='comma-separated scenario ids to run')
    parser.add_argument('--no-mp', action='store_true', help='skip the MP two-client fixture scenarios')
    parser.add_argument('--no-profile', action='store_true', help='skip per-phase profiling')
    parser.add_argument('--diagnostics', action='store_true', help='collect CVP_Diagnostics snapshots')
    parser.add_argument('--write-readme', action='store_true', help='write a README.md with conditions and the result table')
    parser.add_argument('--expect-backend', default=DEFAULT_EXPECTED_BACKEND, choices=BACKEND_CHOICES,
                        help='reject scenarios whose actual solver backend differs (default: %s)' % DEFAULT_EXPECTED_BACKEND)
    args = parser.parse_args(argv)

    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    os.chdir(ROOT)

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.mkdir(parents=True, exist_ok=True)

    selected = {part.strip() for part in args.only.split(',') if part.strip()}
    scenarios = scenario_list(args.quick)
    if selected:
        scenarios = [scenario for scenario in scenarios if scenario['id'] in selected]
    if args.no_mp:
        scenarios = [scenario for scenario in scenarios if scenario['mode'] != 'mp']
    if not scenarios:
        parser.error('no scenarios selected')

    probe_lua = None
    try:
        from lua_fixture import create_current_fixture
        probe_lua = create_current_fixture()
    except Exception:
        probe_lua = None
    environment = environment_info(probe_lua)
    clock = clock_overhead(probe_lua)
    timer_overhead = measure_timer_overhead(args.quick)
    del probe_lua

    started = time.time()
    results = []
    failures = []
    for index, scenario in enumerate(scenarios, 1):
        print('[%d/%d] %s' % (index, len(scenarios), scenario['id']), flush=True)
        began = time.time()
        try:
            if args.no_profile:
                scenario['profile_frames'] = 0
            if scenario['mode'] == 'authority':
                result = run_authority_scenario(scenario, args.quick, args.diagnostics,
                                                expected_backend=args.expect_backend)
            elif scenario['mode'] == 'presentation':
                result = run_presentation_scenario(scenario, args.quick, args.diagnostics,
                                                   expected_backend=args.expect_backend)
            elif scenario['mode'] == 'client':
                result = run_client_scenario(scenario, args.quick, args.diagnostics,
                                             expected_backend=args.expect_backend)
            elif scenario['mode'] == 'mp':
                result = run_mp_scenario(scenario, args.quick, args.diagnostics,
                                         expected_backend=args.expect_backend)
            else:
                raise ValueError('unknown mode %r' % scenario['mode'])
            result['elapsedSeconds'] = round(time.time() - began, 3)
            results.append(result)
            validation = result.get('validation') or {}
            if not validation.get('ok', True):
                failed = [check for check in validation.get('checks', []) if not check.get('ok')]
                failures.append({
                    'id': scenario['id'],
                    'error': 'validation rejected run: ' + '; '.join(
                        '%s (%s)' % (check['check'], check.get('detail')) for check in failed),
                    'checks': failed,
                })
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append({'id': scenario['id'], 'error': repr(error)})
        gc.collect()

    observed_backends = sorted({(scenario.get('backend') or {}).get('name')
                                for scenario in results if (scenario.get('backend') or {}).get('name')})
    document = {
        'schema': SCHEMA,
        'schemaVersion': SCHEMA_VERSION,
        'phase': args.phase,
        'label': args.label,
        'elapsedSeconds': round(time.time() - started, 3),
        'bench': environment['source']['bench'],
        'environment': environment,
        'clockOverhead': clock,
        'timerOverhead': timer_overhead,
        'backend': {'expected': args.expect_backend, 'observed': observed_backends},
        'protocol': protocol_block(args.quick),
        'settings': {
            'fixtureSandboxVars': {'CorpseProxyLab': {'VehicleDrag': True}},
            'maxBodiesPerChain': 32,
            'solver': 'Lua path (CVPSolverNative not present in the offline fixture)',
            'repeatsScheme': 'fresh fixture per repeat; setup/build/warmup outside the measured batch',
        },
        'scenarios': results,
        'selfCheck': summarize_validation({'scenarios': results}),
        'failures': failures,
        'limitations': LIMITATIONS,
    }
    raw_path = output / ('raw-%s.json' % args.phase if args.phase != 'adhoc' else 'raw.json')
    with open(raw_path, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, indent=1, sort_keys=False)
        handle.write('\n')
    print('raw data: %s' % raw_path, flush=True)
    print('bench sha256: %s' % document['bench']['sha256'], flush=True)
    print('backend observed: %r (expected %r)' % (observed_backends, args.expect_backend), flush=True)
    if failures:
        print('FAILURES: %r' % (failures,), flush=True)
    if args.write_readme:
        write_readme(output, document, raw_path)
    return 1 if failures else 0


# README rendering is kept close to the raw document so a reviewer can check the
# table against raw.json without re-running anything.
def write_readme(output, document, raw_path):
    lines = ['# Offline diagnostics run: %s' % (document.get('label') or document['phase']), '']
    environment = document['environment']
    lines += ['## Conditions', '',
              '- Kind: **%s** — %s' % (environment['kind'], environment['interpreter']),
              '- Lua interpreter: `%s` via lupa `%s`; Python `%s`' % (environment['luaVersion'], environment['lupa'], environment['python']),
              '- Platform: %s; CPU: %s; cores: %s' % (environment['platform'], environment.get('processor'), environment.get('cpuCount')),
              '- Game build referenced (not executed): %s' % environment.get('gameVersion'),
              '- Bench file: `%s` SHA-256 `%s`' % (document['bench']['file'], document['bench']['sha256']),
              '- Source: branch `%s`, commit `%s`, dirty: %s' % (
                  environment['source']['branch'], environment['source']['commit'], environment['source']['dirty']),
              '- Backend: expected `%s`, observed `%s`' % (
                  document['backend']['expected'], ', '.join(document['backend']['observed'])),
              '- Measurement: one batch mean per repeat (`batchMeanMs`) plus raw per-frame samples (`tickMs`); '
              'repeats use a fresh fixture with identical seed/build/warmup and identical checkpoint hashes',
              '- Protocol: %s' % document['protocol'],
              '- Clock overhead: %s' % (document.get('clockOverhead') or {}),
              '- Timer overhead (A/B): median %s ns/tick for the per-tick sample bookkeeping (%s)' % (
                  fmt(((document.get('timerOverhead') or {}).get('micro') or {}).get('medianDeltaNsPerTick')),
                  ((document.get('timerOverhead') or {}).get('micro') or {}).get('note')),
              '']
    if environment['source'].get('dirtyPaths'):
        lines += ['Dirty paths (present before measurement):', '']
        lines += ['- `%s`' % path for path in environment['source']['dirtyPaths']]
        lines += ['']
    lines += ['## Result table (ms, Lua model only)', '',
              '| scenario | kind | backend | batches | batch median | batch p95 | tick p50 | tick p95 | tick p99 | notes |',
              '|---|---|---|---|---|---|---|---|---|---|']
    for scenario in document['scenarios']:
        backend = (scenario.get('backend') or {}).get('name', '-')
        if 'roles' in scenario:
            for role in scenario['roles']:
                batch = role.get('batchMeanMs') or {}
                tick = role.get('ownTickMs') or {}
                lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                    role['id'], scenario.get('kind'), backend, batch.get('count'),
                    fmt(batch.get('median')), fmt(batch.get('p95')),
                    fmt(tick.get('p50')), fmt(tick.get('p95')), fmt(tick.get('p99')), role['description']))
            continue
        batch = scenario.get('batchMeanMs') or {}
        tick = scenario.get('tickMs') or {}
        if 'error' in scenario:
            lines.append('| %s | %s | %s | - | - | - | - | - | - | ERROR: %s |' % (
                scenario['id'], scenario.get('kind'), backend, scenario['error']))
            continue
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            scenario['id'], scenario.get('kind'), backend, batch.get('count'),
            fmt(batch.get('median')), fmt(batch.get('p95')),
            fmt(tick.get('p50')), fmt(tick.get('p95')), fmt(tick.get('p99')), scenario['description']))
    lines += ['', '## Limits and non-claims', '']
    lines += ['- %s' % item for item in document['limitations']]
    lines += ['', 'Raw data: `%s`' % raw_path.name, '']
    if document.get('failures'):
        lines += ['## Failures', '']
        lines += ['- `%s`: %s' % (failure['id'], failure['error']) for failure in document['failures']]
        lines += ['']
    path = output / 'README.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    print('readme: %s' % path, flush=True)


def fmt(value):
    if value is None:
        return '-'
    if isinstance(value, (int, float)):
        return '%.3f' % value
    return str(value)


if __name__ == '__main__':
    sys.exit(main())
