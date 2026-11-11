"""Both endpoints, walking cancellation, batch order and final server validation."""
import unittest
from test_stock_visuals import single_player
from test_multiplayer import vm


def setup(lua):
    lua.execute('''
        deferAction=true;deferPath=true
        function finishStage()
            local a=queued;a:start();a:perform();return a
        end
        function beginSingle() menu(body);click('(верёвка)') end
        function beginBatch() batchMenu(false) end
    ''')
    return lua


class TieSequenceTests(unittest.TestCase):
    def test_body_then_hitch_with_no_early_mutation(self):
        lua=setup(single_player())
        lua.execute('''
            car.x=6;beginSingle()
            assert(queued.isPath and queued.x==body.x)
            finishStage();local bodyAction=queued
            assert(bodyAction.endpoint=='body')
            finishStage();assert(queued.isPath and queued.x>5)
            assert(not body.md.CVPTether and rope.owner==storage)
            finishStage();local hitchAction=queued;assert(hitchAction.endpoint=='vehicle')
            hitchAction:start();assert(hitchAction.anim=='VehicleTrailer')
            player.faceLocationF=function(_,x,y) facingX=x;facingY=y end
            hitchAction:waitToStart();assert(facingX==6 and facingY==0)
            hitchAction:perform();hitchAction:perform()
            assert(#CVPTest.links()==1 and rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
            assert(player.x>5 and not body2.md.CVPTether)
        ''')

    def test_batch_prepares_all_at_hitch_then_visits_bodies_once(self):
        lua=setup(single_player())
        lua.execute('''
            car.x=6;beginBatch();assert(queued.isPath and queued.x>5)
            finishStage();assert(queued.endpoint=='vehicle');finishStage()
            assert(queued.endpoint=='vehicle','second rope at same hitch without another walk')
            assert(#CVPTest.links()==0 and rope.owner==storage and chain.owner==storage)
            finishStage();assert(queued.isPath and queued.x==0)
            finishStage();assert(queued.endpoint=='body');finishStage()
            assert(#CVPTest.links()==1 and queued.isPath and queued.x==0)
            finishStage();assert(queued.endpoint=='body');finishStage()
            assert(#CVPTest.links()==2 and #storage.rows==0 and not require('CVP_Batch').jobs[player])
        ''')

    def test_cancel_every_single_stage_preserves_originals(self):
        for stage in range(4):
            with self.subTest(stage=stage):
                lua=setup(single_player())
                lua.execute(f'''
                    car.x=6;beginSingle()
                    for i=1,{stage} do finishStage() end
                    local a=queued;a:stop();a:perform()
                    assert(#CVPTest.links()==0 and rope.owner==storage and worldCount(body)==1)
                    assert(not body.md.CVPTether and queued==a)
                ''')

    def test_batch_cancel_keeps_completed_body_and_unused_item(self):
        lua=setup(single_player())
        lua.execute('''
            car.x=6;beginBatch()
            for i=1,5 do finishStage() end
            assert(#CVPTest.links()==1 and queued.isPath)
            queued:stop();queued:perform()
            assert(#CVPTest.links()==1 and #storage.rows==1 and not require('CVP_Batch').jobs[player])
            assert(worldCount(body)==1 and worldCount(body2)==1)
        ''')

    def test_changed_targets_or_gear_abort_between_ends(self):
        for mutation in ('car.x=7', 'body.x=1', 'speed=2', 'storage:Remove(rope)',
                         'storage:Remove(rope);container():AddItem(rope)', 'driving=true',
                         'body.sq:removeCorpse(body)', 'player.isDead=function() return true end'):
            with self.subTest(mutation=mutation):
                lua=setup(single_player())
                lua.execute('car.x=6;beginSingle();finishStage();finishStage();'+mutation+'''
                    finishStage()
                    assert(#CVPTest.links()==0 and not body.md.CVPTether)
                    assert(not CVPEquipmentRuntime or rope.owner~=CVPEquipmentRuntime.container)
                ''')

    def test_failed_path_aborts_batch_without_item_moves(self):
        lua=setup(single_player())
        lua.execute('''
            car.x=6;beginBatch();local path=queued;path.onFail();path:stop();path:perform()
            assert(not require('CVP_Batch').jobs[player] and #CVPTest.links()==0)
            assert(rope.owner==storage and chain.owner==storage)
        ''')

    def test_force_cancel_pending_path_discards_batch(self):
        lua=setup(single_player())
        lua.execute('''
            car.x=6;beginBatch();queued:forceCancel();queued:perform()
            assert(not require('CVP_Batch').jobs[player] and #CVPTest.links()==0)
            assert(rope.owner==storage and chain.owner==storage)
        ''')

    def test_batch_does_not_retarget_prepared_rope_after_body_moves(self):
        lua=setup(single_player())
        lua.execute('''
            car.x=6;beginBatch();finishStage();finishStage()
            assert(queued.endpoint=='vehicle');body.x=1;finishStage()
            assert(not require('CVP_Batch').jobs[player] and #CVPTest.links()==0)
            assert(rope.owner==storage and chain.owner==storage)
        ''')

    def test_mp_sends_only_after_second_end_and_old_server_is_blocked(self):
        lua=setup(vm(False))
        lua.execute('''
            car.x=6;CVPMPClient.queueAction('attach',player,body,car,rope)
            for i=1,3 do finishStage();assert(#clientPackets==0) end
            finishStage();local last=queued;last:perform()
            assert(#clientPackets==1 and clientPackets[1].args.finishAt=='vehicle')
            assert(rope.owner==storage and not body.md.CVPTether)
            CVPMPClient.twoPointAttach=false
            local a=queued
            CVPMPClient.queueAction('attach',player,body,car,rope,nil,nil,true)
            assert(queued==a and #clientPackets==1)
        ''')

    def test_server_checks_final_endpoint_not_remote_corpse_adjacency(self):
        lua=vm(True)
        lua.execute('''
            car.x=6;player.x=6.85
            -- Match native canReachTo: only neighbouring grid squares qualify.
            for x=0,8 do local q=gridSquare(x,0,0)
                q.canReachTo=function(s,other) return math.abs(s.x-other.x)<=1 and math.abs(s.y-other.y)<=1 end
            end
            assert(not CVPMPServer.attach(player,body,car,rope,'feet','body'))
            assert(not CVPMPServer.attach(player,body,car,rope,'feet','invalid'))
            player.x=10;assert(not CVPMPServer.attach(player,body,car,rope,'feet','vehicle'))
            player.x=6.85;speed=3;assert(not CVPMPServer.attach(player,body,car,rope,'feet','vehicle'))
            speed=0;assert(CVPMPServer.attach(player,body,car,rope,'feet','vehicle'))
            assert(rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
        ''')


if __name__=='__main__': unittest.main()
