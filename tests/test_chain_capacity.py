import unittest
from test_trains import train


class ChainCapacityTests(unittest.TestCase):
    def test_32_move_and_restore_after_unload(self):
        for server in (False, True):
            lua = train(server, 32)
            lua.execute("""
                for i=1,30 do car.x=car.x+.02;player.x=car.x;stepTrain(1/60) end
                assert(#links()==32)
                for _,r in ipairs(links()) do assert(not r.failed and r.chainTick==now) end
                local square=car.getSquare
                car.getSquare=function() return nil end;stepTrain(1/60)
                car.getSquare=square
                for i=1,33 do restore() end
                assert(#links()==32,'long saved chain did not restore')
                stepTrain(1/60)
                for _,r in ipairs(links()) do assert(not r.failed and not r.chainWaiting) end
            """)

    def test_default_32_is_per_root_and_tail_release_visits_all(self):
        for server in (False, True):
            lua = train(server, 32)
            lua.execute("""
                local World=require 'CVP_World'
                local Core=require 'CVP_Core'
                assert(World.maxChain()==32 and #links()==32)
                for _,r in ipairs(trainRecords) do r.taut=true end
                assert(Core.connected(trainRecords[32]))
                local b=corpse();b.getSquare=body.getSquare;b.setSquare=body.setSquare
                b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;sq:addCorpse(b)
                b.netID='30000';local gear=item('Base.Rope');storage:AddItem(gear)
                local tail=trainRecords[32]
                if serverMode then
                    local ok,reason=CVPMPServer.attach(player,b,car,gear,'feet','body',tail.body,tail.connection.id)
                    assert(not ok and reason=='IGUI_CVP_VehicleLimit')
                    assert(CVPMPServer.attach(player,b,car,gear))
                else
                    CVPTest.attach(player,b,car,gear,'feet',false,tail)
                    assert(not b.md.CVPTether and gear.owner==storage)
                    CVPTest.attach(player,b,car,gear)
                end
                assert(#links()==33,'independent root shares no chain budget')
                local middle=trainRecords[16]
                if serverMode then assert(CVPMPServer.detach(player,middle.body))
                else CVPTest.stop(middle,'capacity test') end
                stepTrain(0);stepTrain(0)
                assert(#links()==16,'prefix and independent root must survive')
                for i=16,32 do assert(not trainBodies[i].md.CVPTether and worldCount(trainBodies[i])==1) end
            """)

    def test_unlimited_exceeds_old_server_cap_and_retains_ancestry(self):
        for server in (False, True):
            lua = train(server, 65, limit=0)
            lua.execute("""
                local Core=require 'CVP_Core'
                assert(#links()==65)
                for _,r in ipairs(trainRecords) do r.taut=true end
                assert(Core.connected(trainRecords[65]))
                -- Restoration validation must traverse more than the old eight ancestors.
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                local status=Core.restore(trainBodies[65],trainBodies[65].md.CVPTether,Core.loadedVehicles(),reg)
                assert(status=='ready',status)
                Core.endTail(trainRecords[1])
                for _,b in ipairs(trainBodies) do assert(worldCount(b)==1) end
                assert(next(car.md.CVPConnections)==nil)
            """)

if __name__ == '__main__':
    unittest.main()
