"""Measure MP server Lua cost at allowed 4/32/128-body configurations.

This is the same isolated lupa Lua 5.1 handler model used by tests: the real
CVP_MPServer/CVP_LinkRuntime modules run over the Python engine fixture. It does
NOT launch Project Zomboid, Bullet, the Java bridge or a real network, so the
numbers are relative server-handler costs, not in-game FPS or wire bytes.

Usage:
    .venv/Scripts/python.exe -B tools/mp_server_load.py --bodies 4 32 128
    .venv/Scripts/python.exe -B tools/mp_server_load.py --bodies 128 --json out.json
"""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tests'))

from test_link_multiplayer import Network, take  # noqa: E402

SETUP = r'''
function __loadBuild(n, groups)
    local all = {}
    local per = math.floor(n / groups)
    for i = 1, n do
        local b = corpse()
        b.netID = 'load-' .. i
        b.md.CVPBodyKey = 'load-' .. i
        b.getSquare = body.getSquare
        b.setSquare = body.setSquare
        b.getStaticMovingObjectIndex = body.getStaticMovingObjectIndex
        b.getAngle = body.getAngle
        local x = 4 + ((i - 1) % per) * 2
        local y = 0
        local square = gridSquare(math.floor(x), math.floor(y), 0)
        square:addCorpse(b)
        b.x, b.y, b.z, b.sq = x, y, 0, square
        all[i] = b
    end
    H.discover()
    for g = 1, groups do
        local previous = C
        for j = 1, per do
            local i = (g - 1) * per + j
            local gear = item('Base.Rope')
            storage:AddItem(gear)
            local endpoint = {kind = 'body', key = all[i].md.CVPBodyKey, point = 'feet'}
            link(previous, endpoint, gear)
            previous = endpoint
        end
    end
    publish()
    return n
end
function __loadBatch(frames)
    __fi = 0
    local started = benchClock()
    for _ = 1, frames do
        now = now + 100
        car.x = car.x + 0.05
        CVPMPServer.tick()
    end
    return (benchClock() - started) * 1000 / frames
end
'''

PHASES = [
    ('CVPMPServer', 'tick', 'mp.server.tick'),
    ('CVPMPServer', 'capture', 'mp.server.capture'),
    ('CVPMPServer', 'publish', 'mp.server.publish'),
]


def measure(bodies, groups, frames=30, repeats=3, warmup=5):
    network = Network()
    server = network.server
    server.globals().benchClock = time.perf_counter
    server.execute(SETUP)
    server.globals().n = bodies
    server.globals().groups = groups
    server.execute('__loadBuild(n, groups)')
    network.pump()
    server.globals().benchClock = time.perf_counter
    server.execute('__loadWarm = function() for i=1,5 do now=now+100;car.x=car.x+0.05;CVPMPServer.tick() end end')
    server.execute('__loadWarm()')
    values = [float(server.eval('__loadBatch(%d)' % frames)) for _ in range(repeats)]
    stats = server.eval('CVPMPServer.stats') if server.eval('type(CVPMPServer.stats)') == 'table' else None
    result = {
        'bodies': bodies,
        'groups': groups,
        'links': server.eval('(function() local n=0;for _ in pairs(S.graph.links) do n=n+1 end;return n end)()'),
        'frames': frames,
        'warmup': warmup,
        'repeats': values,
        'median': statistics.median(values),
        'p95': sorted(values)[min(len(values) - 1, int(round(.95 * (len(values) - 1))))],
        'stats': {str(k): v for k, v in (stats or {}).items()},
        'environment': {
            'platform': platform.platform(),
            'python': platform.python_version(),
            'lua': 'lupa Lua 5.1 (isolated fixture)',
            'game': 'not launched',
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bodies', type=int, nargs='+', default=[4, 32, 128])
    parser.add_argument('--frames', type=int, default=30)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    results = []
    for bodies in args.bodies:
        groups = 4 if bodies > 32 else 1
        print('measuring %d bodies in %d allowed 32-body chain(s)' % (bodies, groups), flush=True)
        results.append(measure(bodies, groups, frames=args.frames, repeats=args.repeats))
    payload = {
        'schema': 'cvp-mp-server-load',
        'version': 1,
        'scope': 'isolated lupa Lua 5.1 handler model; no PZ, Bullet, Java or network',
        'protocol': {'frames': args.frames, 'repeats': args.repeats, 'dtMs': 100,
                     'groups': '4 bodies=1 chain, 32=1 chain, 128=4x32 chains'},
        'results': results,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
