"""Current handlers in separate Lua server/client VMs; packets cross as plain data."""
from pathlib import Path
import unittest
from lua_fixture import create_current_fixture
from lua_fixture import copy_packet

ROOT = Path('CorpseProxyLab/42/media/lua')


def vm(server=False, who='owner', saved=None):
    l = create_current_fixture()
    l.globals().serverMode = server
    l.globals().localName = who
    l.execute('''
        function isServer() return serverMode end
        function isClient() return not serverMode end
        function getNumActivePlayers() return 1 end
        player.getUsername=function() return 'owner' end;player.getPlayerNum=function() return 0 end
        player2=actor('IsoPlayer',0,0);player2.inv=container();player2.inv.parent=player2;player2.md={}
        player2.getInventory=function(s) return s.inv end;player2.getModData=function(s) return s.md end
        player2.getUsername=function() return 'friend' end
        for _,method in ipairs({'getVehicle','isDead','getSquare','getPrimaryHandItem','getSecondaryHandItem','getPlayerNum',
            'faceLocationF','faceThisObject','shouldBeTurning','reportEvent','Say'}) do player2[method]=player[method] end
        otherRope=item('Base.Rope');player2.inv:AddItem(otherRope)
        players={player,player2};localPlayer=localName=='friend' and player2 or player
        function getPlayer() return localPlayer end;function getSpecificPlayer() return localPlayer end
        function getOnlinePlayers() return list(players) end
        car.getSqlId=function() return serverMode and 71 or -1 end;car.getId=function() return 17 end
        car.isLocalPhysicSim=function() return physicsOwner==true end
        car.getNetPlayerId=function() return 1 end
        player.getOnlineID=function() return 1 end;player2.getOnlineID=function() return 2 end
        car.getDriver=function() return player end
        player.isLocalPlayer=function() return true end
        function getVehicleById(id) if id==17 then return car end end
        body.md.CVPBodyKey='A';body2.md.CVPBodyKey='B'
        body.netID='9007199254740993';body2.netID='9007199254740994'
        for _,b in ipairs(bodies) do b.getAngle=function(s) return s.angle or 0 end end
        World=require 'CVP_World';G=require 'CVP_LinkGraph'
        World.move(body2,-3,0,0,gridSquare(-3,0,0))
        CVPNetwork={id=function(b) return b.netID end,bodies=function() return list(bodies) end,
            find=function(id) for _,b in ipairs(bodies) do if b.netID==id and b.world then return b end end end,
            encode=function(b) return 'encoded:'..b.netID end,
            receive=function(id,payload)
                assert(payload=='encoded:'..id)
                for _,b in ipairs(bodies) do if b.netID==id then
                    if not b.world then b.sq:addCorpse(b);replicas=(replicas or 0)+1 end;return b
                end end
            end}
        CVPSkeletonNative={version=function() return '2-graph-clocks' end,sync=function() end,retire=function() return false end}
        drawn={};tracked={}
        CVPFreeRopeScene={version=function() return '1-free-endpoints' end,update=function(id,points) drawn[id]=equipmentCopy(points) end,
            vehicle=function() end,remove=function(id) drawn[id]=nil end}
        installNativeRopeScene(CVPFreeRopeScene)
        CVPViewpoint={track=function(b) tracked[b]=true end,untrack=function(b) tracked[b]=nil end,clear=function() tracked={} end}
        packets={};clientPackets={};containerPackets={}
        function sendServerCommand(p,m,n,a) packets[#packets+1]={who=p:getUsername(),name=n,args=equipmentCopy(a)} end
        function sendClientCommand(p,m,n,a) clientPackets[#clientPackets+1]={who=p:getUsername(),name=n,args=equipmentCopy(a)} end
        function sendRemoveItemFromContainer(c,i)
            local p=c:getCharacter();if p then containerPackets[#containerPackets+1]={who=p:getUsername(),kind='remove',id=i:getID()} end
        end
        function sendAddItemToContainer(c,i)
            local p=c:getCharacter();if p then containerPackets[#containerPackets+1]={who=p:getUsername(),kind='add',payload=equipmentEncode(i)} end
        end
        local read=CVPEquipmentPersistence.read
        CVPEquipmentPersistence.read=function() assert(serverMode,'client opened authoritative equipment ledger');return read() end
        A={kind='body',key='A',native=body.netID,point='feet'};B={kind='body',key='B',native=body2.netID,point='feet'}
        C={kind='vehicle',key='sql:71',native=17,point='hitch'}
        deferAction=true;deferPath=true
        function finishStage()
            local a=assert(queued);a:start()
            if a.complete and not isClient() then a:complete() end
            a:perform()
        end
        function choose(key,...)
            local label=getText(key,...)
            for _,opt in ipairs(options) do if opt.label==label then assert(not opt.notAvailable,opt.toolTip and opt.toolTip.description);opt.run();return end end
            error('missing menu '..label)
        end
    ''')
    if saved is not None:
        l.globals().saved=l.table_from(saved,recursive=True)
        l.execute('loadEquipment(saved);storage:Remove(rope)')
    path = ROOT / ('server/CVP_MPServer.lua' if server else 'client/CVP_MPClient.lua')
    l.execute(path.read_text(encoding='utf-8-sig'))
    if server:
        l.execute('''
            now=100;CVPMPServer.tick();R=CVPMPServer.authority;S=R.service;H=R.host
            function beside(e,p) local pos=assert(H.sample(e));p=p or player;p.x=pos.x;p.y=pos.y end
            function link(a,b,item,p)
                p=p or player;beside(a,p);local token=assert(R:prepare(p,a,item:getID()))
                beside(b,p);local ok,id=R:create(p,token,b);assert(ok,id);return id
            end
            function publish() CVPMPServer.sequence=CVPMPServer.sequence+1
                local snapshot=CVPMPServer.capture();for _,p in ipairs(players) do CVPMPServer.publish(p,snapshot) end
            end
        ''')
    else:
        l.execute('now=100;callbacks.OnGameStart()')
    return l


def take(l, name):
    rows = [copy_packet(v) for _, v in l.globals()[name].items()]
    l.globals()[name] = l.table()
    return rows


class Network:
    def __init__(self):
        self.server = vm(True)
        self.clients = {name: vm(False, name) for name in ('owner', 'friend')}
        self.pump()

    def send(self, packet):
        s = self.server
        p = s.globals().player if packet['who'] == 'owner' else s.globals().player2
        s.globals().CVPMPServer.command('CVP', packet['name'], p, s.table_from(packet['args'], recursive=True))

    def receive(self, packet):
        c = self.clients[packet['who']]
        c.globals().CVPMPClient.receive(packet['name'], c.table_from(packet['args'], recursive=True))

    def pump(self, inventories=True):
        for _ in range(50):
            work = False
            for name, c in self.clients.items():
                requests = take(c, 'clientPackets')
                for request in requests:
                    work = True
                    p = self.server.globals().player if name == 'owner' else self.server.globals().player2
                    local = c.globals().localPlayer
                    p.x, p.y, p.z = local.x, local.y, local.z
                    self.send(request)
            for packet in take(self.server, 'packets'):
                work = True; self.receive(packet)
            if inventories:
                for packet in take(self.server, 'containerPackets'):
                    c = self.clients[packet['who']]; c.globals().nativePacket = c.table_from(packet)
                    c.execute('''
                        local inv=localPlayer:getInventory()
                        if nativePacket.kind=='remove' then local item=inv:getItemWithIDRecursiv(nativePacket.id);if item then item:getContainer():Remove(item) end
                        else local item=equipmentDecode(nativePacket.payload);inv:AddItem(item) end
                    ''')
            if not work:
                return
        raise AssertionError('packet exchange did not settle')

    def publish(self):
        self.server.execute('publish()'); self.pump()

    def tick(self, movement=0):
        self.server.globals().motion = movement
        self.server.execute('now=now+100;car.x=car.x+motion;CVPMPServer.tick()')
        for c in self.clients.values():
            c.globals().car.x = self.server.globals().car.x
            c.globals().car.y = self.server.globals().car.y
            c.execute('now=now+100;CVPMPClient.tick()')
        self.pump()

    def finish(self, who='owner'):
        c = self.clients[who]
        for _ in range(100):
            job = c.globals().CVPMPClient.actions.jobs[c.globals().localPlayer]
            if job.finished:
                return job
            if not job.waiting:
                c.execute('finishStage()')
            self.server.execute('now=now+1000')
            c.execute('now=now+1000')
            self.pump()
        raise AssertionError('action queue did not finish')


class LinkMultiplayerTests(unittest.TestCase):
    def test_tracking_only_on_first_success_and_after_failed_placement(self):
        n=Network();n.server.execute('root=link(C,A,rope)');n.publish()
        c=n.clients['owner'];c.execute('''
            trackCalls=0
            CVPViewpoint.track=function(b) tracked[b]=true;trackCalls=trackCalls+1 end
            CVPMPClient.tick();CVPMPClient.tick()
            assert(trackCalls==1 and tracked[body])
            local grapple=body.isBeingGrappled
            body.isBeingGrappled=function() return true end
            CVPMPClient.tick();assert(not tracked[body])
            body.isBeingGrappled=grapple
            CVPMPClient.tick();CVPMPClient.tick()
            assert(trackCalls==2 and tracked[body])
        ''')

    def test_empty_client_skips_player_sampling_but_keeps_reconnect(self):
        n=Network();c=n.clients['owner']
        c.execute('''
            local original=getOnlinePlayers;playerReads=0
            getOnlinePlayers=function() playerReads=playerReads+1;return original() end
            for i=1,100 do CVPMPClient.tick() end
            assert(playerReads==0)
            now=now+4000;CVPMPClient.tick()
            assert(#clientPackets>0 and playerReads==0)
        ''')
        n.pump()
        n.server.execute('link(C,A,rope);publish()')
        n.pump()
        c.execute('CVPMPClient.tick();assert(playerReads>0)')

    def test_final_pose_retries_unavailable_body_but_respects_later_moves(self):
        for moved in (False,True):
            with self.subTest(moved=moved):
                n=Network();s=n.server;c=n.clients['owner']
                s.execute('root=link(C,A,rope)');n.publish()
                for _ in range(12):n.tick(.1)
                c.execute('originalSquare=body.getSquare;body.getSquare=function() return nil end')
                s.execute("assert(S:unloadBody('A',{x=body.x,y=body.y,z=0}))")
                n.publish()
                c.execute("assert(type(CVPMPClient.finals.A)=='table');body.getSquare=originalSquare")
                if moved:c.execute('body.x=body.x+1')
                expected=c.eval('body.x') if moved else s.eval('body.x')
                c.execute('scans=0;local discover=CVPMPClient.host.discover;CVPMPClient.host.discover=function() scans=scans+1;return discover() end')
                n.publish();n.publish()
                self.assertEqual(c.eval('scans'),0, 'repeated final pose triggered full discovery')
                self.assertAlmostEqual(c.eval('body.x'),expected,places=9)
                c.execute("assert(type(CVPMPClient.finals.A)=='string' and not CVPMPClient.rows.A)")

    def test_lost_request_or_reply_retries_same_id_and_returns_item_once(self):
        for lost in ('command','result','all_results'):
            with self.subTest(lost=lost):
                n=Network();s=n.server;c=n.clients['owner']
                s.execute('root=link(C,A,rope);calls=0;local request=R.request;R.request=function(...) calls=calls+1;return request(...) end')
                n.publish()
                c.globals().player.x=s.eval('H.sample(S.graph.links[root].a).x')
                c.globals().player.y=s.eval('H.sample(S.graph.links[root].a).y')
                original=n.send if lost=='command' else n.receive
                dropped=[]
                def drop_once(packet):
                    if packet['name']==('result' if lost=='all_results' else lost) and (not dropped or lost=='all_results'):
                        dropped.append(packet);return
                    original(packet)
                if lost=='command':n.send=drop_once
                else:n.receive=drop_once
                c.execute("""
                    replies=0;local id,row=next(CVPMPClient.graph.links)
                    CVPMPClient.api.request(player,'command',{id=id,revision=row.revision,side='a',op='remove'},
                        function(ok,result,why) replies=replies+1;success=ok;reason=why end)
                """)
                n.pump()
                for _ in range(120 if lost=='all_results' else 35):n.tick()
                c.execute('assert(replies==1 and CVPMPClient.request==1 and not next(CVPMPClient.pending))')
                if lost=='all_results':c.execute("assert(not success and reason=='IGUI_CVP_ResultUnknown')")
                else:c.execute('assert(success)')
                s.execute('assert(calls==1 and not next(S.graph.links) and rope:getContainer()==storage and storage:getItems():size()==2)')
                self.assertEqual(len(dropped),4 if lost=='all_results' else 1)

    def test_remote_motion_keeps_only_heartbeat_and_entering_range_sends_state(self):
        n=Network();s=n.server;s.execute('link(C,A,rope);player2.x=1000');n.publish()
        received=[];original=n.receive
        def capture(packet):
            if packet['who']=='friend' and packet['name'] in ('state','motion'):received.append(packet)
            original(packet)
        n.receive=capture
        for _ in range(5):n.tick(.1)
        self.assertEqual(len(received),0)
        for _ in range(6):n.tick(.1)
        self.assertEqual(len(received),1)
        s.execute('player2.x=0');n.tick(.1)
        n.clients['friend'].execute('assert(next(CVPMPClient.graph.links))')

    def test_fresh_snapshot_retries_missing_body_before_lookup_deadline(self):
        for wrong_key in (False, True):
            with self.subTest(wrong_key=wrong_key):
                n=Network();s=n.server;c=n.clients['friend']
                s.execute('link(C,A,rope);publish()')
                packets=take(s,'packets')
                for packet in packets:n.receive(packet)
                c.execute("""
                    local row=CVPMPClient.rows.A
                    savedSquare=body.sq;body.sq:removeCorpse(body)
                    now=now+10;CVPMPClient.tick();deadline=row.nextLookup
                    assert(row.lookupMissing)
                    now=now+50;CVPMPClient.tick()
                    assert(row.nextLookup==deadline,'empty ticks repeated the failed lookup')
                    savedSquare:addCorpse(body)
                """)
                for packet in packets:n.receive(packet)
                c.execute('assert(CVPMPClient.rows.A.lookupMissing and now<deadline)')
                if wrong_key:c.execute("body.md.CVPBodyKey='unrelated'")
                s.execute('publish()')
                for packet in take(s,'packets'):n.receive(packet)
                if wrong_key:
                    c.execute("assert(not CVPMPClient.rows.A.body and body.md.CVPBodyKey=='unrelated');body.md.CVPBodyKey='A'")
                    s.execute('publish()')
                    for packet in take(s,'packets'):n.receive(packet)
                c.execute("""
                    assert(now<deadline and CVPMPClient.rows.A.body==body)
                    assert(not CVPMPClient.rows.A.lookupMissing)
                    assert(worldCount(body)==1 and body.inv:getItems():size()==1)
                    assert(body.inv:getItems():get(0):getFullType()=='Base.Watch')
                """)

    def test_missing_first_body_does_not_starve_other_bootstrap_requests(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('link(C,A,rope);link(A,B,chain)');n.publish()
        c.execute('body.sq:removeCorpse(body);body2.sq:removeCorpse(body2);now=now+100;CVPMPClient.tick()')
        first=next(p for p in take(c,'clientPackets') if p['name']=='body')
        # The first transfer never arrives. The next slot must serve the other body.
        c.execute('now=now+1100;CVPMPClient.tick()')
        second=next(p for p in take(c,'clientPackets') if p['name']=='body')
        self.assertNotEqual(first['args']['key'],second['args']['key'])
        s.execute('now=now+1100');n.send(second)
        for packet in take(s,'packets'):n.receive(packet)
        c.execute('assert(replicas==1)')

    def test_inconsistent_body_membership_and_vehicle_load_reject_entire_snapshot(self):
        for corrupt in ('membership','load'):
            with self.subTest(corrupt=corrupt):
                n=Network();s=n.server;c=n.clients['owner'];s.execute('link(C,A,rope)');n.publish()
                before=copy_packet(c.globals().CVPMPClient.graph)
                s.execute('publish()');page=next(p for p in take(s,'packets') if p['who']=='owner' and p['name']=='state')
                if corrupt=='membership':page['args']['bodies'][1]['connections'][1]='unrelated-link'
                else:page['args']['loads']['missing-vehicle']={'vehicle':17,'mass':999}
                n.receive(page)
                self.assertEqual(before,copy_packet(c.globals().CVPMPClient.graph))
                self.assertLess(c.globals().CVPMPClient.sequence,page['args']['sequence'])

    def test_current_handlers_move_one_eight_and_thirty_two_bodies_with_player_loot(self):
        for count in (1,8,32):
            with self.subTest(count=count):
                n=Network();s=n.server
                for l in (s,*n.clients.values()):
                    l.globals().count=count
                    l.execute('''
                        for i=3,count do
                            local b=corpse();b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
                            b.getSquare=body.getSquare;b.setSquare=body.setSquare
                            b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
                            b.world=false;sq:addCorpse(b)
                            World.move(b,-(i-1)*3,0,0,gridSquare(-(i-1)*3,0,0))
                        end
                        body.isPlayer=function() return true end;body.isZombie=function() return false end
                        bag=item('Base.Bag_DuffelBag');bag.kind='InventoryContainer';bag.inv=container()
                        bag.getInventory=function(s) return s.inv end
                        loot=item('Base.Watch');loot.md={owner='player loot',charge=.37}
                        bag.inv:AddItem(loot);body.inv:AddItem(bag)
                        originalLoot=equipmentEncode(loot);originalBagID=bag.id
                        originalBodies={};originalItems={}
                        for i=1,count do originalBodies[i]=bodies[i];originalItems[i]=bodies[i].inv:getItems():get(0) end
                        if serverMode then
                            H.discover();root=link(C,A,rope);local last=A
                            for i=2,count do
                                local b=bodies[i];local ref={kind='body',key=b.md.CVPBodyKey,point='feet'}
                                local gear=item('Base.Rope');storage:AddItem(gear);link(last,ref,gear);last=ref
                            end
                            player.x=0;player.y=0
                        end
                    ''')
                n.publish()
                n.clients['owner'].execute('physicsOwner=true')
                for _ in range(36):n.tick(.04)
                # Let the confirmed 150 ms hitch trajectory reach the stopped car.
                for _ in range(2):n.tick()
                s.execute('''assert(body.x>.1)
                    local tail=bodies[count];local initial=-(count-1)*3
                    if count<32 then assert(tail.x>initial+.01) else
                        -- This short trip does not take up all 31 rope allowances.
                        -- With intra-chain contacts disabled, a slack tail stays put.
                        local record
                        for _,r in pairs(R.simulation.records) do if r.body==tail then record=r end end
                        assert(record and not record.failed and not record.taut)
                        assert(math.abs(tail.x-initial)<.005)
                    end
                ''')
                for _ in range(12):n.tick()
                for _ in range(30):
                    s.execute('car.y=car.y+.03');n.tick()
                for _ in range(20):n.tick(-.02)
                for _ in range(15):n.tick()
                for l in (s,*n.clients.values()):
                    l.execute('''
                        local graph=serverMode and S.graph or CVPMPClient.graph
                        local links=0;for _ in pairs(graph.links) do links=links+1 end;assert(links==count)
                        for i=1,count do local b=bodies[i]
                            assert(b==originalBodies[i] and worldCount(b)==1)
                            assert(b.inv:getItems():get(0)==originalItems[i])
                        end
                        assert(body.inv:getItems():size()==2 and bag.id==originalBagID)
                        assert(bag.inv:getItems():size()==1 and equipmentEncode(loot)==originalLoot)
                    ''')
                for c in n.clients.values():
                    for i in range(1,count+1):
                        b=c.globals().bodies[i];target=s.globals().bodies[i]
                        self.assertLess((b.x-target.x)**2+(b.y-target.y)**2,.25)
                s.execute("beside(S.graph.links[root].a);assert(R:command(player,{id=root,revision=S.graph.links[root].revision,side='a',op='release'}))")
                n.publish()
                s.execute('before={};for i=1,count do before[i]={x=bodies[i].x,y=bodies[i].y} end')
                # The server stops immediately; clients finish their delayed interpolation.
                for _ in range(5):n.tick()
                s.execute('for i=1,count do assert(bodies[i].x==before[i].x and bodies[i].y==before[i].y) end')
                for c in n.clients.values():
                    for i in range(1,count+1):
                        self.assertAlmostEqual(c.globals().bodies[i].x,s.globals().bodies[i].x,places=6)
                        self.assertAlmostEqual(c.globals().bodies[i].y,s.globals().bodies[i].y,places=6)
                    c.execute('before={};for i=1,count do before[i]={x=bodies[i].x,y=bodies[i].y} end')
                for _ in range(10):n.tick(.1)
                for l in (s,*n.clients.values()):
                    # Authority must stop exactly; interpolation may round the final pose.
                    l.execute('''
                        for i=1,count do
                            local delta=math.abs(bodies[i].x-before[i].x)+math.abs(bodies[i].y-before[i].y)
                            assert(serverMode and delta==0 or not serverMode and delta<1e-6)
                        end
                    ''')

    def test_client_render_failure_does_not_disable_physics_owner_load(self):
        n=Network();s=n.server;c=n.clients['owner'];s.execute('link(C,A,rope)');n.publish()
        c.execute("physicsOwner=true;CVPFreeRopeScene.update=function() error('renderer unavailable') end")
        for _ in range(12):n.tick(.05)
        # Isolate the render failure from the solver reaction magnitude.
        c.execute("CVPMPClient.loads['sql:71'].resistanceForceN=750;now=now+20;CVPMPClient.tick()")
        c.execute('assert(#impulses>0 and CVPMPClient.renderError and body.x>0)')

    def test_authoritative_load_ignores_legacy_prediction_timeout_and_release(self):
        n=Network();s=n.server;c=n.clients['owner'];observer=n.clients['friend']
        s.execute('link(C,A,rope)');n.publish()
        # Publish through actual paging and validation; observers need no estimates.
        s.execute('''
            player.getOnlineID=function() return 1 end;player2.getOnlineID=function() return 2 end
            snap=CVPMPServer.capture();local row=snap.loads['sql:71']
            row.owner=1;row.resistanceForceN=0
            row.loadEstimate={hitch={x=0,y=0,z=.25,dx=1,dy=0,slack=0,mass=75,loadMass=0}}
            local W=require 'CVP_LinkWire'
            local pages=W.pages(snap.graph,snap.bodies,snap.loads,snap.index,player,snap.obstacles)
            local page=pages[1];page.epoch='e';page.session='s';page.sequence=1;page.ready=true
            page.frameSchema=1;page.sampledAt=now;page.intervalSeconds=0
            assert(W.page(page))
            row.resistanceForceN=math.huge;assert(not W.page(page))
            row.resistanceForceN=0/0;assert(not W.page(page))
            row.resistanceForceN=-1;assert(not W.page(page));row.resistanceForceN=0
            CVPMPServer.sequence=CVPMPServer.sequence+1
            for _,p in ipairs(players) do CVPMPServer.publish(p,snap) end
        ''');n.pump()
        for client in (c,observer):
            client.execute('''
                physicsOwner=localName=='owner';car.getNetPlayerId=function() return 1 end
                player.isLocalPlayer=function() return localName=='owner' end
                CVPMPClient.host.sample=function(e) return {x=car.x,y=0,z=.25} end
                car.x=0;now=100;CVPMPClient.tick();impulses={}
                now=150;car.x=.5;CVPMPClient.tick()
            ''')
        c.execute('assert(#impulses==0 and CVPMPClient.loads["sql:71"].resistanceForceN==0)')
        observer.execute('assert(#impulses==0,"observer applied a force without physics ownership")')
        c.execute('''
            local sample=CVPMPClient.host.sample;local samples=0
            CVPMPClient.host.sample=function(e) samples=samples+1;return sample(e) end
            now=155;CVPMPClient.tick()
            assert(samples==0,'authoritative load must not resample prediction anchors')
            -- Legacy estimates cannot create a force absent from the server force.
            assert(CVPMPClient.loadPrediction==nil)
            local row=CVPMPClient.loads['sql:71'];row.resistanceForceN=750
            local count=#impulses;now=160;CVPMPClient.tick()
            assert(#impulses==count+1 and samples==0)
            row.resistanceForceN=0;now=180;CVPMPClient.tick();assert(#impulses==count+1)
        ''')
        c.execute('''
            local count=#impulses;now=1200;car.x=5;CVPMPClient.tick()
            assert(#impulses==count and CVPMPClient.loadPrediction==nil)
        ''')
        s.execute("local id,link=next(S.graph.links);beside(link.a);assert(R:command(player,{id=id,revision=link.revision,side='a',op='release'}))")
        n.publish()
        c.execute('now=1250;local count=#impulses;CVPMPClient.tick();assert(#impulses==count)')

    def test_observer_does_not_receive_unrelated_remote_train(self):
        n=Network();s=n.server
        s.execute('link(C,A,rope);link(A,B,chain);player2.x=1000');n.publish()
        n.clients['owner'].execute('assert(next(CVPMPClient.graph.links))')
        n.clients['friend'].execute('assert(not next(CVPMPClient.graph.links))')

    def test_actual_handler_save_and_reload_preserves_ground_end(self):
        n=Network();s=n.server;c=n.clients['owner']
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry')");n.finish()
        s.execute('callbacks.OnSave()');saved=copy_packet(s.globals().equipmentDisk)
        fresh=vm(True,saved=saved)
        fresh.execute("now=now+1000;CVPMPServer.tick();local graph=CVPMPServer.authority.service.graph;local _,row=next(graph.links);assert(row.a.key=='A' and row.b.kind=='ground');assert(require('CVP_Equipment').get(row.equipment):getID()==rope.id)")

    def test_car_menu_releases_only_car_end_with_client_database_id_missing(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute('root=link(C,A,rope);tail=link(A,B,chain)');n.publish()
        c.execute("carMenu();choose('IGUI_CVP_DetachFromCar')");n.finish();n.publish()
        s.execute("assert(S.graph.links[root].a.kind=='ground' and S.graph.links[tail].a.key=='A')")
        for c in n.clients.values():
            c.execute("local grounded=0;for _,row in pairs(CVPMPClient.graph.links) do if row.a.kind=='ground' then grounded=grounded+1 end end;assert(grounded==1)")

    def test_rewire_menu_commits_same_graph_for_both_clients(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute('first=link(C,A,rope);second=link(C,B,chain)');n.publish()
        c.execute("carMenu();choose('IGUI_CVP_Rewire')");n.finish();n.publish()
        s.execute("assert(S.graph.links[second].a.kind=='body' and S.graph.links[second].a.key=='A')")
        expected=copy_packet(s.globals().S.graph)
        for c in n.clients.values():self.assertEqual(expected,copy_packet(c.globals().CVPMPClient.graph))

    def test_motion_load_owner_handoff_and_release_final_pose(self):
        n=Network();s=n.server
        s.execute('root=link(C,A,rope);tail=link(A,B,chain)');n.publish()
        n.clients['owner'].execute('physicsOwner=true');n.clients['friend'].execute('physicsOwner=false')
        for _ in range(35):n.tick(.035)
        s.execute('assert(body.x>0 and body2.x>-3 and #impulses==0)')
        n.clients['owner'].execute('assert(body.x>0 and tracked[body] and next(drawn) and #impulses>0)')
        n.clients['friend'].execute('assert(body.x>0 and #impulses==0)')
        owner_impulses=len(n.clients['owner'].globals().impulses)
        n.clients['owner'].execute('physicsOwner=false');n.clients['friend'].execute('physicsOwner=true')
        for _ in range(5):n.tick(.035)
        self.assertEqual(owner_impulses,len(n.clients['owner'].globals().impulses))
        n.clients['friend'].execute('assert(#impulses>0)')
        s.execute("beside(S.graph.links[tail].b);assert(R:command(player,{id=tail,revision=S.graph.links[tail].revision,side='b',op='release'}))")
        final_x=s.globals().body2.x;n.publish()
        for c in n.clients.values():self.assertAlmostEqual(c.globals().body2.x,final_x,places=7)
        # Repeated terminal snapshots must not overwrite a later ordinary body move.
        for c in n.clients.values():c.execute('body2.x=body2.x+1')
        n.publish()
        for c in n.clients.values():self.assertAlmostEqual(c.globals().body2.x,final_x+1,places=7)

    def test_body_bootstrap_ignores_duplicate_and_stale_parts(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('root=link(C,A,rope)');n.publish()
        c.execute('body.sq:removeCorpse(body);now=now+100;CVPMPClient.tick()')
        requests=take(c,'clientPackets');request=next(p for p in requests if p['name']=='body')
        n.send(request);parts=[p for p in take(s,'packets') if p['name']=='body']
        self.assertTrue(parts)
        for p in parts:n.receive(p)
        for p in parts:n.receive(p)
        c.execute('assert(replicas==1 and worldCount(body)==1 and body.inv:getItems():size()==1)')
        s.execute("beside(S.graph.links[root].b);assert(R:command(player,{id=root,revision=S.graph.links[root].revision,side='b',op='remove'}))")
        n.publish();c.execute('body.sq:removeCorpse(body)')
        for p in parts:n.receive(p)
        c.execute('assert(not body.world and replicas==1)')

    def test_multiframe_snapshot_over_320_links_applies_only_when_complete(self):
        n=Network();s=n.server;c=n.clients['owner']
        # Ground-only links need no simulated native bodies; transport still validates
        # the full graph and its equipment uniqueness. There is no legacy 320-row cap.
        s.execute('''
            local graph=G.empty()
            for i=1,337 do local id='free:'..i
                graph.links[id]={id=id,revision=1,owner='owner',equipment='gear:'..i,material='Base.Rope',length=1,
                    a={kind='ground',x=0,y=0,z=.025},b={kind='ground',x=1,y=0,z=.025}}
            end
            local W=require 'CVP_LinkWire';local index=assert(G.index(graph));local peer=CVPMPServer.peers[player]
            for _,page in ipairs(W.pages(graph,{},{},index,player)) do
                page.protocol=require('CVP_LinkWire').version;page.epoch=CVPMPServer.epoch;page.session=peer.session;page.sequence=900;page.ready=true
                page.frameSchema=1;page.sampledAt=now;page.intervalSeconds=0
                sendServerCommand(player,'CVP','state',page)
            end
        ''')
        pages=take(s,'packets');self.assertGreater(len(pages),1)
        for page in reversed(pages[1:]):n.receive(page)
        c.execute('assert(not next(CVPMPClient.graph.links))')
        n.receive(pages[-1]);c.execute('assert(not next(CVPMPClient.graph.links))')
        n.receive(pages[0]);c.execute('local count=0;for _ in pairs(CVPMPClient.graph.links) do count=count+1 end;assert(count==337)')
        n.receive(pages[0]);c.execute('assert(CVPMPClient.sequence==900)')

    def test_truncated_malformed_and_old_snapshots_do_not_clear_current_links(self):
        n=Network();s=n.server;c=n.clients['owner'];s.execute('root=link(C,A,rope)');n.publish()
        before=copy_packet(c.globals().CVPMPClient.graph)
        s.execute('publish()');packets=take(s,'packets');page=next(p for p in packets if p['who']=='owner' and p['name']=='state')
        page['args']['sequence']+=10;page['args']['count']=2
        n.receive(page);self.assertEqual(before,copy_packet(c.globals().CVPMPClient.graph))
        c.execute('now=now+6000;CVPMPClient.tick()');self.assertIsNone(c.globals().CVPMPClient.assembly)
        page['args']['count']=1;page['args']['links'][1]['length']=-1
        n.receive(page);self.assertEqual(before,copy_packet(c.globals().CVPMPClient.graph))

    def test_restart_epoch_cancels_pending_and_cannot_be_reverted(self):
        n=Network();c=n.clients['owner'];s=n.server
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry');finishStage()")
        self.assertTrue(c.globals().CVPMPClient.actions.jobs[c.globals().player].waiting is not None)
        s.execute('publish()');old=take(s,'packets')
        s.execute("CVPMPServer.epoch='new-server-epoch';CVPMPServer.sequence=0;publish()")
        for packet in take(s,'packets'):n.receive(packet)
        c.execute("assert(CVPMPClient.epoch=='new-server-epoch' and not next(CVPMPClient.pending));assert(CVPMPClient.actions.jobs[player].finished)")
        for packet in old:n.receive(packet)
        self.assertEqual(c.globals().CVPMPClient.epoch,'new-server-epoch')

    def test_foreign_and_spoofed_actions_cannot_move_or_return_equipment(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('root=link(C,A,rope);SandboxVars.CorpseProxyLab.AllowDetachOthers=false');n.publish()
        row=next(iter(copy_packet(c.globals().CVPMPClient.graph)['links'].values()))
        c.globals().commandArgs=c.table_from({'id':row['id'],'revision':row['revision'],'side':'b','op':'remove'},recursive=True)
        c.execute("CVPMPClient.api.request(localPlayer,'command',commandArgs,function(ok,_,why) answer={ok=ok,why=why} end)")
        n.pump();self.assertFalse(c.globals().answer.ok)
        s.execute('assert(S.graph.links[root] and rope:getContainer()~=storage)')
        packet={'who':'friend','name':'create','args':{'protocol':s.eval("require('CVP_LinkWire').version"),'session':c.globals().CVPMPClient.session,
            'epoch':c.globals().CVPMPClient.epoch,'request':12,'args':{'token':'invented','target':{'kind':'ground','x':900,'y':900,'z':9}}}}
        n.send(packet);s.execute('assert(S.graph.links[root] and otherRope:getContainer()==player2.inv)')

    def test_no_client_physics_runs_after_state_timeout(self):
        n=Network();n.server.execute('link(C,A,rope)');n.publish()
        c=n.clients['owner'];c.execute('physicsOwner=true')
        for _ in range(10):n.tick(.05)
        count=len(c.globals().impulses)
        c.execute("now=now+11000;CVPMPClient.tick();assert(CVPMPClient.connectionReason()=='IGUI_CVP_SyncLost');assert(not next(drawn) and not tracked[body])")
        self.assertEqual(count,len(c.globals().impulses))

    def test_menu_carry_body_chain_car_release_and_exact_return(self):
        n = Network(); c = n.clients['owner']; s = n.server
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry')")
        self.assertIsNone(s.globals().S.graph.links[next(iter(s.globals().S.graph.links), '')])
        self.assertTrue(n.finish().finished)
        s.execute("local _,row=next(S.graph.links);assert(row.a.key=='A' and row.b.kind=='held');assert(rope:getContainer()~=storage)")
        c.execute("menu(body2);choose('IGUI_CVP_LinkBindBody')"); n.finish(); n.publish()
        for client in n.clients.values():
            client.execute("local _,row=next(CVPMPClient.graph.links);assert(row.a.key=='A' and row.b.key=='B')")
            self.assertEqual(client.globals().equipmentWrites, 0)
        c.execute("menu(body2);choose('IGUI_CVP_DetachBody')"); n.finish()
        s.execute("local _,row=next(S.graph.links);assert(row.b.kind=='ground')")
        c.execute("menu(body);choose('IGUI_CVP_LinkRemoveRope')"); n.finish(); n.publish()
        s.execute('assert(not next(S.graph.links) and rope:getContainer()==storage)')
        for client in n.clients.values():
            client.execute('assert(not next(CVPMPClient.graph.links))')
        c.execute('assert(storage:getItemWithID(rope.id) and storage:getItems():size()==2)')

    def test_duplicate_rpc_returns_same_result_without_second_transfer(self):
        n = Network(); c = n.clients['owner']; s = n.server
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry');finishStage()")
        request = take(c, 'clientPackets')[0]
        p=s.globals().player;p.x=c.globals().player.x;p.y=c.globals().player.y
        n.send(request); n.send(request)
        replies=take(s,'packets');results=[p['args'] for p in replies if p['name']=='result']
        self.assertEqual(results[0]['result'], results[1]['result'])
        for packet in replies: n.receive(packet)
        create = take(c,'clientPackets')[0]; n.send(create);n.send(create)
        for packet in take(s,'packets'): n.receive(packet)
        n.pump()
        s.execute('local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1 and rope:getContainer()~=storage)')

    def test_same_snapshot_refreshes_replaced_local_body_before_callbacks(self):
        n=Network();n.server.execute('link(C,A,rope)');n.publish()
        c=n.clients['owner'];c.execute("""
            body.world=false;body2.md.CVPBodyKey='A';body2.netID=body.netID;bodies={body2}
        """)
        n.publish()
        c.execute("assert(CVPMPClient.host.body({kind='body',key='A'})==body2)")

    def test_pending_duplicate_does_not_transfer_twice(self):
        from test_save_jobs import DELAY
        n=Network();c=n.clients['owner'];s=n.server
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry');finishStage()")
        request=take(c,'clientPackets')[0]
        p=s.globals().player;p.x=c.globals().player.x;p.y=c.globals().player.y
        n.send(request)
        for packet in take(s,'packets'): n.receive(packet)
        create=take(c,'clientPackets')[0]
        s.execute(DELAY)
        n.send(create);n.send(create)
        self.assertFalse([p for p in take(s,'packets') if p['name']=='result'])
        s.execute('assert(R.saveJob and rope:getContainer()==storage)')
        for _ in range(30):
            s.execute('now=now+16;CVPMPServer.tick()')
            if not s.globals().R.saveJob: break
        results=[p for p in take(s,'packets') if p['name']=='result']
        self.assertEqual(len(results),1)
        self.assertTrue(results[0]['args']['ok'])
        writes=s.globals().equipmentWrites
        n.send(create)
        repeated=[p for p in take(s,'packets') if p['name']=='result']
        self.assertEqual(len(repeated),1)
        self.assertEqual(results[0]['args']['result']['id'],repeated[0]['args']['result']['id'])
        self.assertEqual(writes,s.globals().equipmentWrites)
        s.execute('local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1 and rope:getContainer()~=storage)')

    def test_ack_waits_for_complete_state_and_ignores_late_duplicate(self):
        n=Network();c=n.clients['owner'];s=n.server
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry');finishStage()")
        request=take(c,'clientPackets')[0];n.send(request)
        packets=take(s,'packets');result=next(p for p in packets if p['name']=='result')
        n.receive(result);self.assertEqual(len(take(c,'clientPackets')),0)
        for packet in packets:
            if packet['name']=='state':n.receive(packet)
        self.assertEqual(len(take(c,'clientPackets')),1)
        n.receive(result);self.assertEqual(len(take(c,'clientPackets')),0)

    def test_two_players_cannot_pick_up_same_free_end(self):
        n=Network();s=n.server
        s.execute("id=link(A,B,rope);beside(S.graph.links[id].b);assert(R:command(player,{id=id,revision=S.graph.links[id].revision,side='b',op='release'}))")
        n.publish()
        for c in n.clients.values():
            c.execute("local id,row=next(CVPMPClient.graph.links);localPlayer.x=row.b.x;localPlayer.y=row.b.y;CVPMPClient.actions:command(localPlayer,id,row.revision,'b','take')")
            c.execute('finishStage()')
        n.pump();s.execute("assert(S.graph.links[id].b.kind=='held' and S.graph.links[id].b.holder=='owner')")
        for c in n.clients.values():self.assertEqual(c.globals().equipmentWrites,0)

    def test_disconnect_drops_held_end_and_new_session_rejects_old_packets(self):
        n=Network();c=n.clients['owner'];s=n.server
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry')");n.finish();n.publish()
        s.execute('publish()');old=take(s,'packets')
        s.execute('players={player2};now=now+1000;CVPMPServer.tick()')
        s.execute("local _,row=next(S.graph.links);assert(row.b.kind=='ground')")
        # New Lua session on the same account; no held-end claim survives.
        n.clients['owner']=vm(False);n.clients['owner'].execute("CVPMPClient.session='reconnected-session';clientPackets={};callbacks.OnGameStart()")
        s.execute('players={player,player2}')
        n.pump();fresh=n.clients['owner']
        for p in old:
            if p['who']=='owner':n.receive(p)
        fresh.execute("local _,row=next(CVPMPClient.graph.links);assert(row.b.kind=='ground')")

    def test_outdated_protocol_has_specific_message_and_no_mutation(self):
        n=Network();c=n.clients['owner']
        c.execute("CVPMPClient.receive('state',{protocol=3});assert(CVPMPClient.connectionReason()=='IGUI_CVP_ProtocolMismatch')")
        c.execute("local called=false;CVPMPClient.api.request(player,'prepare',{target=A,gear=rope.id},function(ok) called=true;assert(not ok) end);assert(called)")
        self.assertEqual(len(take(c,'clientPackets')),0)


if __name__=='__main__':unittest.main()
