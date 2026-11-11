"""End-to-end linear towing through the authoritative adapters and MP observer."""
import unittest
from test_core_lifecycle import environment
from test_multiplayer import vm, copy_packet, deliver


def train(server, count=2, limit=None, spacing=None, material=None):
    lua=environment(server)
    if limit is not None:
        lua.execute("SandboxVars.CorpseProxyLab.MaxBodiesPerChain="+str(limit))
    lua.globals().trainCount=count
    lua.globals().trainSpacing=spacing
    lua.globals().trainMaterial=material
    lua.execute("""
        if trainSpacing then
            -- A two-metre rear hitch; preserve the original initial anchor.
            car.x=car.x+2;car.heading=0
            car.getWorldPos=function(s,a,b,c,out)
                out.xx=s.x+c*math.cos(s.heading)-a*math.sin(s.heading)
                out.yy=s.y+c*math.sin(s.heading)+a*math.cos(s.heading)
            end
        end
        if trainMaterial then rope.t=trainMaterial end
        assert(attach('feet'))
        local Core=require 'CVP_Core'
        trainBodies={body};trainRecords={links()[1]}
        for i=2,trainCount do
            local b
            if i==2 then b=body2 else
                b=corpse();b.getSquare=body.getSquare;b.setSquare=body.setSquare
                b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;sq:addCorpse(b)
            end
            b.netID=tostring(10000+i)
            if trainSpacing then
                b:getSquare():removeCorpse(b)
                b.x=-(i-1)*trainSpacing
                gridSquare(math.floor(b.x),math.floor(b.y),b.z):addCorpse(b)
                player.x=b.x
            end
            local gear=item(trainMaterial or 'Base.Rope');storage:AddItem(gear)
            local parent=trainRecords[i-1]
            if serverMode then
                assert(CVPMPServer.attach(player,b,car,gear,'feet','body',parent.body,parent.connection.id))
            else CVPTest.attach(player,b,car,gear,'feet',false,parent) end
            local r=(serverMode and CVPMPServer.registry or CVPRuntime.registry).byBody[b]
            assert(r and r.parent==parent and r.connection.a.object==parent.body)
            trainBodies[i]=b;trainRecords[i]=r
        end
        function stepTrain(dt)
            now=now+dt*1000
            if serverMode then CVPMPServer.tick() else callbacks.OnTick() end
        end
    """)
    return lua


class TrainTests(unittest.TestCase):
    def test_obstructed_middle_releases_tail_without_poisoning_prefix(self):
        for server in (False, True):
            lua=train(server,3)
            lua.execute("""
                local Geometry=require 'CVP_Geometry'
                local resolve=Geometry.resolve
                local middle=trainRecords[2]
                local bx,by=middle.x,middle.y
                Geometry.resolve=function(r,x,y,angle,oldAngle)
                    if r==middle then return bx,by,oldAngle,true end
                    return resolve(r,x,y,angle,oldAngle)
                end
                for i=1,650 do
                    car.x=car.x+.05;player.x=car.x;stepTrain(1/60)
                end
                assert(#links()==1,'obstructed tail must release, not freeze the whole chain')
                assert(links()[1]==trainRecords[1] and not links()[1].failed)
                assert(middle.body.x==bx and middle.body.y==by,'blocked body teleported')
                for i,b in ipairs(trainBodies) do
                    assert(worldCount(b)==1,'lost or duplicated world corpse')
                    if i>1 then
                        assert(not b.md.CVPTether,'stale binding')
                        local gear=trainRecords[i].gear
                        assert(gear:getWorldItem() or storage:getItems():contains(gear),'lost tether')
                    end
                end
            """)

    def test_hitch_out_of_range_releases_all_without_duplicates(self):
        for server in (False, True):
            lua=train(server,3)
            lua.execute("""
                car.x=25;player.x=car.x
                stepTrain(1/60);stepTrain(1/60)
                assert(#links()==0,'out-of-range root remained active')
                for _,b in ipairs(trainBodies) do
                    assert(not b.md.CVPTether and worldCount(b)==1)
                end
                car.x=0;player.x=0
                for i=1,5 do stepTrain(.1) end
                assert(#links()==0,'released links resurrected on reverse')
            """)

    def test_release_middle_invalidates_unloaded_tail_and_keeps_prefix(self):
        for server in (False,True):
            lua=train(server,3)
            lua.execute("""
                local Core=require 'CVP_Core'
                local last=trainRecords[3];local middle=trainRecords[2]
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                Core.unregister(reg,last)
                if serverMode then CVPMPServer.byID[last.id]=nil end
                if serverMode then assert(CVPMPServer.detach(player,middle.body))
                else CVPTest.stop(middle,'test') end
                assert(not car.md.CVPConnections[last.connection.id])
                if serverMode then CVPMPServer.discover()
                else CVPTest.discover(last.body:getSquare());CVPTest.resume() end
                assert(not last.body.md.CVPTether and #links()==1 and links()[1]==trainRecords[1])
            """)

    def test_unloaded_middle_pauses_and_resumes(self):
        for server in (False,True):
            lua=train(server,3)
            lua.execute("""
                local middle=trainBodies[2];local square=middle.getSquare
                middle.getSquare=function() return nil end
                local x=trainRecords[1].x
                car.x=4;stepTrain(.1);stepTrain(.1)
                assert(trainRecords[1].x==x and middle.md.CVPTether)
                middle.getSquare=square
                for i=1,4 do
                    if serverMode then CVPMPServer.discover()
                    else for _,b in ipairs(trainBodies) do CVPTest.discover(b:getSquare()) end;CVPTest.resume() end
                end
                stepTrain(.1)
                assert(#links()==3)
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                assert(reg.byBody[trainBodies[3]].parent==reg.byBody[middle])
                for _,r in ipairs(links()) do assert(not r.failed and not r.chainWaiting) end
            """)

    def test_branch_cycle_and_stale_source_rejected(self):
        lua=train(True,2)
        lua.execute("""
            local gear=item('Base.Rope');storage:AddItem(gear)
            local root=trainRecords[1];local child=trainRecords[2]
            assert(not CVPMPServer.attach(player,body,car,gear,'feet','body',child.body,child.connection.id))
            local b=corpse();b.netID='77'
            assert(not CVPMPServer.attach(player,b,car,gear,'feet','body',root.body,root.connection.id))
            assert(not CVPMPServer.attach(player,b,car,gear,'feet','body',child.body,'stale'))
            assert(gear.owner==storage and #links()==2)
        """)

    def test_network_roundtrip_and_client_chain_command(self):
        server=train(True,2);server.execute('stepTrain(.1)')
        client=vm(False)
        client.execute("body2.netID='10002';CVPRopeScene.updateBody=function(...) bodyRenders=(bodyRenders or 0)+1 end")
        packet=copy_packet(server.globals().packets[1])
        deliver(client,packet);client.execute('now=100;CVPMPClient.tick()')
        client.execute("""
            local r=CVPMPClient.links[body2.netID]
            assert(r.target.connection.a.kind=='body' and r.sourceBody==body)
            assert(body2.md.CVPTether.parentConnection and bodyRenders==1)
            CVPMPClient.requestDetachAll(player,car)
            assert(#clientPackets==1)
            -- ACK arrives before the terminal snapshot. The child must not
            -- generate a second detach against an already released server link.
            CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=1,ok=true,message='IGUI_CVP_Released'})
            assert(#clientPackets==1 and require('CVP_Batch').jobs[player]==nil)
        """)

    def test_two_body_action_and_cancellation(self):
        for cancelled in (False,True):
            lua=environment(False);lua.globals().cancelled=cancelled
            lua.execute("""
                assert(attach());local root=links()[1];deferAction=true
                assert(CVPTest.chain(player,body2,root,chain))
                local first=queued;assert(first.body==body)
                first:start();first:complete();first:perform()
                assert(queued~=first and queued.body==body2)
                if cancelled then body.x=body.x+1 end
                queued:start();queued:complete();queued:perform()
                assert(#links()==(cancelled and 1 or 2))
                assert(chain.owner==(cancelled and storage or CVPEquipmentRuntime.container))
            """)

    def test_client_action_sends_authoritative_source_identity(self):
        server=environment(True);server.execute('assert(attach());now=100;CVPMPServer.tick()')
        client=vm(False)
        deliver(client,copy_packet(server.globals().packets[1]))
        client.execute("""
            now=100;CVPMPClient.tick()
            local root=CVPMPClient.links[body.netID]
            assert(CVPMPClient.queueChain(player,body2,root,chain))
            assert(#clientPackets==1 and clientPackets[1].name=='chain')
            assert(clientPackets[1].args.source==body.netID)
            assert(clientPackets[1].args.sourceConnection==root.target.connection.id)
            assert(chain.owner==storage and not body2.md.CVPTether)
        """)
        args=copy_packet(client.globals().clientPackets[1].args)
        server.globals().incoming=server.table_from(args,recursive=True)
        server.execute("""
            now=500;callbacks.OnClientCommand('CVP','chain',player,incoming)
            assert(#CVPMPServer.links==2 and CVPMPServer.links[2].parent==CVPMPServer.links[1])
        """)

    def test_fresh_save_restore_uses_persistent_ids(self):
        for server in (False,True):
            old=train(server,3)
            data=[copy_packet(old.globals().trainBodies[i].md) for i in range(1,4)]
            car=copy_packet(old.globals().car.md)
            equipment=copy_packet(old.eval('serializeEquipment()'))
            fresh=environment(server)
            fresh.globals().saved=fresh.table_from(data,recursive=True)
            fresh.globals().savedCar=fresh.table_from(car,recursive=True)
            fresh.globals().savedEquipment=fresh.table_from(equipment,recursive=True)
            fresh.execute("""
                car.md=savedCar;storage:Remove(rope);storage:Remove(chain);loadEquipment(savedEquipment)
                local third=corpse();third.getSquare=body.getSquare;third.setSquare=body.setSquare
                third.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;sq:addCorpse(third)
                local all={body,body2,third}
                for i,b in ipairs(all) do
                    b.md=saved[i];b.netID=tostring(20000+i)
                    assert(#b.inv.rows==1,'corpse save must contain only original loot')
                end
                for i=1,4 do restore() end
                assert(#links()==3)
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                assert(reg.byBody[body2].parent==reg.byBody[body])
                assert(reg.byBody[third].parent==reg.byBody[body2])
                assert(reg.byBody[third].connection.id==saved[3].CVPTether.connection.id)
            """)

    def test_slack_upstream_transmits_no_tail_load(self):
        lua=train(True,3)
        lua.execute("""
            local Core=require 'CVP_Core'
            for _,r in ipairs(links()) do r.taut=true end
            assert(Core.connected(trainRecords[3]))
            trainRecords[2].taut=false
            assert(not Core.connected(trainRecords[3]))
            assert(Core.connected(trainRecords[1]))
        """)

    def test_loaded_tail_release_returns_equipment_and_keeps_prefix(self):
        for server in (False,True):
            lua=train(server,3)
            lua.execute("""
                local gear=trainRecords[2].gear;local tailGear=trainRecords[3].gear
                if serverMode then assert(CVPMPServer.detach(player,trainBodies[2]))
                else CVPTest.stop(trainRecords[2],'test') end
                assert(#links()==1 and links()[1]==trainRecords[1])
                assert(gear.owner==storage and tailGear.owner==storage)
                assert(not trainBodies[2].md.CVPTether and not trainBodies[3].md.CVPTether)
            """)

    def test_deleted_middle_releases_tail(self):
        for server in (False,True):
            lua=train(server,3)
            lua.execute("""
                trainBodies[2]:getSquare():removeCorpse(trainBodies[2])
                stepTrain(.1);stepTrain(.1)
                assert(#links()==1 and links()[1]==trainRecords[1])
                assert(not trainBodies[3].md.CVPTether)
            """)

    def test_dormant_tail_terminal_is_valid_protocol(self):
        lua=train(True,2)
        lua.execute("""
            local Core=require 'CVP_Core';local r=trainRecords[2]
            Core.unregister(CVPMPServer.registry,r);CVPMPServer.byID[r.id]=nil
            assert(CVPMPServer.detach(player,r.body))
            local row=CVPMPServer.terminal[r.id].row
            assert(require('CVP_Protocol').row(row))
            assert(not row.active and row.connection.a.kind=='body')
        """)


if __name__=='__main__':
    unittest.main()
