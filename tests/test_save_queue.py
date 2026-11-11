"""Bounded authority queue through real MP handlers and deferred persistence."""
import unittest
from test_link_multiplayer import Network, take, vm
from test_save_jobs import DELAY


def concurrent():
    n=Network();s=n.server;a=n.clients['owner'];b=n.clients['friend']
    a.execute("menu(body);choose('IGUI_CVP_LinkStartCarry');finishStage()")
    request=take(a,'clientPackets')[0]
    s.globals().player.x=a.globals().player.x;s.globals().player.y=a.globals().player.y
    n.send(request)
    for packet in take(s,'packets'):n.receive(packet)
    create=take(a,'clientPackets')[0];s.execute(DELAY);n.send(create)
    sent=[];send=n.send
    def record(packet):sent.append(packet);send(packet)
    n.send=record
    b.execute("carMenu();C.key=nil;job=CVPMPClient.actions:batch(localPlayer,C,{B},{otherRope},false,function(ok,_,why) answer={ok=ok,why=why} end)")
    for _ in range(10):
        if b.eval('job.waiting~=nil'):break
        b.execute('finishStage()');n.pump()
    s.execute('assert(R.saveJob and #R.saveQueue==1 and otherRope:getContainer()==player2.inv)')
    b.execute('assert(not job.finished and not answer)')
    return n,next(p for p in sent if p['who']=='friend')


def drain(n):
    b=n.clients['friend']
    for _ in range(150):
        if not b.eval('job.finished or job.waiting'):b.execute('finishStage()')
        n.pump();n.tick()
        if not n.server.globals().R.saveJob and n.server.eval('#R.saveQueue==0') and b.eval('job.finished'):return
    raise AssertionError('queue did not settle')


class SaveQueueTests(unittest.TestCase):
    def test_two_players_wait_and_duplicate_requests_do_not_transfer_twice(self):
        n,request=concurrent();s=n.server;b=n.clients['friend']
        writes=s.globals().equipmentWrites
        n.send(request);n.send(request)
        self.assertEqual(writes,s.globals().equipmentWrites)
        s.execute('assert(#R.saveQueue==1)')
        drain(n);b.execute('assert(answer.ok)')
        s.execute("local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==2 and otherRope:getContainer()~=player2.inv)")
        writes=s.globals().equipmentWrites;n.send(request);n.pump()
        self.assertEqual(writes,s.globals().equipmentWrites)

    def test_owner_unavailable_after_transfer_does_not_block_waiting_player(self):
        n,_=concurrent();s=n.server;b=n.clients['friend']
        s.execute("""
            local key=CVPEquipmentPersistence.playerKeyAsync
            CVPEquipmentPersistence.playerKeyAsync=function(p)
                if p==player and rope:getContainer()~=storage then return nil end
                return key(p)
            end
        """)
        drain(n);b.execute('assert(answer.ok)')
        s.execute("""
            assert(not R.saveJob and #R.saveQueue==0)
            assert(otherRope:getContainer()~=player2.inv)
            local pending=0
            for key,row in pairs(CVPEquipmentRuntime.data.rows) do
                if row.state=='taking' then
                    pending=pending+1;assert(not require('CVP_Equipment').get(key))
                end
            end
            assert(pending==1)
        """)

    def test_cancel_waiting_batch_preserves_original_and_stops_retry(self):
        n,request=concurrent();s=n.server;b=n.clients['friend']
        b.execute("require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()")
        n.pump();drain(n)
        b.execute("assert(not answer.ok and answer.why=='IGUI_CVP_CancelledQueue' and otherRope:getContainer()==player2.inv)")
        s.execute("assert(otherRope:getContainer()==player2.inv);local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1)")
        n.send(request);n.pump();s.execute('assert(not R.saveJob and #R.saveQueue==0)')

    def test_waiting_disconnect_and_movement_reject_before_consumption(self):
        for change,reason in (("players={player}",'player disconnected'),("player2.x=player2.x+2",'endpoint not reachable')):
            n,_=concurrent();s=n.server;b=n.clients['friend'];s.execute(change)
            drain(n)
            self.assertEqual(b.eval('answer.why'),reason)
            s.execute('assert(otherRope:getContainer()==player2.inv)')

    def test_first_write_failure_does_not_block_other_player_or_lose_items(self):
        n,_=concurrent();s=n.server;b=n.clients['friend']
        s.execute("local write=CVPEquipmentPersistence.write;local fail=true;CVPEquipmentPersistence.write=function(data) if fail then fail=false;error('test write failure') end;return write(data) end")
        drain(n);b.execute('assert(answer.ok)')
        s.execute("assert(rope:getContainer()==storage and otherRope:getContainer()~=player2.inv);local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1)")

    def test_waiting_request_revalidates_target(self):
        n,_=concurrent();s=n.server;b=n.clients['friend']
        s.execute('car.x=100')
        drain(n);b.execute('assert(not answer.ok)')
        s.execute('assert(otherRope:getContainer()==player2.inv)')

    def test_cancel_committed_transfer_finishes_it_before_next_player(self):
        n,_=concurrent();s=n.server;a=n.clients['owner'];b=n.clients['friend']
        for _ in range(30):
            if s.eval('R.saveJob and R.saveJob.committed'):break
            s.execute('now=now+16;CVPMPServer.tick()');n.pump()
        s.execute('assert(R.saveJob.committed)')
        a.execute("require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()")
        n.pump();drain(n);b.execute('assert(answer.ok)')
        s.execute("assert(rope:getContainer()~=storage and otherRope:getContainer()~=player2.inv);local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==2)")

    def test_fifo_admission_and_timeout_do_not_start_waiting_operation(self):
        l=vm(True);l.execute(DELAY);l.execute('''
            ran={};answers={}
            R.request=function(_,p)
                ran[#ran+1]=p:getUsername()
                local ok,why=Jobs.call('checkpointSquare',{});return ok,nil,why
            end
            R:submit(player,'fixture',{},function(ok) answers[1]=ok end)
            R:submit(player2,'fixture',{},function(ok,_,why) answers[2]=why or ok end)
            R:submit(player2,'fixture',{},function(ok,_,why) assert(not ok and why=='equipment operation pending') end)
            assert(#R.saveQueue==1 and #ran==1)
            now=now+8000;R:tick({player,player2},.016)
            assert(answers[2]=='IGUI_CVP_ResultUnknown' and #ran==1 and #R.saveQueue==0)
            assert(rope:getContainer()==storage and otherRope:getContainer()==player2.inv)
        ''')

    def test_completion_callback_cannot_jump_a_waiting_player(self):
        l=vm(True);l.execute(DELAY);l.execute('''
            ran={};R.request=function(_,p)
                ran[#ran+1]=p:getUsername();local ok,why=Jobs.call('checkpointSquare',{});return ok,nil,why
            end
            R:submit(player,'fixture',{},function(ok)
                assert(ok);R:submit(player,'fixture',{},function(ok) assert(ok) end)
            end)
            R:submit(player2,'fixture',{},function(ok) assert(ok) end)
            for i=1,12 do R:tick({player,player2},.016) end
            assert(table.concat(ran,',')=='owner,friend,owner' and not R.saveJob and #R.saveQueue==0)
        ''')

if __name__=='__main__':unittest.main()
