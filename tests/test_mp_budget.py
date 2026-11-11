"""MP request budget: duplicates/rejections must not build snapshots.

The real server/client handlers run in separate Lua VMs; packets cross as plain
data.  Counters are the server's bounded CVPMPServer.stats table plus a wrapper
around Runtime.request that records how many authoritative operations ran.
"""
import unittest

from test_link_multiplayer import Network, take

FIELDS = ('captures', 'publishes', 'results', 'rejected', 'rateLimited', 'duplicates', 'repliesDropped')


def wire_version(n):
    return n.server.eval("require('CVP_LinkWire').version")


def packet(n, request, args, who='owner', name='command'):
    """A client command envelope with the current protocol/session/epoch."""
    c = n.clients[who]
    return {'who': who, 'name': name, 'args': {
        'protocol': wire_version(n),
        'session': c.globals().CVPMPClient.session,
        'epoch': c.globals().CVPMPClient.epoch,
        'request': request,
        'args': args}}


def counters(n):
    stats = n.server.eval('CVPMPServer.stats')
    rows = {field: (stats[field] if stats is not None else None) for field in FIELDS}
    # Raw capture count works even on a build without the counters table, so the
    # budget tests fail on the old behavior for the right reason.
    rows['captures'] = n.server.eval('rawCaptures')
    return rows


def instrument(n):
    """Wrap S.capture once per VM and initialize the fixed-size counters."""
    n.server.execute("""
        rawCaptures=0
        local capture=CVPMPServer.capture
        CVPMPServer.capture=function(...) rawCaptures=rawCaptures+1;return capture(...) end
        if CVPMPServer.resetStats then CVPMPServer.resetStats() end
    """)


def reset_counters(n):
    n.server.execute('rawCaptures=0;if CVPMPServer.resetStats then CVPMPServer.resetStats() end')


def count_operations(n):
    """Wrap the authority entry point once per VM so replays cannot hide."""
    n.server.execute("local request=R.request;ops=0;R.request=function(...) ops=ops+1;return request(...) end")


def operations(n):
    return n.server.eval('ops')


def link_visible(n):
    n.server.execute('root=link(C,A,rope)')
    n.publish()


class MPRequestBudgetTests(unittest.TestCase):
    def test_duplicate_completed_request_replays_result_without_capture(self):
        n = Network()
        instrument(n)
        hard_enum = n.server
        link_visible(n)
        hard_enum.execute('beside(S.graph.links[root].a)')
        link_id = hard_enum.eval('root')
        revision = hard_enum.eval('S.graph.links[root].revision')
        request = packet(n, 1, {'id': link_id, 'revision': revision, 'side': 'a', 'op': 'release'})
        count_operations(n)
        reset_counters(n)
        n.send(request)
        first = counters(n)
        self.assertEqual(first['captures'], 1, 'one accepted operation must publish exactly one state')
        for outgoing in take(hard_enum, 'packets'):
            n.receive(outgoing)
        self.assertEqual(operations(n), 1)
        graph_revision = hard_enum.eval('S.graph.revision')
        reset_counters(n)
        for _ in range(100):
            n.send(request)
        after = counters(n)
        self.assertEqual(operations(n), 1, 'a duplicate request was executed again')
        self.assertEqual(after['captures'], 0, 'duplicate requests forced full captures')
        self.assertEqual(after['publishes'], 0, 'duplicate requests forced a state publication')
        self.assertEqual(after['duplicates'], 100)
        self.assertLessEqual(after['results'], 8, 'duplicate replies must be bounded')
        self.assertEqual(after['results'] + after['repliesDropped'], 100)
        self.assertEqual(hard_enum.eval('S.graph.revision'), graph_revision)
        outgoing = take(hard_enum, 'packets')
        self.assertEqual(len(outgoing), after['results'])
        self.assertTrue(all(row['name'] == 'result' for row in outgoing),
                        'duplicate replay published state instead of only the stored result')

    def test_reply_budget_recovers_over_time(self):
        n = Network()
        s = n.server
        link_visible(n)
        reset_counters(n)
        bad = {'id': 'root', 'revision': 1, 'side': 'a', 'op': 'bogus'}
        for request in range(1, 101):
            n.send(packet(n, request, bad))
        self.assertLessEqual(counters(n)['results'], 8)
        self.assertGreater(counters(n)['repliesDropped'], 0)
        take(s, 'packets')
        s.execute('now=now+1000')
        n.send(packet(n, 101, bad))
        self.assertEqual(counters(n)['results'], 9,
                         'the reply budget must recover with time')
        self.assertEqual(len(take(s, 'packets')), 1)

    def test_invalid_request_flood_does_not_capture_or_execute(self):
        n = Network()
        instrument(n)
        s = n.server
        link_visible(n)
        count_operations(n)
        reset_counters(n)
        graph_revision = s.eval('S.graph.revision')
        bad = {'id': 'root', 'revision': 1, 'side': 'a', 'op': 'bogus'}
        for request in range(1, 101):
            n.send(packet(n, request, bad))
        after = counters(n)
        self.assertEqual(operations(n), 0)
        self.assertEqual(after['captures'], 0, 'invalid commands forced full captures')
        self.assertEqual(after['rejected'], 100)
        self.assertLessEqual(after['results'], 8, 'invalid-command replies must be bounded')
        self.assertEqual(after['results'] + after['repliesDropped'], 100)
        self.assertEqual(s.eval('S.graph.revision'), graph_revision)
        outgoing = take(s, 'packets')
        self.assertEqual(len(outgoing), after['results'])
        self.assertTrue(all(row['name'] == 'result' for row in outgoing))

    def test_valid_rejections_are_token_limited_without_captures(self):
        n = Network()
        instrument(n)
        s = n.server
        link_visible(n)
        count_operations(n)
        reset_counters(n)
        graph_revision = s.eval('S.graph.revision')
        # Valid wire shape, but the authority rejects it: no graph change happens.
        bad = {'id': 'missing-link', 'revision': 1, 'side': 'a', 'op': 'release'}
        for request in range(1, 101):
            n.send(packet(n, request, bad))
        after = counters(n)
        self.assertEqual(operations(n), 8, 'the token budget must gate authority work')
        self.assertEqual(after['captures'], 0, 'rejected replies forced full captures')
        self.assertEqual(after['rejected'], 8)
        self.assertEqual(after['rateLimited'], 92)
        self.assertLessEqual(after['results'], 8, 'rejection replies must be bounded')
        self.assertEqual(after['results'] + after['repliesDropped'], 100)
        self.assertEqual(s.eval('S.graph.revision'), graph_revision,
                         'rejected requests must not change the graph')

    def test_distinct_valid_successes_are_token_limited_with_bounded_captures(self):
        n = Network()
        instrument(n)
        s = n.server
        link_visible(n)
        count_operations(n)
        reset_counters(n)
        graph_revision = s.eval('S.graph.revision')
        link_id = s.eval('root')
        for request in range(1, 101):
            s.execute('beside(S.graph.links[root].a)')
            revision = s.eval('S.graph.links[root].revision')
            n.send(packet(n, request, {'id': link_id, 'revision': revision, 'side': 'a', 'op': 'release'}))
        after = counters(n)
        self.assertEqual(operations(n), 8, 'tokens must cap accepted operations')
        self.assertEqual(after['captures'], 8, 'captures must stay bounded by accepted operations')
        self.assertEqual(after['rateLimited'], 92)
        self.assertLessEqual(after['results'], 16, 'success + rejection replies must be bounded')
        self.assertEqual(after['results'] + after['repliesDropped'], 100)
        self.assertEqual(s.eval('S.graph.revision'), graph_revision + 8)

    def test_appearance_messages_are_rate_limited(self):
        n = Network()
        s = n.server
        link_visible(n)
        c = n.clients['owner']
        protocol = wire_version(n)
        session = c.globals().CVPMPClient.session
        epoch = c.globals().CVPMPClient.epoch
        base = {'protocol': protocol, 'session': session, 'epoch': epoch}
        s.execute('now=1000')
        for _ in range(100):
            args = dict(base)
            args['rows'] = {'A': 1}
            n.send({'who': 'owner', 'name': 'appearanceAck', 'args': args})
        self.assertEqual(s.eval('CVPMPServer.peers[player].nextAppearanceAck'), 1250)
        # First missing request schedules the next one; the rest are ignored.
        for _ in range(100):
            args = dict(base)
            args['key'] = 'A'
            n.send({'who': 'owner', 'name': 'appearanceMissing', 'args': args})
        self.assertEqual(s.eval('CVPMPServer.peers[player].nextAppearanceMissing'), 2000)

    def test_result_waits_for_and_accepts_satisfying_state(self):
        n = Network()
        instrument(n)
        s = n.server
        c = n.clients['owner']
        link_visible(n)
        c.execute("""
            replies=0
            local id,row=next(CVPMPClient.graph.links)
            CVPMPClient.api.request(localPlayer,'command',{id=id,revision=row.revision,side='b',op='release'},
                function(ok,result,why) replies=replies+1;success=ok;reason=why end)
        """)
        sent = take(c, 'clientPackets')
        self.assertEqual(len(sent), 1)
        n.send(sent[0])
        outgoing = take(s, 'packets')
        result = next(row for row in outgoing if row['name'] == 'result')
        states = [row for row in outgoing if row['name'] == 'state']
        self.assertTrue(states, 'a successful graph change must publish a state at the result sequence')
        c.execute('assert(CVPMPClient.pending[1] and not CVPMPClient.pending[1].result)')
        n.receive(result)
        c.execute('assert(CVPMPClient.pending[1] and CVPMPClient.pending[1].result)')
        self.assertEqual(c.eval('replies'), 0, 'result drained before its state arrived')
        self.assertLess(c.eval('CVPMPClient.sequence'), result['args']['sequence'])
        for row in states:
            n.receive(row)
        self.assertEqual(c.eval('replies'), 1)
        self.assertTrue(c.eval('success'))
        self.assertGreaterEqual(c.eval('CVPMPClient.sequence'), result['args']['sequence'])

    def test_lost_state_recovers_and_lost_result_replays_without_capture(self):
        # A) The result arrives but its state was lost: the client waits, then asks
        # for one full sync instead of waiting for the idle recovery timer.
        n = Network()
        instrument(n)
        s = n.server
        c = n.clients['owner']
        link_visible(n)
        c.execute("""
            replies=0
            local id,row=next(CVPMPClient.graph.links)
            CVPMPClient.api.request(localPlayer,'command',{id=id,revision=row.revision,side='b',op='release'},
                function(ok,result,why) replies=replies+1;success=ok;reason=why end)
        """)
        n.send(take(c, 'clientPackets')[0])
        outgoing = take(s, 'packets')
        result = next(row for row in outgoing if row['name'] == 'result')
        for row in outgoing:
            if row['name'] != 'state':
                n.receive(row)
        self.assertEqual(c.eval('replies'), 0)
        for _ in range(12):
            n.tick()
        self.assertEqual(c.eval('replies'), 1, 'a lost state must be recovered within the bounded wait')
        self.assertTrue(c.eval('success'))

        # B) The result is lost but the state arrives: the client retries the same
        # id, and the server replays the stored result without capturing again.
        n = Network()
        instrument(n)
        s = n.server
        c = n.clients['owner']
        link_visible(n)
        c.execute("""
            replies=0
            local id,row=next(CVPMPClient.graph.links)
            CVPMPClient.api.request(localPlayer,'command',{id=id,revision=row.revision,side='b',op='release'},
                function(ok,result,why) replies=replies+1;success=ok;reason=why end)
        """)
        n.send(take(c, 'clientPackets')[0])
        outgoing = take(s, 'packets')
        for row in outgoing:
            if row['name'] == 'state':
                n.receive(row)
        self.assertEqual(c.eval('replies'), 0)
        c.execute('now=now+2100;CVPMPClient.tick()')
        retries = [row for row in take(c, 'clientPackets') if row['name'] == 'command']
        self.assertEqual(len(retries), 1, 'the client must retry the same request id')
        reset_counters(n)
        n.send(retries[0])
        replayed = counters(n)
        self.assertEqual(replayed['captures'], 0, 'a duplicate replay forced a full capture')
        self.assertEqual(replayed['duplicates'], 1)
        self.assertEqual(replayed['results'], 1)
        for row in take(s, 'packets'):
            n.receive(row)
        self.assertEqual(c.eval('replies'), 1)
        self.assertTrue(c.eval('success'))

    def test_owner_flood_does_not_stop_friend_updates(self):
        n = Network()
        instrument(n)
        s = n.server
        link_visible(n)
        reset_counters(n)
        friend_states = []
        receive = n.receive

        def capture(packet_row):
            if packet_row['who'] == 'friend' and packet_row['name'] in ('state', 'motion'):
                friend_states.append(packet_row)
            receive(packet_row)

        n.receive = capture
        bad = {'id': 'root', 'revision': 1, 'side': 'a', 'op': 'bogus'}
        request = 0
        try:
            for _ in range(10):
                for _ in range(10):
                    request += 1
                    n.send(packet(n, request, bad))
                n.tick(.1)
        finally:
            n.receive = receive
        after = counters(n)
        self.assertTrue(friend_states, 'a flooding client stopped another client updates')
        self.assertLessEqual(after['captures'], 12, 'a request flood added full captures')
        self.assertEqual(after['rejected'], 100)
        self.assertGreater(n.clients['friend'].eval('CVPMPClient.sequence'), 0)


if __name__ == '__main__':
    unittest.main()
