"""Probe MP request/response cost on the real server/client handler modules.

Runs on both pre-fix and current Lua sources (no S.stats dependency): counters are
collected by wrapping CVPMPServer.capture/publish and R.request. This is an
isolated lupa Lua 5.1 handler model, not a network or game FPS measurement.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tests'))
from test_link_multiplayer import Network, take  # noqa: E402

SPY = r'''
captures, publishes, operations = 0, 0, 0
local capture = CVPMPServer.capture
CVPMPServer.capture = function(...) captures = captures + 1; return capture(...) end
local publish = CVPMPServer.publish
CVPMPServer.publish = function(...) publishes = publishes + 1; return publish(...) end
local request = R.request
R.request = function(...) operations = operations + 1; return request(...) end
function takeStats()
    local result = {captures = captures, publishes = publishes, operations = operations}
    captures, publishes, operations = 0, 0, 0
    return result
end
'''


def version(n):
    return n.server.eval("require('CVP_LinkWire').version")


def packet(n, request, args, who='owner', name='command'):
    c = n.clients[who]
    return {'who': who, 'name': name, 'args': {
        'protocol': version(n), 'session': c.globals().CVPMPClient.session,
        'epoch': c.globals().CVPMPClient.epoch, 'request': request, 'args': args}}


def to_py(value):
    if hasattr(value, 'items'):
        return {str(k): to_py(v) for k, v in value.items()}
    if hasattr(value, '__iter__') and not isinstance(value, (str, bytes, dict)):
        return [to_py(v) for v in value]
    return value


def scenario(n, kind):
    n.server.execute(SPY)
    n.server.execute('root=link(C,A,rope)')
    n.publish()
    for _ in range(50):
        take(n.server, 'packets')
        n.pump()
    n.server.execute('takeStats()')
    link_id = n.server.eval('root')
    revision = n.server.eval('S.graph.links[root].revision')
    if kind == 'duplicates':
        first = packet(n, 1, {'id': link_id, 'revision': revision, 'side': 'a', 'op': 'release'})
        n.send(first)
        outgoing = take(n.server, 'packets')
        for row in outgoing:
            n.receive(row)
        n.pump()
        n.server.execute('takeStats()')
        for _ in range(100):
            n.send(first)
        stats = to_py(n.server.eval('takeStats()'))
        packets = take(n.server, 'packets')
    elif kind == 'invalid':
        for request in range(1, 101):
            n.send(packet(n, request, {'id': 'root', 'revision': 1, 'side': 'a', 'op': 'bogus'}))
        stats = to_py(n.server.eval('takeStats()'))
        packets = take(n.server, 'packets')
    else:
        for request in range(1, 101):
            n.send(packet(n, request, {'id': 'missing-link', 'revision': 1, 'side': 'a', 'op': 'release'}))
        stats = to_py(n.server.eval('takeStats()'))
        packets = take(n.server, 'packets')
    counts = {}
    for row in packets:
        counts[row['name']] = counts.get(row['name'], 0) + 1
    stats['packets'] = counts
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    payload = {'schema': 'cvp-mp-budget-probe', 'version': 1,
               'scope': 'isolated lupa Lua 5.1 handler model; no PZ/Java/network',
               'scenarios': {}}
    for kind in ('duplicates', 'invalid', 'rejected'):
        n = Network()
        payload['scenarios'][kind] = scenario(n, kind)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


if __name__ == '__main__':
    main()
