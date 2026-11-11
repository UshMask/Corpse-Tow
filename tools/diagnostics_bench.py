"""Reproducible offline Lua performance matrix for Corpse Tow (NOT game FPS).

This tool measures the mod's Lua-side authority/presentation work in the isolated
lupa Lua 5.1 engine model used by the Python test suite. It never launches the
game, so Kahlua, Bullet physics, Java bridge cost and rendering are out of scope.
Only relative comparisons made with this exact protocol on one machine are
meaningful; results must not be reported as in-game FPS.

Output: one JSON document with environment fingerprint, protocol, per-scenario
raw repeats, optional per-phase profile rows and optional CVP_Diagnostics snapshot.
See local/runs/diagnostics-*/README.md for the documented report format.

Usage:
    .venv/Scripts/python.exe -B tools/diagnostics_bench.py --output local/runs/some-run
    .venv/Scripts/python.exe -B tools/diagnostics_bench.py --quick --no-mp
    .venv/Scripts/python.exe -B tools/diagnostics_bench.py --diagnostics --phase after
"""
import argparse
import datetime
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
SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Lua groundwork shared by every scenario. `benchClock` is injected from Python
# (time.perf_counter) because Lua 5.1 os.clock has ~1 ms granularity on Windows.
# The mod itself is never modified for measuring; phase wrappers are installed
# only during the short profile batch and then removed.
# ---------------------------------------------------------------------------
COMMON_LUA = r'''
__fi = 0
local __R = R
function __benchStats()
    local service = __R.service
    local links = 0
    for _ in pairs(service.graph.links) do links = links + 1 end
    local sim = __R.simulation
    local groups = #sim.groups
    local records = 0
    for _, group in ipairs(sim.groups) do records = records + #group.records end
    return {links = links, groups = groups, records = records}
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
function __benchBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do __benchFrame() end
    return (benchClock() - started) * 1000 / frames
end
function __benchWarm(frames)
    for _ = 1, frames do __benchFrame() end
    return true
end
-- Restore the warm scene before every repeat so repeats compare the same state.
-- The restore itself is outside the measured batch; its native moves are the
-- same count for every build and only reset constraints for one frame.
function __benchSnapshot()
    __snapshot = {car = {x = car.x, y = car.y}, bodies = {}, links = {}}
    for i, b in ipairs(__all) do
        __snapshot.bodies[i] = {x = b.x, y = b.y, z = b.z or 0, world = b.world}
    end
    for id, link in pairs(S.graph.links) do
        __snapshot.links[id] = {a = {x = link.a.x, y = link.a.y, z = link.a.z},
            b = {x = link.b.x, y = link.b.y, z = link.b.z}}
    end
    return true
end
function __benchRestore()
    for i, b in ipairs(__all) do
        local p = __snapshot.bodies[i]
        if p.world ~= false then move(b, p.x, p.y, p.z or 0) end
    end
    car.x = __snapshot.car.x
    car.y = __snapshot.car.y
    -- The ledger endpoint coordinates advance with the bodies; restore them too,
    -- then force a plan rebuild so every repeat starts from the same warm state.
    for id, link in pairs(S.graph.links) do
        local saved = __snapshot.links[id]
        if saved then
            link.a.x = saved.a.x; link.a.y = saved.a.y; link.a.z = saved.a.z
            link.b.x = saved.b.x; link.b.y = saved.b.y; link.b.z = saved.b.z
        end
    end
    Sim.index = nil
    return true
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


def chain_scene(count, start=(4.0, 0.0), direction=(1.0, 0.0)):
    positions = chain_positions(start, direction, count)
    links = [('vehicle', 1)]
    for i in range(1, count):
        links.append((i, i + 1))
    return positions_lua(positions) + links_lua(links)


def groups_scene(chains):
    """chains: list of (start, direction, count). Returns setup Lua and body offsets."""
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


STRAIGHT_FRAME = 'car.x = car.x + 0.05\nrun()'
STRAIGHT_SLOW_FRAME = 'car.x = car.x + 0.02\nrun()'
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


def scenario_list(quick):
    """Full reproducible matrix. Frame counts scale down with --quick."""
    chain_warm = 40 if quick else 80
    chain_frames = 20 if quick else 40
    chain_reps = 2 if quick else 3
    heavy_frames = 12 if quick else 24
    heavy_reps = 2
    heavy_warm = 30 if quick else 50
    idle_frames = 200 if quick else 400
    scenarios = [
        dict(id='idle.authority', mode='authority', description='Mod enabled, 0 links: idle authority tick (~1 discovery/s)',
             build='', frame=IDLE_FRAME, warmup=50, reps=5, frames=idle_frames,
             phases=[('R', 'tick', 'tick'), ('Sim', 'tick', 'sim.tick'), ('S', 'tick', 'service.tick')]),
        dict(id='bodies.4.individual', mode='authority', description='4 bodies, 4 independent vehicle links',
             build=individual_scene(4), frame=STRAIGHT_FRAME, warmup=80, reps=5, frames=150),
        dict(id='bodies.32.individual', mode='authority', description='32 bodies, 32 independent vehicle links (allowed default config)',
             build=individual_scene(32), frame=STRAIGHT_SLOW_FRAME, warmup=60, reps=4, frames=100),
        dict(id='bodies.32.chain', mode='authority', description='One 32-body chain, straight drive',
             build=chain_scene(32), frame=STRAIGHT_FRAME, warmup=chain_warm, reps=chain_reps, frames=chain_frames),
        dict(id='bodies.32.chain.turn', mode='authority', description='One 32-body chain, circular turn',
             build=chain_scene(32), frame=TURN_FRAME, warmup=chain_warm, reps=chain_reps, frames=chain_frames),
        dict(id='bodies.32.chain.brake', mode='authority', description='One 32-body chain, decelerating from 1 m/s',
             build=chain_scene(32), frame=BRAKE_FRAME, warmup=chain_warm, reps=chain_reps, frames=chain_frames),
        dict(id='bodies.32.chain.backwards', mode='authority', description='One 32-body chain, reversing',
             build=chain_scene(32), frame=BACKWARDS_FRAME, warmup=chain_warm, reps=chain_reps, frames=chain_frames),
        dict(id='bodies.32.chain.obstacle', mode='authority', description='One 32-body chain with every square solid (obstacle/blocked path)',
             build=chain_scene(32), frame=OBSTACLE_FRAME, warmup=chain_warm, reps=chain_reps, frames=chain_frames,
             after_warmup='blocked = true'),
        dict(id='bodies.128.groups4', mode='authority', description='128 bodies in 4 allowed 32-body chains from one vehicle, straight drive',
             build=groups_scene([((4.0, 0.0), (1.0, 0.0), 32), ((-2.0, 0.0), (-1.0, 0.0), 32),
                                 ((2.0, 3.0), (0.0, 1.0), 32), ((2.0, -3.0), (0.0, -1.0), 32)]),
             frame=STRAIGHT_FRAME, warmup=heavy_warm, reps=heavy_reps, frames=heavy_frames),
        dict(id='bodies.128.groups4.turn', mode='authority', description='128 bodies in 4 chains, circular turn',
             build=groups_scene([((4.0, 0.0), (1.0, 0.0), 32), ((-2.0, 0.0), (-1.0, 0.0), 32),
                                 ((2.0, 3.0), (0.0, 1.0), 32), ((2.0, -3.0), (0.0, -1.0), 32)]),
             frame=TURN_FRAME, warmup=heavy_warm, reps=heavy_reps, frames=heavy_frames),
        dict(id='requests.excess', mode='authority', description='32-body chain with an outstanding save job: 8 excess submit attempts per frame',
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
             warmup=60, reps=4, frames=60,
             before_profile='R.saveJob = nil',
             extra='return {rejections = rejections, saveQueueLength = #R.saveQueue}'),
        dict(id='chunk.unavailable', mode='authority', description='4-body scene, one body unavailable 10/40 frames (chunk unload approximation)',
             build=individual_scene(4) + 'chunkBody = bodies[3]\n',
             frame='''__fi = __fi + 1
local phaseMod = (__fi - 1) % 40
chunkBody.world = not (phaseMod >= 10 and phaseMod < 20)
car.x = car.x + 0.05
run()''',
             warmup=80, reps=4, frames=80,
             extra='''local hidden = 0
for i = 1, 40 do hidden = hidden + 1 end
return {scenario = 'chunk.unavailable'}'''),
        dict(id='reconnect.players', mode='authority', description='4-body scene, player disconnects 5/30 frames then reconnects (recovery/save approximation)',
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
             warmup=80, reps=4, frames=60),
        dict(id='save.flush', mode='authority', description='32-body chain, forced ledger flush every frame (fixture persistence model included; see limitations)',
             build=chain_scene(32),
             frame='''car.x = car.x + 0.05
now = now + 50
S.dirty = true
assert(S:flush())''',
             warmup=60, reps=4, frames=40),
        dict(id='graph.copy', mode='authority', description='32-body chain, deep graph copy every frame (pure Lua serialization proxy)',
             build=chain_scene(32),
             frame='''car.x = car.x + 0.05
run()
G.copy(S.graph)''',
             warmup=60, reps=4, frames=60),
        dict(id='presentation.0links', mode='presentation', description='Presentation update with no links (client idle visual path)',
             build='', frame='now = now + 50\nrender()', warmup=50, reps=5, frames=200),
        dict(id='presentation.32.chain', mode='presentation', description='Full SP frame model: authority tick plus presentation update for a 32-body chain',
             build=chain_scene(32), frame='car.x = car.x + 0.05\nrun()\nrender()',
             warmup=chain_warm, reps=chain_reps, frames=chain_frames),
        dict(id='presentation.32.individual', mode='presentation', description='Full SP frame model: authority tick plus presentation for 32 independent links (crowded mode)',
             build=individual_scene(32), frame='car.x = car.x + 0.02\nrun()\nrender()',
             warmup=60, reps=3, frames=60),
        dict(id='client.0links.idle', mode='client', description='Real client OnTick entry point with no links (full mod frame, idle)',
             build='', frame='now = now + 16\ncallbacks.OnTick()\nassert(not CVPRuntime.error)',
             warmup=100, reps=5, frames=300),
    ]
    # Restore the settled warm scene between repeats for body scenes except the
    # ones whose whole point is a changing world (chunk unload, reconnect,
    # blocked paths). Restore cost is excluded from the measured batch.
    for scenario in scenarios:
        if (scenario['mode'] in ('authority', 'presentation') and scenario.get('build')
                and scenario['id'] not in ('chunk.unavailable', 'reconnect.players', 'bodies.32.chain.obstacle')):
            scenario['reset_each_rep'] = True
    return scenarios


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
    lua.globals().benchClock = time.perf_counter
    try:
        value = lua.eval('''(function()
            local started = benchClock()
            for _ = 1, 10000 do benchClock() end
            return (benchClock() - started) / 10000 * 1e6
        end)()''')
        return {'usPerCall': float(value)}
    finally:
        pass


def lua_hooks(hook_list):
    rows = ','.join("{target=%s,key=%s,name=%s}" % (
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
        per_frame = float(lua.eval('__benchBatch(%d)' % frames))
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
            lua.eval('__benchBatch(%d)' % frames)
        snapshot = to_py(lua.eval("require('CVP_Diagnostics').snapshot()"))
        return snapshot
    finally:
        try:
            lua.execute("require('CVP_Diagnostics').disable()")
        except Exception:
            pass


def run_authority_scenario(scenario, quick, with_diagnostics):
    from test_link_runtime import environment

    lua = environment()
    lua.globals().benchClock = time.perf_counter
    lua.execute(COMMON_LUA)
    if scenario['build']:
        lua.execute(scenario['build'])
    lua.execute('function __benchFrame()\n%s\nend' % scenario['frame'])
    lua.execute('function __benchExtra() %s end' % scenario.get('extra', 'return {}'))
    measured_frames = scenario['frames']
    warmup = scenario.get('warmup', 0)
    if warmup:
        lua.eval('__benchWarm(%d)' % warmup)
    after_warmup = scenario.get('after_warmup')
    if after_warmup:
        lua.execute(after_warmup)
    reset = scenario.get('reset_each_rep')
    if reset:
        lua.eval('__benchSnapshot()')
    repeats = []
    for _ in range(scenario.get('repeats', 3)):
        if reset:
            lua.eval('__benchRestore()')
        repeats.append(float(lua.eval('__benchBatch(%d)' % measured_frames)))
    stats = evaluate_stats(lua, scenario.get('extra'))
    phases = scenario.get('phases', AUTHORITY_PHASES)
    profile_frames = scenario.get('profile_frames', 20 if not quick else 10)
    before_profile = scenario.get('before_profile')
    if before_profile:
        lua.execute(before_profile)
    if reset:
        lua.eval('__benchRestore()')
    profile, profile_ms = run_profiled(lua, phases, profile_frames)
    snapshot = None
    if with_diagnostics:
        if after_warmup:
            lua.execute(after_warmup)
        snapshot = diagnostics_snapshot(lua, profile_frames)
    return {
        'id': scenario['id'],
        'mode': scenario['mode'],
        'description': scenario['description'],
        'measuredFramesPerRepeat': measured_frames,
        'warmupFrames': warmup,
        'repeats': repeats,
        'msPerFrame': summarize(repeats),
        'stats': stats,
        'profile': {'frames': profile_frames, 'msPerFrame': profile_ms, 'phases': profile},
        'diagnostics': snapshot,
    }


def run_presentation_scenario(scenario, quick, with_diagnostics):
    from test_link_presentation import scene

    lua = scene()
    lua.globals().benchClock = time.perf_counter
    lua.execute(COMMON_LUA)
    if scenario['build']:
        lua.execute(scenario['build'])
    lua.execute('function __benchFrame()\n%s\nend' % scenario['frame'])
    measured_frames = scenario['frames']
    warmup = scenario.get('warmup', 0)
    if warmup:
        lua.eval('__benchWarm(%d)' % warmup)
    reset = scenario.get('reset_each_rep')
    if reset:
        lua.eval('__benchSnapshot()')
    repeats = []
    for _ in range(scenario.get('repeats', 3)):
        if reset:
            lua.eval('__benchRestore()')
        repeats.append(float(lua.eval('__benchBatch(%d)' % measured_frames)))
    stats = evaluate_stats(lua)
    profile_frames = scenario.get('profile_frames', 20 if not quick else 10)
    if reset:
        lua.eval('__benchRestore()')
    profile, profile_ms = run_profiled(lua, PRESENTATION_PHASES, profile_frames)
    snapshot = diagnostics_snapshot(lua, profile_frames) if with_diagnostics else None
    return {
        'id': scenario['id'],
        'mode': scenario['mode'],
        'description': scenario['description'],
        'measuredFramesPerRepeat': measured_frames,
        'warmupFrames': warmup,
        'repeats': repeats,
        'msPerFrame': summarize(repeats),
        'stats': stats,
        'profile': {'frames': profile_frames, 'msPerFrame': profile_ms, 'phases': profile},
        'diagnostics': snapshot,
    }


def run_client_scenario(scenario, quick, with_diagnostics):
    from test_link_client import client

    lua = client()
    lua.globals().benchClock = time.perf_counter
    lua.execute(COMMON_LUA)
    if scenario['build']:
        lua.execute(scenario['build'])
    lua.execute('function __benchFrame()\n%s\nend' % scenario['frame'])
    measured_frames = scenario['frames']
    warmup = scenario.get('warmup', 0)
    if warmup:
        lua.eval('__benchWarm(%d)' % warmup)
    repeats = []
    for _ in range(scenario.get('repeats', 3)):
        repeats.append(float(lua.eval('__benchBatch(%d)' % measured_frames)))
    stats = evaluate_stats(lua)
    profile_frames = scenario.get('profile_frames', 20 if not quick else 10)
    profile, profile_ms = run_profiled(lua, CLIENT_PHASES, profile_frames)
    snapshot = diagnostics_snapshot(lua, profile_frames) if with_diagnostics else None
    return {
        'id': scenario['id'],
        'mode': scenario['mode'],
        'description': scenario['description'],
        'measuredFramesPerRepeat': measured_frames,
        'warmupFrames': warmup,
        'repeats': repeats,
        'msPerFrame': summarize(repeats),
        'stats': stats,
        'profile': {'frames': profile_frames, 'msPerFrame': profile_ms, 'phases': profile},
        'diagnostics': snapshot,
    }


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)

    def percentile(p):
        index = min(count - 1, max(0, int(round((p / 100.0) * (count - 1)))))
        return ordered[index]

    mean = sum(ordered) / count
    variance = sum((value - mean) ** 2 for value in ordered) / count
    return {
        'count': count,
        'min': ordered[0],
        'median': percentile(50),
        'p95': percentile(95),
        'max': ordered[-1],
        'mean': mean,
        'stdDev': math.sqrt(variance),
        'unit': 'ms/frame',
        'repeatsMsPerFrame': values,
    }


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
        local x = 4 + (i - 1) * 3
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

MP_SERVER_COMMON = MP_PHASE_LUA + r'''
function __benchFrame()
    now = now + 100
    car.x = car.x + 0.05
    CVPMPServer.tick()
end
function __benchBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do __benchFrame() end
    return (benchClock() - started) * 1000 / frames
end
function __benchWarm(frames)
    for _ = 1, frames do __benchFrame() end
end
function __benchStats()
    local groups = #R.simulation.groups; local records = 0
    for _, group in ipairs(R.simulation.groups) do records = records + #group.records end
    local links = 0; for _ in pairs(R.service.graph.links) do links = links + 1 end
    return {links = links, groups = groups, records = records}
end
'''

MP_CLIENT_COMMON = MP_PHASE_LUA + r'''
function __benchFrame()
    now = now + 100
    CVPMPClient.tick()
end
function __benchBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do __benchFrame() end
    return (benchClock() - started) * 1000 / frames
end
function __benchWarm(frames)
    for _ = 1, frames do __benchFrame() end
end
function __benchStats()
    local bodies = 0
    if CVPMPClient.graph then
        for _ in pairs(CVPMPClient.graph.links or {}) do bodies = bodies + 1 end
    end
    local rows = 0
    for _ in pairs(CVPMPClient.rows or {}) do rows = rows + 1 end
    return {links = bodies, rows = rows}
end
'''


def run_mp_scenario(quick, with_diagnostics):
    from test_link_multiplayer import Network, take

    network = Network()
    errors = []
    try:
        network.server.execute(MP_SETUP_LUA)
        network.server.execute('__mpBuild()')
        network.publish()
    except Exception as error:
        errors.append('mp setup failed: %r' % (error,))
        return {'id': 'mp.2clients.8', 'mode': 'mp', 'description': 'MP server + owner/friend client model', 'error': errors[0]}
    results = []
    measured_frames = 40 if quick else 80
    warmup = 10
    server = network.server
    for role, target, common, phases in (
            ('server', server, MP_SERVER_COMMON, MP_SERVER_PHASES),
            ('owner', network.clients['owner'], MP_CLIENT_COMMON, MP_CLIENT_PHASES),
            ('friend', network.clients['friend'], MP_CLIENT_COMMON, MP_CLIENT_PHASES)):
        target.globals().benchClock = time.perf_counter
        target.execute(common)
        target.eval('__benchWarm(%d)' % warmup)
        repeats = [float(target.eval('__benchBatch(%d)' % measured_frames)) for _ in range(3)]
        stats = to_py(target.eval('__benchStats()'))
        profile, profile_ms = run_profiled(target, phases, 10 if quick else 20)
        snapshot = diagnostics_snapshot(target, 10 if quick else 20) if with_diagnostics else None
        results.append({
            'id': 'mp.' + role + '.8',
            'mode': 'mp',
            'description': 'MP 2-client fixture, 8-body chain, %s Lua handling only' % role,
            'measuredFramesPerRepeat': measured_frames,
            'warmupFrames': warmup,
            'repeats': repeats,
            'msPerFrame': summarize(repeats),
            'stats': {str(k): v for k, v in stats.items()},
            'profile': {'frames': 10 if quick else 20, 'msPerFrame': profile_ms, 'phases': profile},
            'diagnostics': snapshot,
        })
    return {'id': 'mp.2clients.8', 'mode': 'mp', 'description': 'MP model: server plus owner/friend client Lua work; Python packet pump excluded from timing', 'roles': results}


def protocol_block(quick):
    return {
        'clock': 'Python time.perf_counter injected into Lua; per-frame batches timed inside Lua',
        'phaseClock': 'same clock; inclusive nested timings must not be summed',
        'dt': 'authority SP model: 50 ms per frame; MP model: 100 ms per frame',
        'repeats': 'per scenario; see scenarios[].repeats',
        'warmup': 'per scenario; see scenarios[].warmupFrames',
        'quickMode': quick,
        'scope': 'Lua model only: Python engine fixture, no Kahlua, Java JAR, Bullet solver or rendering',
    }


LIMITATIONS = [
    'Offline lupa Lua 5.1 model, not Project Zomboid/Kahlua and not in-game FPS. '
    'The game runs Kahlua with a Java JAR; engine calls are Python/table stand-ins here.',
    'Engine fixture replaces Bullet, the Java solver and the renderer with plain Lua/Python tables; '
    'relative Lua-side changes are meaningful, absolute game cost is not.',
    'The fixture persistence layer serializes equipment through Python JSON; save.flush timing '
    'includes that model and is not representative of the game write path.',
    'No network transport: MP scenario times server/client Lua handlers only; Python packet pump '
    'and real latency are excluded. The fixture has two clients, so the far/third client case is in-game only.',
    'os-level scheduling noise exists. Compare same-machine, same-protocol runs only; repeats show variance.',
    'Non-movement scenarios (idle) are microseconds per frame; phase profiling adds a Python clock '
    'call per invocation and is only used descriptively.',
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', required=True, help='output directory for raw.json and README.md')
    parser.add_argument('--phase', default='baseline', choices=['baseline', 'after', 'adhoc'])
    parser.add_argument('--label', default='', help='free-form run label')
    parser.add_argument('--quick', action='store_true', help='shorter protocol for smoke checks')
    parser.add_argument('--only', default='', help='comma-separated scenario ids to run')
    parser.add_argument('--no-mp', action='store_true', help='skip the MP two-client fixture scenario')
    parser.add_argument('--no-profile', action='store_true', help='skip per-phase profiling')
    parser.add_argument('--diagnostics', action='store_true', help='collect CVP_Diagnostics snapshots')
    parser.add_argument('--write-readme', action='store_true', help='write a README.md with conditions and the result table')
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

    probe_lua = None
    try:
        from lua_fixture import create_current_fixture
        probe_lua = create_current_fixture()
    except Exception:
        probe_lua = None
    environment = environment_info(probe_lua)
    clock = clock_overhead(probe_lua) if probe_lua is not None else None

    started = time.time()
    results = []
    failures = []
    for index, scenario in enumerate(scenarios, 1):
        print('[%d/%d] %s' % (index, len(scenarios), scenario['id']), flush=True)
        began = time.time()
        try:
            if scenario.get('no_profile') or args.no_profile:
                scenario['profile_frames'] = 0
            if scenario['mode'] == 'authority':
                result = run_authority_scenario(scenario, args.quick, args.diagnostics)
            elif scenario['mode'] == 'presentation':
                result = run_presentation_scenario(scenario, args.quick, args.diagnostics)
            elif scenario['mode'] == 'client':
                result = run_client_scenario(scenario, args.quick, args.diagnostics)
            else:
                raise ValueError('unknown mode %r' % scenario['mode'])
            result['elapsedSeconds'] = round(time.time() - began, 3)
            results.append(result)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append({'id': scenario['id'], 'error': repr(error)})

    if not args.no_mp and not selected:
        began = time.time()
        print('[mp] mp.2clients.8', flush=True)
        try:
            mp_result = run_mp_scenario(args.quick, args.diagnostics)
            mp_result['elapsedSeconds'] = round(time.time() - began, 3)
            results.append(mp_result)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append({'id': 'mp.2clients.8', 'error': repr(error)})

    document = {
        'schema': SCHEMA,
        'schemaVersion': SCHEMA_VERSION,
        'phase': args.phase,
        'label': args.label,
        'elapsedSeconds': round(time.time() - started, 3),
        'environment': environment,
        'clockOverhead': clock,
        'protocol': protocol_block(args.quick),
        'settings': {
            'fixtureSandboxVars': {'CorpseProxyLab': {'VehicleDrag': True}},
            'maxBodiesPerChain': 32,
            'solver': 'Lua path (CVPSolverNative not present in fixture)',
        },
        'scenarios': results,
        'failures': failures,
        'limitations': LIMITATIONS,
    }
    raw_path = output / ('raw-%s.json' % args.phase if args.phase != 'adhoc' else 'raw.json')
    with open(raw_path, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, indent=1, sort_keys=False)
        handle.write('\n')
    print('raw data: %s' % raw_path, flush=True)
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
              '- Source: branch `%s`, commit `%s`, dirty: %s' % (
                  environment['source']['branch'], environment['source']['commit'], environment['source']['dirty']),
              '- Sandbox model: Enabled=true, VehicleDrag=true, MaxBodiesPerChain=32; Lua solver path (no native solver)',
              '- Protocol: %s' % document['protocol'],
              '- Clock overhead: %s' % (document.get('clockOverhead') or {}),
              '']
    if environment['source'].get('dirtyPaths'):
        lines += ['Dirty paths (present before measurement):', '']
        lines += ['- `%s`' % path for path in environment['source']['dirtyPaths']]
        lines += ['']
    lines += ['## Result table (ms/frame, Lua model only)', '',
              '| scenario | repeats | median | p95 | max | std dev | notes |',
              '|---|---|---|---|---|---|---|']
    for scenario in document['scenarios']:
        if 'roles' in scenario:
            for role in scenario['roles']:
                summary = role.get('msPerFrame') or {}
                lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
                    role['id'], summary.get('count'), fmt(summary.get('median')), fmt(summary.get('p95')),
                    fmt(summary.get('max')), fmt(summary.get('stdDev')), role['description']))
            continue
        summary = scenario.get('msPerFrame') or {}
        if 'error' in scenario:
            lines.append('| %s | - | - | - | - | - | ERROR: %s |' % (scenario['id'], scenario['error']))
            continue
        lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
            scenario['id'], summary.get('count'), fmt(summary.get('median')), fmt(summary.get('p95')),
            fmt(summary.get('max')), fmt(summary.get('stdDev')), scenario['description']))
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
