"""Batch resource use/cancellation, native sound pacing and persisted attachment point."""
import unittest
from test_stock_visuals import single_player
from test_multiplayer import vm


def sp():
    lua=single_player()
    lua.execute('''
        function batch()
            batchMenu(false)
            while queued.endpoint=='vehicle' and not queued.done do finishAction() end
        end
        function finishAction() local a=queued;a:start();a:complete();a:perform() end
    ''')
    return lua


class NearbyNeckTests(unittest.TestCase):
    def test_batch_uses_each_item_once_and_saves_neck(self):
        lua=sp()
        lua.execute('''
            batch();assert(not body.md.CVPTether and not body2.md.CVPTether)
            local first=queued;finishAction();assert(#CVPTest.links()==1 and queued~=first)
            finishAction();assert(#CVPTest.links()==2 and #storage.rows==0)
            assert(body.md.CVPTether.connection.b.point=='neck' and body2.md.CVPTether.connection.b.point=='neck')
            assert(rope~=chain and rope.owner==CVPEquipmentRuntime.container and chain.owner==CVPEquipmentRuntime.container and worldCount(body)==1 and worldCount(body2)==1)
            callbacks.OnSave();assert(#CVPTest.links()==2 and body.md.CVPTether.connection.b.point=='neck')
        ''')
        lua.execute('''
            releaseAll()
            assert(rope.owner==storage and chain.owner==storage and worldCount(body)==1 and worldCount(body2)==1)
        ''')

    def test_batch_selects_each_body_endpoint_once(self):
        lua=sp()
        lua.execute("""
            body2.getAngle=function() return math.pi end
            carMenu();local count=0
            for _,o in ipairs(context.children) do
                if o.label==getText('IGUI_CVP_QuickNearby',getText('IGUI_CVP_Rope'),'1') then count=count+1 end
            end
            assert(count==1,'one vehicle batch action')
            batch();finishAction();finishAction()
            assert(body.md.CVPTether.connection.b.point=='neck' and body2.md.CVPTether.connection.b.point=='feet')
            car.x=-2;callbacks.OnSave()
            assert(body.md.CVPTether.connection.b.point=='neck' and body2.md.CVPTether.connection.b.point=='feet','choice stays fixed')
        """)

    def test_mp_automatic_request_and_authoritative_selection(self):
        lua=vm(False)
        lua.execute("""
            deferAction=true;CVPMPClient.neckAttach=true
            CVPMPClient.queueAction('attach',player,body,car,rope)
            queued:start();queued:perform();assert(#clientPackets==0)
            queued:start();queued:perform()
            assert(#clientPackets==1 and clientPackets[1].args.point==nil and clientPackets[1].args.finishAt=='vehicle')
        """)
        for angle,expected in ((0,'neck'),(3.141592653589793,'feet')):
            lua=vm(True)
            lua.execute("body.getAngle=function() return "+str(angle)+" end")
            lua.execute("assert(CVPMPServer.attach(player,body,car,rope));assert(body.md.CVPTether.connection.b.point=='"+expected+"')")

    def test_bulk_detach_is_sequential_and_cancel_keeps_remainder(self):
        lua=sp()
        lua.execute("""
            batch();finishAction();finishAction()
            carMenu();click(getText('IGUI_CVP_DetachAllMenu','2'))
            assert(#CVPTest.links()==2 and #storage.rows==0,'click must not release anything')
            local first=queued;first:start();assert(first.removing and first.maxTime>0)
            first:complete();first:perform()
            assert(#CVPTest.links()==1 and #storage.rows==1 and queued~=first)
            local second=queued;second:start();second:stop();second:perform()
            assert(#CVPTest.links()==1 and #storage.rows==1 and require('CVP_Batch').jobs[player]==nil)
            carMenu();click(getText('IGUI_CVP_DetachAllMenu','1'));finishAction()
            assert(#CVPTest.links()==0 and rope.owner==storage and chain.owner==storage)
            assert(worldCount(body)==1 and worldCount(body2)==1)
        """)

    def test_bulk_detach_approaches_and_stops_when_car_moves(self):
        lua=sp()
        lua.execute("""
            batch();finishAction();finishAction()
            body.x=6;body.sq:removeCorpse(body);gridSquare(6,0,0):addCorpse(body)
            luautils.walkAdj=function(p,q) p.x=q:getX();p.y=q:getY();return true end
            carMenu();click(getText('IGUI_CVP_DetachAllMenu','2'))
            finishAction();assert(queued.body==body and player.x==6)
            speed=3;queued:perform()
            assert(#CVPTest.links()==1 and body.md.CVPTether and require('CVP_Batch').jobs[player]==nil)
        """)

    def test_mp_bulk_detach_waits_for_each_ack(self):
        lua=vm(False)
        lua.execute("""
            deferAction=true;CVPMPClient.bulkDetach=true
            for _,b in ipairs({body,body2}) do
                CVPMPClient.links[b.netID]={body=b,target={vehicle=7,gearID=b==body and rope.id or chain.id,connection=require('CVP_Connection').create(b,'car','feet')}}
            end
            CVPMPClient.requestDetachAll(player,car)
            local first=queued;assert(#clientPackets==0);first:start();first:perform()
            assert(#clientPackets==1 and clientPackets[1].name=='detach' and queued==first)
            CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=1,ok=true,message='IGUI_CVP_Released'})
            assert(queued~=first);queued:start();queued:perform()
            assert(#clientPackets==2 and clientPackets[2].name=='detach')
            assert(clientPackets[1].args.id~=clientPackets[2].args.id)
            CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=2,ok=false,message='IGUI_CVP_LetGo'})
            assert(require('CVP_Batch').jobs[player]==nil)
            assert(rope.owner==storage and chain.owner==storage,'client never changes inventory')
        """)

    def test_cancel_and_vehicle_movement_stop_batch_without_consumption(self):
        for cancel in ('queued:stop()', 'speed=3;queued:perform()'):
            lua=sp()
            lua.execute("batch();queued:start();"+cancel+'''
                assert(#CVPTest.links()==0 and rope.owner==storage and chain.owner==storage)
                assert(require('CVP_Batch').jobs[player]==nil)
            ''')

    def test_more_bodies_than_equipment_and_empty_inventory(self):
        lua=sp()
        lua.execute('''
            local third=corpse();third.world=false;sq:addCorpse(third)
            batch();finishAction();finishAction()
            assert(#CVPTest.links()==2 and #storage.rows==0 and require('CVP_Batch').jobs[player]==nil)
            local attached=0;for _,b in ipairs(bodies) do if b.md.CVPTether then attached=attached+1 end end
            assert(attached==2 and #bodies==3)
            menu();local name=getText('IGUI_CVP_AttachNearest','TestCar')
            for _,o in ipairs(options) do if o.label:find(name,1,true) then assert(o.notAvailable) end end
        ''')

    def test_removed_body_and_lost_server_reply_do_not_continue(self):
        lua=sp()
        lua.execute('''
            batch();local a=queued;local b=a.body;b.sq:removeCorpse(b)
            a:perform();assert(#CVPTest.links()==0 and rope.owner==storage and chain.owner==storage)
            assert(require('CVP_Batch').jobs[player]==nil)
        ''')
        lua=vm(False)
        lua.execute('''
            deferAction=true;CVPMPClient.neckAttach=true
            local B=require 'CVP_Batch'
            B.start(player,car,'feet',function(p,b,v,g,point,after,approach,mode)
                return CVPMPClient.queueAction('attach',p,b,v,g,point,after,approach,mode)
            end,function() return 0 end)
            while queued.endpoint=='vehicle' and not queued.done do queued:start();queued:perform() end
            local a=queued;a:start();a:perform();assert(#clientPackets==1)
            now=12000;CVPMPClient.tick();assert(B.jobs[player]==nil)
            CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=1,ok=true,message='IGUI_CVP_AttachedOne'})
            assert(queued==a and rope.owner==storage and chain.owner==storage)
        ''')

    def test_limit_nested_inventory_and_unreachable_body(self):
        lua=sp()
        lua.execute('''
            local bag=item('Base.Bag');bag.kind='InventoryContainer';bag.inv=container()
            bag.getInventory=function(s) return s.inv end;storage:AddItem(bag)
            storage:Remove(rope);bag.inv:AddItem(rope)
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1
            batch();finishAction();assert(#CVPTest.links()==1 and chain.owner==storage)
            assert(require('CVP_Batch').jobs[player]==nil)
            releaseAll();SandboxVars.CorpseProxyLab.MaxBodiesPerChain=8
            body.sq:removeCorpse(body);body.x=1;gridSquare(1,0,0):addCorpse(body)
            body2.sq:removeCorpse(body2);body2.x=6;gridSquare(6,0,0):addCorpse(body2)
            noPath=true
            batch()
            assert(#CVPTest.links()==0 and not body.md.CVPTether and not body2.md.CVPTether)
            assert(require('CVP_Batch').jobs[player]==nil and rope.owner==storage and chain.owner==storage)
        ''')

    def test_chain_handling_stays_silent(self):
        lua=sp()
        lua.execute("""
            player:getModData().CVPMaterial='Base.HeavyChain';menu();click('(цепь)');local a=queued;a:start()
            for i=1,20 do now=i*100;a:update() end
            a:stop();assert(#sounds==0 and #stops==0)
        """)

    def test_neck_orientation_collision_and_binding_repair(self):
        lua=sp()
        lua.execute('''
            CVPTest.attach(player,body,car,rope,'neck')
            local r=CVPTest.links()[1];assert(r.point=='neck' and r.attachLocalX>0 and r.footLocalX<0)
            local radius=r.footprintRadius;local samples=#r.footprint
            local Rope=require 'CVP_Rope'
            for i=1,140 do r.x,r.y=Rope.step(r,r.x,r.y,4+i*.1,0,.05) end
            local x,y=Rope.feet(r);assert(x>r.x+.4 and math.abs(y-r.y)<.1)
            assert(r.footprintRadius==radius and #r.footprint==samples)
            local md=body.md.CVPTether
            require('CVP_Core').unregister(CVPRuntime.registry,CVPRuntime.links[1]);CVPRuntime.pending={};callbacks.OnGameStart()
            assert(#CVPTest.links()==1 and CVPTest.links()[1].point=='neck')
            -- A damaged body save is repaired from the committed equipment binding.
            require('CVP_Core').unregister(CVPRuntime.registry,CVPRuntime.links[1]);md.point=nil;md.connection=nil;callbacks.OnGameStart()
            assert(#CVPTest.links()==1 and body.md.CVPTether.connection.b.point=='neck')
            releaseAll();assert(worldCount(body)==1 and rope.owner==storage)
        ''')

    def test_mp_batch_waits_for_ack_and_stops_on_rejection(self):
        lua=vm(False)
        lua.execute('''
            deferAction=true;CVPMPClient.neckAttach=true
            local B=require 'CVP_Batch'
            B.start(player,car,'neck',function(p,b,v,g,point,after,approach,mode)
                return CVPMPClient.queueAction('attach',p,b,v,g,point,after,approach,mode)
            end,function() return 0 end)
            while queued.endpoint=='vehicle' and not queued.done do queued:start();queued:perform() end
            local first=queued;first:start();first:perform()
            assert(#clientPackets==1 and clientPackets[1].args.point=='neck' and queued==first)
            CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=1,ok=true,message='IGUI_CVP_AttachedOne'})
            assert(queued~=first);queued:start();queued:perform()
            assert(#clientPackets==2 and clientPackets[1].args.gear~=clientPackets[2].args.gear)
            CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=2,ok=false,message='IGUI_CVP_VehicleLimit'})
            assert(B.jobs[player]==nil and rope.owner==storage and chain.owner==storage)
        ''')

    def test_server_neck_validation_and_snapshot(self):
        lua=vm(True)
        lua.execute('''
            assert(not CVPMPServer.attach(player,body,car,rope,'invalid') and rope.owner==storage)
            assert(CVPMPServer.attach(player,body,car,rope,'neck'))
            local r=CVPMPServer.links[1];assert(r.attachLocalX>0 and r.md.connection.b.point=='neck')
            now=now+1000;CVPMPServer.tick()
            local found=false
            for _,p in ipairs(packets) do if p.name=='state' then
                assert(p.args.neckAttach);assert(p.args.rows[1].point=='neck' and p.args.rows[1].footX>0);found=true
            end end
            assert(found and worldCount(body)==1)
        ''')


if __name__=='__main__': unittest.main()
