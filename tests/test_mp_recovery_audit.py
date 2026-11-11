"""Audit boundary: player disconnects before the durable intent write.

Model-level only (Lua handlers + mocked engine/network). Existing coverage:
- test_save_queue covers a *waiting* batch rejected on disconnect;
- test_save_jobs covers a synthetic runtime cancel and shared-ledger pre-transfer
  failures (errors, not disconnection);
- test_save_jobs covers a reconnect after an already-written intent.

This test drives the real MP client/server handlers through the real save queue
and equipment ledger. An in-flight ``create`` job first acknowledges the body
identity checkpoint (as a real save would), then suspends in the equipment
owner-identity checkpoint. The player leaves at that point - before the ledger
'taking' row exists. The test asserts that no intent row is written, the
original material is never moved or claimed, and the queue is released for
another player's operation.
"""
import unittest
from test_link_multiplayer import Network, take
from test_save_jobs import DELAY


def drain(n):
    b = n.clients['friend']
    for _ in range(150):
        if not b.eval('job.finished or job.waiting'):
            b.execute('finishStage()')
        n.pump(); n.tick()
        if not n.server.globals().R.saveJob and n.server.eval('#R.saveQueue==0') and b.eval('job.finished'):
            return
    raise AssertionError('queue did not settle')


class MPRecoveryAuditTests(unittest.TestCase):
    def test_disconnect_before_intent_write_leaves_ledger_clean_and_queue_free(self):
        n = Network(); s = n.server; c = n.clients['owner']; b = n.clients['friend']
        # Real carry: the owner's prepare round-trip completes and the client
        # holds the unsent 'create' request.
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry');finishStage()")
        request = take(c, 'clientPackets')[0]
        p = s.globals().player; p.x = c.globals().player.x; p.y = c.globals().player.y
        n.send(request)
        for packet in take(s, 'packets'): n.receive(packet)
        create = take(c, 'clientPackets')[0]
        # Async persistence makes the job yield at the checkpoints.
        s.execute(DELAY)
        writes = s.globals().equipmentWrites
        n.send(create)
        s.execute("assert(R.saveJob and not R.saveJob.committed and not R.saveJob.done)")
        # Two ticks complete the body identity checkpoint; the job then suspends
        # in the equipment owner-identity checkpoint, still before the intent write.
        for _ in range(2):
            s.execute('now=now+16;CVPMPServer.tick()')
        s.execute("assert(R.saveJob and not R.saveJob.committed and not R.saveJob.done)")
        s.execute("assert(H.confirmed[body]==true and not next(CVPEquipmentRuntime.data.rows))")
        self.assertEqual(writes, s.globals().equipmentWrites, 'intent written before the disconnect')
        # Disconnect while suspended: the player is no longer online.
        s.execute('players={player2}')
        for _ in range(20):
            s.execute('now=now+16;CVPMPServer.tick()')
            if not s.eval('R.saveJob'): break
        n.pump()
        s.execute("""
            assert(not R.saveJob and #R.saveQueue==0)
            assert(rope:getContainer()==storage and not body.md.CVPTether)
            assert(not next(S.graph.links))
            assert(equipmentWrites==0)
            assert(not next(CVPEquipmentRuntime.data.rows))
            assert(equipmentDisk==nil or not equipmentDisk.rows or not next(equipmentDisk.rows))
        """)
        # Another player's real operation still starts and consumes its own
        # original exactly once; the aborted owner's material stays untouched.
        b.execute("carMenu();C.key=nil;job=CVPMPClient.actions:batch(localPlayer,C,{B},{otherRope},false,"
                  "function(ok,_,why) answer={ok=ok,why=why} end)")
        for _ in range(10):
            if b.eval('job.waiting~=nil'): break
            b.execute('finishStage()'); n.pump()
        drain(n)
        b.execute('assert(answer.ok)')
        s.execute("""
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end
            assert(count==1)
            assert(otherRope:getContainer()~=player2.inv)
            assert(rope:getContainer()==storage)
        """)


if __name__ == '__main__':
    unittest.main()
