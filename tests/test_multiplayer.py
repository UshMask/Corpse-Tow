"""Isolated Lua server and two clients; native replication is tested separately in Java.

Uses a fresh shared engine fixture for each isolated Lua runtime.
Packets are copied through Python so no Lua object references cross the network.
"""
from pathlib import Path
import unittest
from lua_fixture import copy_packet

ROOT = Path('CorpseProxyLab/42/media/lua')
LEGACY = Path('tests/fixtures/v031')


def vm(server, handshake=True):
    from legacy_fixture import create_legacy_fixture
    env = create_legacy_fixture()
    lua = env['L']
    lua.globals().server = server
    lua.execute('''
        function isServer() return server end
        function isClient() return not server end
        function list(t) return {size=function() return #t end,get=function(_,i) return t[i+1] end,
            contains=function(_,v) for _,a in ipairs(t) do if a==v then return true end end return false end,
            iterator=function() local i=0;return {hasNext=function() return i<#t end,next=function() i=i+1;return t[i] end} end} end
        player.getPrimaryHandItem=function() return nil end;player.getSecondaryHandItem=function() return nil end
        player2=actor('IsoPlayer',0,0);player2.inv=container();player2.inv.parent=player2
        player2.md={};player2.getModData=function(s) return s.md end
        player2.getInventory=function(s) return s.inv end;player2.getVehicle=function() return nil end
        player2.isDead=function(s) return s.dead or false end
        player.getUsername=function() return 'owner' end
        player2.getUsername=function() return 'friend' end
        player2.getSquare=player.getSquare
        player2.getPrimaryHandItem=player.getPrimaryHandItem;player2.getSecondaryHandItem=player.getSecondaryHandItem
        otherRope=item('Base.Rope');player2.inv:AddItem(otherRope)
        players={player,player2};function getOnlinePlayers() return list(players) end
        car.getId=function() return 7 end;car.isLocalPhysicSim=function() return physicsOwner==true end
        car.getCurrentSpeedKmHour=function() return speed or 0 end
        -- Build 42 returns a Java Set, which has no indexed get().
        cell.getVehicles=function() local rows=list({car});rows.get=nil;return rows end
        function getVehicleById(id) if id==7 then return car end end
        body.netID='9007199254740993';body2.netID='9007199254740994'
        for _,b in ipairs(bodies) do b.getAngle=function(s) return s.angle or 0 end end
        CVPNetwork={id=function(b) return b.netID end,bodies=function()
            local found={};for _,b in ipairs(bodies) do if b.world then found[#found+1]=b end end;return list(found) end,
            find=function(id) for _,b in ipairs(bodies) do if b.netID==id and b.world then return b end end end,
            encode=function(b) return 'encoded:'..b.netID end,
            receive=function(id,payload)
                assert(payload=='encoded:'..id);local b=CVPNetwork.find(id);if b then return b end
                -- Mimic native chunk replication while counting actual registrations.
                b=body;b.netID=id;b.x=0;b.y=0;b.world=false;sq:addCorpse(b);replicas=(replicas or 0)+1;return b
            end}
        packets={};containerPackets={};clientPackets={}
        function sendServerCommand(p,m,n,a) packets[#packets+1]={player=p==player and 1 or 2,name=n,args=a} end
        function sendClientCommand(p,m,n,a) clientPackets[#clientPackets+1]={name=n,args=a} end
        function sendRemoveItemFromContainer(c,i) if c:getCharacter() or c:getParent() then containerPackets[#containerPackets+1]={kind='remove',id=i.id} end end
        function sendAddItemToContainer(c,i) if c:getCharacter() or c:getParent() then containerPackets[#containerPackets+1]={kind='add',id=i.id} end end
        tracked={};CVPViewpoint={track=function(b) tracked[b]=true end,untrack=function(b) tracked[b]=nil end,clear=function() tracked={} end}
        CVPRopeScene={update=function() rendered=(rendered or 0)+1 end,untrack=function() end,clear=function() end}
        function command(name,p,args) now=now+300;args.protocol=3;callbacks.OnClientCommand('CVP',name,p,args) end
    ''')
    lua.execute("package.preload['CVP_Motion']=assert(loadstring(...))",
                (ROOT/'client/CVP_Motion.lua').read_text(encoding='utf-8'))
    for name in ('CVP_Protocol',):
        lua.execute("package.preload[...]=assert(loadstring(select(2,...)))", name,
                    (ROOT/'shared'/(name+'.lua')).read_text(encoding='utf-8'))
    path = LEGACY/('CVP_MPServer.lua' if server else 'CVP_MPClient.lua')
    lua.execute(path.read_text(encoding='utf-8'))
    if not server and handshake:
        lua.execute("CVPMPClient.receive('state',{protocol=3,epoch='fixture',sequence=0,rows={},twoPointAttach=true})")
    return lua


def deliver(client, packet):
    client.globals().CVPMPClient.receive(packet['name'], client.table_from(packet['args'], recursive=True))


class MultiplayerTests(unittest.TestCase):
    def setUp(self):
        self.s = vm(True)

    def test_server_settings_and_legacy_owner(self):
        self.s.execute('''
            body.isZombie=function() return false end
            SandboxVars.CorpseProxyLab.AllowPlayerCorpses=false
            local ok,reason=CVPMPServer.attach(player,body,car,rope)
            assert(not ok and reason=='IGUI_CVP_PlayerBodiesDisabled' and rope.owner==storage)
            SandboxVars.CorpseProxyLab.AllowPlayerCorpses=true
            assert(CVPMPServer.attach(player,body,car,rope))
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1
            ok,reason=CVPMPServer.attach(player2,body2,car,otherRope)
            assert(ok and otherRope.owner==CVPEquipmentRuntime.container)
            assert(CVPMPServer.detach(player2,body2))
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            ok,reason=CVPMPServer.detach(player2,body)
            assert(not ok and reason=='IGUI_CVP_OtherOwner' and rope.owner==CVPEquipmentRuntime.container)
            assert(CVPMPServer.detach(player,body) and rope.owner==storage)
            assert(CVPMPServer.attach(player,body,car,rope))
            body.md.CVPTether.owner=nil
            assert(require('CVP_Equipment').updateBindings({{key=body.md.CVPTether.equipmentKey,body=body,metadata=body.md.CVPTether}}))
            assert(CVPMPServer.detach(player2,body) and rope.owner==player2.inv)
        ''')

    def test_bulk_detach_is_scoped_safe_and_idempotent(self):
        self.attach()
        self.s.execute('''
            assert(CVPMPServer.attach(player2,body2,car,otherRope))
            speed=10;command('detachAll',player,{request=2,vehicle=7})
            assert(#CVPMPServer.links==2)
            speed=0;player.x=20;command('detachAll',player,{request=3,vehicle=7})
            assert(#CVPMPServer.links==2)
            player.x=0;SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            command('detachAll',player,{request=4,vehicle=7})
            assert(#CVPMPServer.links==1 and rope.owner==storage and otherRope.owner==CVPEquipmentRuntime.container)
            assert(packets[#packets].args.message=='IGUI_CVP_BulkPartial')
            SandboxVars.CorpseProxyLab.AllowDetachOthers=true
            command('detachAll',player,{request=5,vehicle=7})
            assert(#CVPMPServer.links==0 and otherRope.owner==storage)
            local n=#containerPackets
            command('detachAll',player,{request=5,vehicle=7})
            command('detachAll',player,{request=6,vehicle=7})
            assert(#containerPackets==n and worldCount(body)==1 and worldCount(body2)==1)
        ''')

    def test_bulk_inventory_failure_retains_tether_for_retry(self):
        self.attach()
        self.s.execute('''
            local add=storage.AddItem;storage.AddItem=function() end
            local ok,reason=CVPMPServer.detachAll(player,car)
            assert(not ok and reason=='IGUI_CVP_BulkPartial')
            assert(#CVPMPServer.links==1 and rope.owner==CVPEquipmentRuntime.container and body.md.CVPTether)
            storage.AddItem=add;assert(CVPMPServer.detachAll(player,car))
            assert(rope.owner==storage and not body.md.CVPTether)
        ''')

    def test_bulk_detach_leaves_other_vehicle_untouched(self):
        self.attach()
        self.s.execute('''
            local car2={};for k,v in pairs(car) do car2[k]=v end
            car2.md={};car2.getId=function() return 8 end
            assert(CVPMPServer.attach(player2,body2,car2,otherRope))
            local original=body2.md.CVPTether
            assert(CVPMPServer.detachAll(player,car))
            assert(#CVPMPServer.links==1 and body2.md.CVPTether==original and otherRope.owner==CVPEquipmentRuntime.container)
            assert(rope.owner==storage)
        ''')

    def test_lowered_capacity_counts_existing_high_slots(self):
        self.attach()
        self.s.execute('''
            body.md.CVPTether.slot=8
            assert(require('CVP_Equipment').updateBindings({{key=body.md.CVPTether.equipmentKey,body=body,metadata=body.md.CVPTether}}))
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1
            local ok,reason=CVPMPServer.attach(player2,body2,car,otherRope)
            assert(ok and body.md.CVPTether.slot==8)
            assert(CVPMPServer.detach(player2,body2))
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=2
            assert(CVPMPServer.attach(player2,body2,car,otherRope))
            assert(body2.md.CVPTether.slot==1)
        ''')

    def test_batched_vehicle_updates_keep_up_without_breaking_tether(self):
        self.attach()
        self.s.execute('''
            speed=40.9;local start=car.x;local maxStep=0
            for i=1,600 do
                -- 250 ms vehicle updates on a 60 Hz server, including a turn.
                if i%15==0 then car.x=start+i/60*speed/3.6;car.y=math.sin(i/60)*2 end
                local x,y=body.x,body.y;now=now+1000/60;CVPMPServer.tick()
                maxStep=math.max(maxStep,math.sqrt((body.x-x)^2+(body.y-y)^2))
                assert(#CVPMPServer.links==1 and worldCount(body)==1)
            end
            assert(maxStep<.7 and body.x>car.x-12)
            assert(rope.owner==CVPEquipmentRuntime.container)
        ''')

    def test_menu_explains_missing_gear_vehicle_and_seat(self):
        client=vm(False)
        client.execute('''
            storage:Remove(rope);storage:Remove(chain);menu(body)
            assert(#options>0)
            for _,o in ipairs(options) do assert(o.notAvailable and o.toolTip.description==getText('IGUI_CVP_NeedGear')) end
            car.x=100;menu(body)
            for _,o in ipairs(options) do assert(o.notAvailable and o.toolTip.description==getText('IGUI_CVP_ParkNearby')) end
            player.getVehicle=function() return car end;menu(body)
            for _,o in ipairs(options) do assert(o.notAvailable and o.toolTip.description==getText('IGUI_CVP_LeaveVehicle')) end
            assert(#clientPackets==0)
        ''')

    def test_bulk_menu_negotiates_server_capability(self):
        self.attach();packet=self.states()[0];client=vm(False)
        packet['args']['bulkDetach']=False;deliver(client,packet)
        client.execute('''
            rope.getDisplayName=function() return 'rope' end;chain.getDisplayName=function() return 'chain' end
            carMenu();local opt=assert(menuBranch(context,getText('IGUI_CVP_DetachAllMenu','1')));assert(opt.notAvailable)
            opt.run();assert(#clientPackets==0)
        ''')
        packet['args']['sequence']+=1;packet['args']['bulkDetach']=True;deliver(client,packet)
        client.execute('''
            CVPMPClient.tick();deferAction=true;carMenu();local opt=assert(menuBranch(context,getText('IGUI_CVP_DetachAllMenu','1')));assert(not opt.notAvailable);opt.run()
            assert(#clientPackets==0);queued:start();queued:perform()
            assert(#clientPackets==1 and clientPackets[1].name=='detach' and clientPackets[1].args.vehicle==7)
        ''')

    def test_vehicle_replication_jump_does_not_become_body_teleport(self):
        def measure(filtered):
            server=vm(True)
            if not filtered:
                server.execute("require('CVP_Rope').networkAnchor=function(r,x,y) return x,y end")
            server.execute('''
                assert(CVPMPServer.attach(player,body,car,rope))
                local oldx,oldy=body.x,body.y;car.x=12;speed=40.9
                now=now+33;CVPMPServer.tick()
                jump=math.sqrt((body.x-oldx)^2+(body.y-oldy)^2)
                assert(#CVPMPServer.links==1)
            ''')
            return server,server.globals().jump
        before,old=measure(False);after,new=measure(True)
        self.assertGreater(old,4)
        self.assertLess(new,.7)
        after.execute('''
            for i=1,180 do now=now+33;CVPMPServer.tick() end
            assert(#CVPMPServer.links==1 and body.x>5)
            local r=CVPMPServer.links[1]
            local ax,ay=require('CVP_Core').anchor(r)
            local fx,fy=require('CVP_Rope').feet(r)
            assert((ax-fx)^2+(ay-fy)^2<(r.length+.3)^2)
            player.x=body.x;player.y=body.y;speed=0
            assert(CVPMPServer.detach(player,body) and rope.owner==storage)
        ''')

    def test_context_menu_with_vehicle_set(self):
        client = vm(False)
        client.execute('''
            rope.getDisplayName=function() return 'rope' end
            chain.getDisplayName=function() return 'chain' end
            menu(body)
            assert(#options==1, 'one direct action with selected material')
            options[1].run()
            assert(#clientPackets==1 and clientPackets[1].name=='attach')
            assert(clientPackets[1].args.id==body.netID and clientPackets[1].args.vehicle==7)
            speed=5;menu(body)
            for _,o in ipairs(options) do assert(o.notAvailable) end
            body.md.CVPTether=require('CVP_Core').metadata(require('CVP_World').vehicleKey(car),rope,1,'feet',body);body.md.CVPTether.version=2;speed=0;menu(body)
            options[1].run()
            assert(clientPackets[2].name=='detach' and clientPackets[2].args.id==body.netID)
        ''')

    def test_player_corpse_loot_survives_tow_reload_and_detach(self):
        self.s.execute('''
            -- A dead player is an IsoDeadBody, not a live IsoPlayer.
            body.isZombie=function() return false end
            body.isPlayer=function() return false end
            savedContainer=body.inv
            bag=item('Base.Bag');bag.kind='InventoryContainer';bag.inv=container()
            bag.getInventory=function(s) return s.inv end
            keepsake=item('Base.Watch');keepsake.md.personal='unchanged';keepsake.w=.15
            bag.inv:AddItem(keepsake);body.inv:AddItem(bag)
            worn=item('Base.Jacket');body.inv:AddItem(worn)
            body.worn={jacket=worn};body.held=worn
            body.reanimateTime=42;body.ownerName='dead player'
            originals={};for i,v in ipairs(body.inv.rows) do originals[i]=v end
        ''')
        self.attach()
        self.s.execute('car.x=5;for i=1,20 do now=now+100;CVPMPServer.tick() end')
        self.s.execute((LEGACY/'CVP_MPServer.lua').read_text())
        self.s.execute('''
            CVPMPServer.discover();assert(#CVPMPServer.links==1)
            player.x=body:getX();player.y=body:getY()
            command('detach',player,{request=2,id=body.netID})
            assert(#CVPMPServer.links==0 and rope.owner==storage and worldCount(body)==1)
            assert(body.inv==savedContainer and #body.inv.rows==#originals)
            for i,v in ipairs(originals) do assert(body.inv.rows[i]==v and v.owner==savedContainer) end
            assert(bag.inv.rows[1]==keepsake and keepsake.owner==bag.inv)
            assert(keepsake.md.personal=='unchanged' and keepsake.w==.15)
            assert(body.worn.jacket==worn and body.held==worn)
            assert(body.reanimateTime==42 and body.ownerName=='dead player')
            command('detach',player,{request=3,id=body.netID})
            assert(#body.inv.rows==#originals and rope.owner==storage)
        ''')

    def test_player_menu_animal_allowed_live_and_fake_dead_rejected(self):
        client=vm(False)
        client.execute('''
            body.isZombie=function() return false end
            rope.getDisplayName=function() return 'rope' end
            chain.getDisplayName=function() return 'chain' end
            menu(body);assert(#options==1)
            options[1].run();assert(clientPackets[1].args.id==body.netID)
        ''')
        self.s.execute('''
            local W=require 'CVP_World'
            assert(not W.towable(player))
            body.isZombie=function() return false end
            body.isAnimal=function() return true end
            command('attach',player,{request=1,id=body.netID,vehicle=7,gear=rope.id})
            assert(#CVPMPServer.links==1)
            command('detach',player,{request=3,id=body.netID})
            body.isAnimal=function() return false end;body.isFakeDead=function() return true end
            command('attach',player,{request=2,id=body.netID,vehicle=7,gear=rope.id})
            assert(#CVPMPServer.links==0 and rope.owner==storage)
        ''')

    def test_player_detach_inventory_failure_keeps_body_and_tether(self):
        self.s.execute('body.isZombie=function() return false end')
        self.attach()
        self.s.execute('''
            local add=storage.AddItem;storage.AddItem=function() end
            command('detach',player,{request=2,id=body.netID})
            assert(#CVPMPServer.links==1 and rope.owner==CVPEquipmentRuntime.container and body.md.CVPTether)
            storage.AddItem=add
            command('detach',player,{request=3,id=body.netID})
            assert(#CVPMPServer.links==0 and rope.owner==storage and worldCount(body)==1)
        ''')

    def attach(self):
        self.s.execute("command('attach',player,{request=1,id=body.netID,vehicle=7,gear=rope.id})")
        self.s.execute("assert(#CVPMPServer.links==1 and rope.owner==CVPEquipmentRuntime.container)")

    def states(self):
        self.s.execute('now=now+100;CVPMPServer.tick()')
        return [copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='state']

    def test_two_players_compete_replay_and_detach_original(self):
        self.attach()
        self.s.execute('''
            command('attach',player2,{request=1,id=body.netID,vehicle=7,gear=otherRope.id})
            assert(#CVPMPServer.links==1 and otherRope.owner==player2.inv and #containerPackets==1)
            command('detach',player,{request=1,id=body.netID}) -- replay of consumed request
            assert(#CVPMPServer.links==1)
            command('detach',player2,{request=2,id=body.netID})
            assert(#CVPMPServer.links==0 and rope.owner==player2.inv and not body.md.CVPTether)
            assert(worldCount(body)==1 and #containerPackets==2)
        ''')

    def test_server_rejects_foreign_item_speed_walls_distance_and_invalid_numbers(self):
        self.s.execute('''
            command('attach',player,{request=1,id=body.netID,vehicle=7,gear=otherRope.id})
            speed=5;command('attach',player,{request=2,id=body.netID,vehicle=7,gear=rope.id});speed=0
            unreachable=true;command('attach',player,{request=3,id=body.netID,vehicle=7,gear=rope.id});unreachable=false
            player.x=50;command('attach',player,{request=4,id=body.netID,vehicle=7,gear=rope.id});player.x=0
            command('attach',player,{request=0/0,id=body.netID,vehicle=7,gear=rope.id})
            command('attach',player,{request=5,id=body.netID,vehicle=0/0,gear=rope.id})
            assert(#CVPMPServer.links==0 and rope.owner==storage and #containerPackets==0)
        ''')

    def test_refused_inventory_transfer_rolls_back(self):
        self.s.execute('''
            local holder=ItemContainer.new();holder.AddItem=function() end
            ItemContainer.new=function() return holder end
            command('attach',player,{request=1,id=body.netID,vehicle=7,gear=rope.id})
            assert(rope.owner==storage and not body.md.CVPTether and #CVPMPServer.links==0 and #containerPackets==0)
        ''')

    def test_disconnect_restart_and_unloaded_vehicle(self):
        self.attach()
        self.s.execute('players={player2};player.dead=true;now=now+100;CVPMPServer.tick();assert(#CVPMPServer.links==1)')
        self.s.execute((LEGACY/'CVP_MPServer.lua').read_text())
        self.s.execute('''
            CVPMPServer.discover();CVPMPServer.discover()
            assert(#CVPMPServer.links==1 and rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
            savedSquare=car.getSquare;car.getSquare=function() return nil end
            now=now+100;CVPMPServer.tick();assert(#CVPMPServer.links==0 and body.md.CVPTether)
            car.getSquare=savedSquare;CVPMPServer.discover();assert(#CVPMPServer.links==1)
        ''')

    def test_dormant_detach_waits_for_vehicle_and_preserves_root_or_middle_tail(self):
        from test_trains import train
        for index in (1,2):
            with self.subTest(detach_index=index):
                lua=train(True,3)
                lua.globals().detachIndex=index
                lua.execute('''
                    local savedSquare=car.getSquare
                    local originals={}
                    for i,b in ipairs(trainBodies) do originals[i]=b.md.CVPTether end
                    car.getSquare=function() return nil end;stepTrain(.1)
                    assert(#links()==0)
                    local ok,reason=CVPMPServer.detach(player,trainBodies[detachIndex])
                    assert(not ok and reason=='IGUI_CVP_VehicleUnavailable')
                    for i,b in ipairs(trainBodies) do
                        assert(b.md.CVPTether==originals[i] and trainRecords[i].gear.owner==CVPEquipmentRuntime.container)
                        assert(car.md.CVPConnections[originals[i].connection.id]~=nil and worldCount(b)==1)
                    end
                    car.getSquare=savedSquare;restore();restore()
                    assert(#links()==3)
                    assert(CVPMPServer.detach(player,trainBodies[detachIndex]))
                    assert(#links()==detachIndex-1)
                    for i,b in ipairs(trainBodies) do
                        assert(worldCount(b)==1)
                        if i<detachIndex then assert(b.md.CVPTether and trainRecords[i].gear.owner==CVPEquipmentRuntime.container)
                        else assert(not b.md.CVPTether and trainRecords[i].gear.owner==storage) end
                    end
                ''')

    def test_body_detach_requires_stationary_root_vehicle_before_transfer(self):
        self.attach()
        self.s.execute('''
            local root=CVPMPServer.links[1]
            assert(CVPMPServer.attach(player,body2,car,chain,'feet','body',body,root.connection.id))
            local rootData,childData=body.md.CVPTether,body2.md.CVPTether
            local sent=#containerPackets;speed=5
            for _,b in ipairs({body,body2}) do
                local ok,reason=CVPMPServer.detach(player,b)
                assert(not ok and reason=='IGUI_CVP_StopVehicle')
            end
            assert(#CVPMPServer.links==2 and body.md.CVPTether==rootData and body2.md.CVPTether==childData)
            assert(rope.owner==CVPEquipmentRuntime.container and chain.owner==CVPEquipmentRuntime.container and #containerPackets==sent)
            speed=0;command('detach',player,{request=2,id=body.netID})
            assert(packets[#packets].args.ok and #CVPMPServer.links==0)
            assert(rope.owner==storage and chain.owner==storage and worldCount(body)==1 and worldCount(body2)==1)
        ''')

    def test_two_clients_follow_server_and_ignore_reordered_state(self):
        self.attach()
        clients = [vm(False), vm(False)]
        first = self.states()[0]
        for client in clients:
            deliver(client, first)
            client.execute('now=now+100;CVPMPClient.tick();assert(worldCount(body)==1 and tracked[body] and rendered>0)')
        self.s.execute('for i=1,30 do car.x=3+i*.2;now=now+100;CVPMPServer.tick() end')
        latest = self.states()[-1]
        for client in clients:
            deliver(client, latest)
            deliver(client, first)
            client.execute('for i=1,20 do now=now+20;CVPMPClient.tick() end;assert(worldCount(body)==1)')
            self.assertEqual(client.globals().CVPMPClient.sequence, latest['args']['sequence'])
            self.assertAlmostEqual(client.globals().body.x,self.s.globals().body.x,delta=.02)

    def test_late_join_bootstrap_is_idempotent_and_stale_chunks_do_not_respawn(self):
        self.attach()
        client = vm(False)
        client.execute('sq:removeCorpse(body)')
        deliver(client, self.states()[0])
        client.execute('now=now+100;CVPMPClient.tick();assert(#clientPackets==1)')
        self.s.execute("command('body',player,{id=body.netID})")
        boot = [copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='body'][0]
        deliver(client, boot);deliver(client, boot)
        client.execute('assert(replicas==1 and worldCount(body)==1)')
        self.s.execute("command('detach',player,{request=2,id=body.netID})")
        deliver(client, self.states()[-1]);deliver(client, boot)
        client.execute('assert(not next(CVPMPClient.links) and replicas==1 and not body.md.CVPTether)')

    def test_bootstrap_from_previous_connection_cannot_restore_reattached_body(self):
        self.attach()
        first = self.states()[0]
        self.s.execute("command('body',player,{id=body.netID})")
        old = [copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='body'][-1]
        self.s.execute('''
            command('detach',player,{request=2,id=body.netID})
            command('attach',player,{request=3,id=body.netID,vehicle=7,gear=chain.id})
            assert(#CVPMPServer.links==1 and chain.owner==CVPEquipmentRuntime.container and rope.owner==storage)
        ''')
        current = self.states()[-1]
        self.s.execute("now=now+1100;command('body',player,{id=body.netID})")
        fresh = [copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='body'][-1]
        self.assertNotEqual(first['args']['rows'][1]['connection']['id'],
                            current['args']['rows'][1]['connection']['id'])
        for client in (vm(False),vm(False)):
            client.execute('''
                sq:removeCorpse(body)
                local receive=CVPNetwork.receive
                CVPNetwork.receive=function(...)
                    decoded=(decoded or 0)+1;return receive(...)
                end
            ''')
            deliver(client,first)
            deliver(client,current)
            # Native payload includes the full corpse and inventory. Even if the
            # network body ID is unchanged, the old attachment snapshot is stale.
            deliver(client,old)
            client.execute('assert(not decoded and not body.world and not next(CVPMPClient.parts))')
            deliver(client,fresh)
            client.execute('now=now+100;CVPMPClient.tick();assert(decoded==1 and replicas==1 and worldCount(body)==1)')
            self.assertEqual(client.eval('body.md.CVPTether.connection.id'),
                             current['args']['rows'][1]['connection']['id'])

    def test_restart_rejects_old_epoch_state_and_result_on_two_clients(self):
        clients = [vm(False),vm(False)]
        first = self.states()[0]
        for client in clients:
            deliver(client,first)
            client.execute('''
                callbackResults={}
                CVPMPClient.requestAction('attach',player,body,car,rope,nil,function(ok,id,reason)
                    callbackResults[#callbackResults+1]={ok=ok,id=id,reason=reason}
                end)
            ''')
        self.attach()
        old_result = [copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='result'][-1]
        old_state = self.states()[-1]
        for client in clients:
            deliver(client,old_state)
            client.execute('now=now+100;CVPMPClient.tick();assert(body.md.CVPTether)')
        self.s.execute((LEGACY/'CVP_MPServer.lua').read_text(encoding='utf-8'))
        self.s.execute('''
            CVPMPServer.discover()
            command('detach',player,{request=1,id=body.netID})
            assert(#CVPMPServer.links==0 and rope.owner==storage)
        ''')
        restarted = self.states()[-1]
        self.assertNotEqual(old_state['args']['epoch'], restarted['args']['epoch'])
        for client in clients:
            deliver(client,restarted)
            client.execute('''
                assert(#callbackResults==1 and callbackResults[1].ok==false)
                assert(callbackResults[1].reason=='IGUI_CVP_QueueStopped' and not next(CVPMPClient.pending))
                assert(not next(CVPMPClient.links) and not body.md.CVPTether)
            ''')
            deliver(client,old_result)
            deliver(client,old_state)
            client.execute('''
                now=now+100;CVPMPClient.tick()
                assert(#callbackResults==1 and not next(CVPMPClient.links))
                assert(not body.md.CVPTether and worldCount(body)==1)
            ''')
            self.assertEqual(client.eval('CVPMPClient.epoch'),restarted['args']['epoch'])
            self.assertEqual(client.eval('CVPMPClient.sequence'),restarted['args']['sequence'])

    def test_first_action_waits_for_handshake_without_sending_or_consuming_request(self):
        client=vm(False,handshake=False)
        client.execute('''
            results={}
            function after(ok,id,reason) results[#results+1]={ok=ok,id=id,reason=reason} end
            CVPMPClient.requestAction('attach',player,body,car,rope,nil,after)
            assert(#clientPackets==0 and CVPMPClient.request==0 and not next(CVPMPClient.pending))
            assert(#results==1 and results[1].ok==false and results[1].reason=='IGUI_CVP_SyncWaiting')
            assert(rope.owner==storage and not body.md.CVPTether)
        ''')
        deliver(client,self.states()[0])
        client.execute("CVPMPClient.requestAction('attach',player,body,car,rope,nil,after)")
        request=copy_packet(client.globals().clientPackets[1])
        self.s.globals().requestArgs=self.s.table_from(request['args'],recursive=True)
        self.s.execute("command('attach',player,requestArgs)")
        result=[copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='result'][-1]
        deliver(client,result)
        client.execute('assert(#results==2 and results[2].ok==true and not next(CVPMPClient.pending))')
        self.s.execute('assert(#CVPMPServer.links==1 and rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)')

    def test_reconnect_rejects_old_ack_with_reused_request_number(self):
        self.attach()
        old_result=[copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='result'][-1]
        self.s.execute((LEGACY/'CVP_MPServer.lua').read_text(encoding='utf-8'))
        state=self.states()[-1]
        clients=[vm(False,handshake=False),vm(False,handshake=False)]
        for client in clients:
            deliver(client,state)
            client.execute('''
                results={}
                CVPMPClient.requestAction('detach',player,body,nil,nil,nil,function(ok)
                    results[#results+1]=ok
                end)
                assert(CVPMPClient.request==1)
            ''')
            deliver(client,old_result)
            client.execute('assert(#results==0 and CVPMPClient.pending[1] and not CVPMPClient.lastResult)')
        self.s.execute("command('detach',player,{request=1,id=body.netID})")
        fresh_result=[copy_packet(p) for _,p in self.s.globals().packets.items() if p['name']=='result'][-1]
        for client in clients:
            deliver(client,fresh_result)
            client.execute('assert(#results==1 and results[1]==true and not next(CVPMPClient.pending))')

    def test_epoch_change_clears_old_pending_before_callbacks_enqueue_again(self):
        client=vm(False)
        deliver(client,self.states()[0])
        client.execute('''
            stopped=0;finished=0
            CVPMPClient.requestAction('attach',player,body,car,rope,nil,function(ok)
                assert(not ok);stopped=stopped+1
                CVPMPClient.requestAction('attach',player,body2,car,chain,nil,function() finished=finished+1 end)
            end)
        ''')
        self.s.execute((LEGACY/'CVP_MPServer.lua').read_text(encoding='utf-8'))
        state=self.states()[-1]
        deliver(client,state)
        client.execute('''
            assert(stopped==1 and finished==0 and not CVPMPClient.pending[1])
            assert(CVPMPClient.pending[2] and CVPMPClient.pending[2].epoch==CVPMPClient.epoch)
        ''')

    def test_epoch_change_clears_only_own_metadata_even_after_timeout(self):
        self.attach()
        active=self.states()[0]
        self.s.execute("assert(CVPMPServer.detach(player,body));now=now+100")
        # Restart drops terminal history before either observer receives it.
        self.s.execute((LEGACY/'CVP_MPServer.lua').read_text(encoding='utf-8'))
        empty=self.states()[-1]
        self.assertFalse(empty['args']['rows'])
        for timeout in (False,True):
            with self.subTest(timeout=timeout):
                own,native=vm(False,handshake=False),vm(False,handshake=False)
                for client in (own,native):
                    deliver(client,active)
                    client.execute('now=now+100;CVPMPClient.tick();mirror=body.md.CVPTether;assert(mirror)')
                native.execute('''
                    nativeData={};for k,v in pairs(mirror) do nativeData[k]=v end
                    body.md.CVPTether=nativeData
                ''')
                if timeout:
                    for client in (own,native):
                        client.execute('now=now+4000;CVPMPClient.tick();assert(not next(CVPMPClient.links))')
                for client in (own,native):
                    deliver(client,empty)
                    client.execute('assert(not next(CVPMPClient.links) and worldCount(body)==1 and rope.owner==storage)')
                own.execute('''
                    assert(not body.md.CVPTether)
                    assert(CVPMPClient.queueAction('attach',player,body,car,rope))
                    assert(clientPackets[#clientPackets].name=='attach')
                ''')
                native.execute("assert(body.md.CVPTether==nativeData and require('CVP_World').data(body)==nativeData)")

    def test_detach_aligns_two_clients_despite_different_visual_positions(self):
        self.attach()
        clients = [vm(False), vm(False)]
        active = self.states()[0]
        for index, client in enumerate(clients):
            deliver(client, active)
            client.execute(f'body.x={index+4};body.y={index+2};body.angle={index+1}')
        self.s.execute("command('detach',player,{request=2,id=body.netID})")
        terminal = self.states()[-1]
        for client in clients:
            deliver(client, terminal)
            deliver(client, active)  # A delayed pre-detach packet must not restore towing.
            client.execute('now=now+100;CVPMPClient.tick();assert(not next(CVPMPClient.links) and not body.md.CVPTether)')
            for coordinate in ('x', 'y', 'z'):
                self.assertAlmostEqual(client.globals().body[coordinate], self.s.globals().body[coordinate])
            self.assertAlmostEqual(client.eval('body:getAngle()'), self.s.eval('body:getAngle()'))

    def test_chain_detach_clears_two_clients_and_allows_reattach_after_timeout(self):
        self.attach()
        self.s.execute('''
            local root=CVPMPServer.links[1]
            assert(CVPMPServer.attach(player,body2,car,chain,'feet','body',body,root.connection.id))
        ''')
        clients=[vm(False),vm(False)]
        active=self.states()[0]
        for client in clients:
            client.execute('CVPRopeScene.updateBody=function() end')
            deliver(client,active)
            client.execute('''
                now=now+100;CVPMPClient.tick()
                assert(body.md.CVPTether and body2.md.CVPTether)
            ''')
        # Timeout removes runtime tracking; the later terminal must also clear
        # a child connection's saved marker so it can be attached again.
        clients[1].execute('now=now+4000;CVPMPClient.tick();assert(not next(CVPMPClient.links))')
        self.s.execute("command('detach',player,{request=2,id=body.netID})")
        terminal=self.states()[-1]
        for client in clients:
            deliver(client,terminal)
            client.execute('''
                assert(not next(CVPMPClient.links))
                assert(not body.md.CVPTether and not body2.md.CVPTether)
                assert(worldCount(body)==1 and worldCount(body2)==1)
                assert(CVPMPClient.queueAction('attach',player,body2,car,chain))
                assert(clientPackets[#clientPackets].name=='attach')
            ''')

    def test_physics_authority_and_stale_state_timeout(self):
        self.attach()
        packet=self.states()[0]
        packet['args']['rows'][1]['taut']=True
        packet['args']['rows'][1]['loadMass']=75
        client=vm(False);deliver(client,packet)
        client.execute('''
            physicsOwner=false;now=now+100;CVPMPClient.tick();assert(#impulses==0)
            physicsOwner=true;now=now+100;CVPMPClient.tick();assert(#impulses==1)
            now=now+4000;CVPMPClient.tick();assert(not next(CVPMPClient.links) and not tracked[body] and #impulses==1)
        ''')

    def test_protocol_rejects_invalid_and_oversized_chunks(self):
        self.attach();client=vm(False);packet=self.states()[0]
        packet['args']['rows'][1]['x']=float('nan');deliver(client,packet)
        client.execute('assert(not next(CVPMPClient.links))')
        valid=self.states()[-1];deliver(client,valid)
        client.execute('''
            CVPMPClient.receive('body',{protocol=3,epoch=CVPMPClient.epoch,id=body.netID,transfer='x',part=1,count=10000,data='x'})
            assert(not next(CVPMPClient.parts))
        ''')

    def large_state(self):
        from copy import deepcopy
        self.attach()
        packet=self.states()[0]
        original=packet['args']['rows'][1]
        rows={}
        for index in range(1,322):
            row=deepcopy(original)
            row['id']=str(10000+index)
            row['connection']['id']='connection-'+str(index)
            row['connection']['b']['key']='body-'+str(index)
            row['gearID']=1000+index
            row['slot']=index
            rows[index]=row
        packet['args']['rows']=rows
        return packet

    def test_state_accepts_321_independent_connections_without_global_limit(self):
        packet=self.large_state()
        for client in (vm(False),vm(False)):
            deliver(client,packet)
            client.execute('''
                local n=0
                for _,r in pairs(CVPMPClient.links) do
                    assert(require('CVP_Protocol').row(r.target));n=n+1
                end
                assert(n==321)
                assert(CVPMPClient.links['10321'].target.connection.id=='connection-321')
            ''')
            self.assertEqual(client.eval('CVPMPClient.sequence'),packet['args']['sequence'])

    def test_state_validates_malformed_row_after_320_before_applying_snapshot(self):
        packet=self.large_state()
        client=vm(False)
        # A valid previous snapshot must survive rejection of any later row.
        initial={'name':'state','args':dict(packet['args'],rows={1:packet['args']['rows'][1]})}
        deliver(client,initial)
        client.execute("previous=CVPMPClient.links['10001'];previousSequence=CVPMPClient.sequence")
        packet['args']['sequence']+=1
        packet['args']['rows'][321]['x']=float('nan')
        deliver(client,packet)
        client.execute('''
            assert(CVPMPClient.sequence==previousSequence and CVPMPClient.links['10001']==previous)
            local n=0;for _ in pairs(CVPMPClient.links) do n=n+1 end;assert(n==1)
        ''')


if __name__=='__main__':
    unittest.main()
