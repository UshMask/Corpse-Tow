"""Behavioral guards for bounded work; timings are diagnostic, not assertions."""
import unittest
from test_link_runtime import environment
from test_link_client import client
from test_link_multiplayer import Network, take


class LinkPerformanceTests(unittest.TestCase):
    def test_stale_body_cache_uses_live_native_match_without_waiting_for_discovery(self):
        for server in (False, True):
            l=environment();l.globals().serverMode=server;l.execute("""
                function isServer() return serverMode end
                H.discover();local ref={kind='body',key='A',native=body.netID,point='feet'}
                local reads=0;local find=CVPNetwork.find
                CVPNetwork.find=function(id) reads=reads+1;return find(id) end
                assert(H.body(ref)==body and reads==0)
                body.world=false
                body2.md.CVPBodyKey='A';body2.netID=body.netID;bodies={body2}
                assert(H.body(ref)==body2 and reads==1)
                local resolved=assert(H.resolve(ref,player));assert(resolved.key=='A')
                body2.md.CVPBodyKey='other';assert(not H.body(ref))
                body2.md.CVPBodyKey='A';H.bodies.A=false;assert(not H.body(ref))
                H.bodies.A=body;body2.world=false;assert(not H.body(ref))
                assert(rope:getContainer()==storage and chain:getContainer()==storage)
            """)

    def test_discovery_does_not_checkpoint_movement_without_free_equipment(self):
        for server in (False, True):
            with self.subTest(server=server):
                l=environment();l.globals().serverMode=server
                l.execute('''
                    function isServer() return serverMode end
                    function sendRemoveItemFromContainer() end
                    function sendAddItemToContainer() end
                    link(C,A,rope);run();assert(S:flush())
                    R.recovered[player]=now+10000
                    local writes=equipmentWrites;now=now+1000;car.x=car.x+.2
                    assert(S:tick(H.samples(S.graph)));assert(S.dirty)
                    assert(R:discover({player}));assert(equipmentWrites==writes and S.dirty)
                    now=now+1000;assert(S:tick(H.samples(S.graph)))
                    assert(equipmentWrites==writes+1 and not S.dirty)
                    intact(body);assert(E.get(S.graph.links[next(S.graph.links)].equipment)==rope)
                ''')

    def test_checkpoint_reuses_plans_and_indexes_without_publishing_failed_write(self):
        for server in (False, True):
            with self.subTest(server=server):
                l=environment();l.globals().serverMode=server
                l.execute('''
                    function isServer() return serverMode end
                    function sendRemoveItemFromContainer() end
                    function sendAddItemToContainer() end
                    local id=link(C,A,rope);run();assert(S:flush());Sim:build(S.graph,S.index)
                    local graph,idx,groups=S.graph,S.index,Sim.groups
                    local revision=S.persistedRevision;local disk=serializeEquipment()
                    car.x=car.x+.2;assert(S:tick(H.samples(S.graph)));assert(S.dirty)
                    equipmentWriteFailure=true;assert(not S:flush())
                    assert(S.dirty and S.persistedRevision==revision and S.graph==graph and S.index==idx)
                    assert(serializeEquipment().graph.revision==disk.graph.revision)
                    assert(E.get(graph.links[id].equipment)==rope);intact(body)
                    equipmentWriteFailure=false
                    local index=G.index;local calls=0
                    G.index=function(...) calls=calls+1;return index(...) end
                    assert(S:flush());G.index=index
                    assert(calls==2,'checkpoint repeated graph validation: '..calls)
                    Sim:build(S.graph,S.index)
                    assert(S.graph==graph and S.index==idx and Sim.groups==groups)
                    assert(S.persistedRevision==revision+1 and not S.dirty)
                    local tail=link(A,B,chain);Sim:build(S.graph,S.index)
                    assert(S.index~=idx and Sim.groups~=groups and Sim.records[tail],
                        'real topology change must still rebuild plans')
                    local saved=serializeEquipment();assert(saved.graph.links[id].a.x==graph.links[id].a.x)
                    local key=graph.links[id].equipment
                    loadEquipment(saved);local restored=require 'CVP_Equipment'
                    assert(restored.links().links[id].a.x==graph.links[id].a.x)
                    assert(restored.get(key):getID()==rope:getID());intact(body)
                ''')

    def test_unrelated_discovery_keeps_plans_but_unload_rebuilds(self):
        for server in (False, True):
            l=environment();l.globals().serverMode=server
            l.execute("""
                function isServer() return serverMode end
                function sendRemoveItemFromContainer() end
                function sendAddItemToContainer() end
                link(C,A,rope);H.discover();Sim:build(S.graph,S.index)
                local groups=Sim.groups
                body2.md.CVPBodyKey='unrelated';H.discover();Sim:build(S.graph,S.index)
                assert(Sim.groups==groups)
                local vehicles=cell.getVehicles
                local other=setmetatable({md={},getSqlId=function() return 999 end,
                    getModData=function(s) return s.md end},{__index=car})
                cell.getVehicles=function() return {iterator=function()
                    local rows={car,other};local i=0
                    return {hasNext=function() return i<2 end,next=function() i=i+1;return rows[i] end}
                end} end
                H.discover();Sim:build(S.graph,S.index);assert(Sim.groups==groups)
                cell.getVehicles=vehicles;H.discover();Sim:build(S.graph,S.index);assert(Sim.groups==groups)
                local index=body.getStaticMovingObjectIndex
                body.getStaticMovingObjectIndex=function() return -1 end
                H.discover();Sim:build(S.graph,S.index);assert(Sim.groups~=groups and not H.body(A))
                groups=Sim.groups;body.getStaticMovingObjectIndex=index
                H.discover();Sim:build(S.graph,S.index);assert(Sim.groups~=groups and H.body(A)==body)
                intact(body);assert(E.get(S.graph.links[next(S.graph.links)].equipment)==rope)
            """)

    def test_mp_discovery_is_periodic_not_per_movement_packet(self):
        n=Network();n.server.execute('link(C,A,rope)');n.publish()
        c=n.clients['owner']
        c.execute("""
            scans=0;local discover=CVPMPClient.host.discover
            CVPMPClient.host.discover=function() scans=scans+1;return discover() end
        """)
        for _ in range(8):
            n.server.execute('car.x=car.x+.01');n.tick(.1)
        self.assertLessEqual(c.eval('scans'),1)
        c.execute("""
            local before=scans;now=now+1001;CVPMPClient.tick();assert(scans==before+1)
            body.sq:removeCorpse(body);now=now+1001;CVPMPClient.tick()
            assert(not CVPMPClient.host.body({key="A",native=body.netID}))
            body.sq:addCorpse(body);now=now+251;CVPMPClient.tick()
            assert(CVPMPClient.rows.A.body==body)
            local before=scans;CVPMPClient.host.discover();assert(scans==before+1)
        """)

    def test_legacy_checks_new_objects_immediately_and_reconciles_later(self):
        l=environment();l.execute("""
            local legacy=require 'CVP_Legacy';local observe=E.observeBody;local calls={}
            E.observeBody=function(b) calls[b]=(calls[b] or 0)+1;return observe(b) end
            assert(legacy.migrate(R));assert(calls[body]==1 and calls[body2]==1)
            now=now+1000;assert(legacy.migrate(R));assert(calls[body]==1)
            R.legacyChecks[body2]=nil -- newly discovered native instance
            assert(legacy.migrate(R));assert(calls[body2]==2 and calls[body]==1)
            R.recoveryErrors[body]='retry';assert(legacy.migrate(R));assert(calls[body]==2)
            now=now+5000;assert(legacy.migrate(R));assert(calls[body]==3 and calls[body2]==3)
            intact(body);intact(body2)
        """)

    def test_joint_placement_only_runs_for_actual_intermediate_nodes(self):
        l=environment();l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain)
            local joints=require 'CVP_LinkJoints';local place=joints.place;local calls=0
            joints.place=function(...) calls=calls+1;return place(...) end
            run();assert(calls==0,'ordinary tethers placed nonexistent joints')
            assert(S:unloadBody(A.key,H.sample(A)))
            run();assert(calls==2,'intermediate joint was not updated before and after solving')
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint')
            joints.place=place
        ''')

    def test_moving_substeps_reuse_tick_inputs_but_refresh_next_tick(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);link(A,B,chain)
            local load=require 'CVP_Load';local graph=require 'CVP_LinkGraph'
            local refresh=load.refresh;local sample=H.sample
            local refreshes,samples=0,0
            load.refresh=function(...) refreshes=refreshes+1;return refresh(...) end
            H.sample=function(...) samples=samples+1;return sample(...) end
            car.x=car.x+.2;Sim:tick(S.graph,S.index,.1,now)
            assert(refreshes==2 and samples<=4,'repeated inputs inside movement substeps')
            local r=Sim.records[root];local previousX=r.sourceSample.x
            S.graph.links[root].allocation=graph.capacityFor(S.graph.links[root])+1
            car.x=car.x+.2;now=now+1001;refreshes=0;samples=0
            Sim:tick(S.graph,S.index,.1,now)
            assert(refreshes==2 and samples<=4)
            assert(r.sourceSample.x~=previousX,'vehicle source must refresh every tick')
            assert(r.maxGapSquared==(graph.capacityFor(S.graph.links[root])+6)^2)
            intact(body);intact(body2)
        ''')

    def test_unchanged_discovery_preserves_paths_and_skeleton_work(self):
        l = environment(); l.execute('''
            link(C,A,rope);link(A,B,chain);H.discover()
            local syncs=0;CVPSkeletonNative.sync=function() syncs=syncs+1 end
            Sim:build(S.graph,S.index);R:skeletons()
            local groups,generation,count=Sim.groups,H.generation,syncs
            for i=1,20 do
                car.x=car.x+.1;move(body,body.x+.01,body.y)
                H.discover();Sim:build(S.graph,S.index);R:skeletons()
                assert(H.generation==generation and Sim.groups==groups)
                assert(syncs==count,'unchanged discovery repeated skeleton work')
            end
            intact(body);intact(body2)
        ''')

    def test_discovery_tracks_body_availability_even_with_same_identity(self):
        l = environment(); l.execute('''
            H.discover();local generation=H.generation
            local index=body.getStaticMovingObjectIndex
            body.getStaticMovingObjectIndex=function() return -1 end
            H.discover();assert(H.generation==generation+1 and not H.body(A))
            H.discover();assert(H.generation==generation+1)
            body.getStaticMovingObjectIndex=index
            H.discover();assert(H.generation==generation+2 and H.body(A)==body)
            local sq=body.getSquare;body.getSquare=function() return nil end
            H.discover();assert(H.generation==generation+3 and not H.body(A))
            body.getSquare=sq;H.discover();assert(H.generation==generation+4 and H.body(A)==body)
        ''')

    def test_discovery_replacement_ambiguity_and_vehicle_reload(self):
        l = environment(); l.execute('''
            H.discover();local generation=H.generation
            body2.md.CVPBodyKey='A';H.discover()
            assert(H.generation==generation+1 and not H.body(A))
            H.discover();assert(H.generation==generation+1)
            local original=bodies;bodies={body2};H.discover()
            assert(H.generation==generation+2 and H.body(A)==body2)
            bodies=original;body2.md.CVPBodyKey='B';H.discover()
            assert(H.generation==generation+3 and H.body(A)==body)
            local sq=car.getSquare;car.getSquare=function() return nil end
            H.discover();assert(H.generation==generation+4 and not H.vehicle(C))
            H.discover();assert(H.generation==generation+4)
            car.getSquare=sq;H.discover();assert(H.generation==generation+5 and H.vehicle(C)==car)
        ''')

    def test_equipment_read_index_expires_and_rejects_duplicate_ids(self):
        l = environment(); l.execute('''
            local id=link(A,B,rope);local key=S.graph.links[id].equipment
            E.beginRead();assert(E.get(key)==rope);E.endRead()
            local c=rope:getContainer();local duplicate=item('Base.Rope');c:AddItem(duplicate);duplicate.id=rope:getID()
            E.beginRead();assert(not E.get(key));E.endRead();c:Remove(duplicate)
            E.beginRead();assert(E.get(key)==rope);E.endRead()
            c:Remove(rope)
            E.beginRead();assert(not E.get(key));E.endRead()
        ''')

    def test_failed_runtime_tick_clears_read_scope(self):
        l = environment(); l.execute('''
            R.simulation.tick=function() error('injected failure') end
            assert(not R:tick({player},.016));assert(not CVPEquipmentRuntime.reading and not CVPEquipmentRuntime.readIndex)
        ''')

    def test_lazy_menu_builds_once_on_highlight_or_joypad_open(self):
        l = client(); l.execute('''
            local M=require 'CVP_Menu';local calls=0
            local parent={addOption=function() return {} end,addSubMenu=function(_,o,s) option=o end}
            local original=ISContextMenu.getNew
            ISContextMenu.getNew=function() return {setVisible=function(self,v) self.visible=v end,clear=function() end} end
            local sub=M.lazySub(parent,'test',function() calls=calls+1 end)
            option.onHighlight(option,parent,false);assert(calls==0)
            sub:setVisible(true);assert(calls==1 and sub.visible)
            option.onHighlight(option,parent,true);sub:setVisible(true);assert(calls==1)
            local unused=M.lazySub(parent,'unused',function() calls=calls+1 end)
            unused:clear();unused:setVisible(true);assert(calls==1)
            ISContextMenu.getNew=original
        ''')

    def test_sleeping_rope_not_resubmitted_but_motion_and_clear_rebuild(self):
        l = client(); l.execute('''
            link(C,A,rope);link(C,B,chain)
            for i=1,300 do now=now+1000/60;callbacks.OnTick() end
            local before=drawCalls
            for i=1,60 do now=now+1000/60;callbacks.OnTick() end
            assert(drawCalls==before)
            car.x=car.x+.1;now=now+1000/60;callbacks.OnTick();assert(drawCalls>before)
            local P=require('CVP_LinkPresentation').new(H);local graph=S.graph
            P:update(graph,H.samples(graph),.016);before=drawCalls;P:clear()
            P:update(graph,H.samples(graph),.016);assert(drawCalls>before)
        ''')

    def test_hidden_ropes_skip_sampling_and_resume_with_current_endpoints(self):
        l = client(); l.execute(''' 
            link(C,A,rope);tick() -- Populate the current displayed-body frame.
            local P=require('CVP_LinkPresentation').new(H)
            local sample=H.samples;local calls=0;local visible=true
            local shape=CVPFreeRopeScene.shape;local shapes=0
            CVPFreeRopeScene.shape=function(...) shapes=shapes+1;return shape(...) end
            local uploaded={};local update=CVPFreeRopeScene.update
            CVPFreeRopeScene.update=function(id,points,chain)
                uploaded[id]=equipmentCopy(points);return update(id,points,chain)
            end
            H.samples=function(...) calls=calls+1;return sample(...) end
            PZAPI={ModOptions={getOptions=function() return {getOption=function()
                return {getValue=function() return visible end} end} end}}
            P:update(S.graph,nil,.016);assert(calls==1 and next(P.curves))
            visible=false;P:update(S.graph,nil,.016)
            assert(calls==1 and not next(P.curves))
            car.x=car.x+.5;visible=true;P:update(S.graph,nil,.016)
            assert(calls==2 and next(P.curves))
            local id,r=next(P.curves);local before=shapes
            car.x=car.x+.5;P:update(S.graph,nil,.016)
            assert(shapes==before) -- shape integration is not yet due at 60 Hz
            local ends=H.samples(S.graph)[id]
            assert(math.abs(uploaded[id][1].x-ends.a.x)<1e-8,'endpoint must still update')
            P:update(S.graph,nil,.002)
            local sent=uploaded[id];assert(shapes==before+1)
            for i,p in ipairs(r.ropePoints) do
                assert(sent[i].x==p.x and sent[i].y==p.y and sent[i].z==p.z)
            end
            assert(#sent==#r.ropePoints)
        ''')

    def test_server_without_subscribers_simulates_without_capturing(self):
        n = Network(); s = n.server
        s.execute(''' 
            link(C,A,rope)
            local peers=CVPMPServer.peers;CVPMPServer.peers={}
            local capture=CVPMPServer.capture;local captures=0
            CVPMPServer.capture=function(...) captures=captures+1;return capture(...) end
            local tick=R.tick;local ticks=0
            R.tick=function(...) ticks=ticks+1;return tick(...) end
            for i=1,10 do car.x=car.x+.1;now=now+100;CVPMPServer.tick() end
            assert(captures==0 and ticks==10)
            CVPMPServer.peers=peers;now=now+100;CVPMPServer.tick()
            assert(captures==1)
        ''')
        self.assertTrue(any(p['who']=='owner' for p in take(s, 'packets')))

    def test_missing_body_search_is_bounded_and_loaded_body_reappears(self):
        n = Network(); n.server.execute('link(C,A,rope)'); n.publish()
        c = n.clients['owner']; c.execute('''
            body.sq:removeCorpse(body);calls=0;local find=CVPNetwork.find
            CVPNetwork.find=function(...) calls=calls+1;return find(...) end
            for i=1,60 do now=now+1000/60;CVPMPClient.tick() end
            assert(calls<=5)
            body.sq:addCorpse(body);now=now+251;CVPMPClient.tick()
            assert(CVPMPClient.rows.A.body==body)
        ''')

    def test_idle_heartbeat_without_resending_empty_state_on_player_movement(self):
        n = Network(); s = n.server
        take(s, 'packets')
        s.execute('for i=1,20 do now=now+100;CVPMPServer.tick() end')
        packets = take(s, 'packets')
        self.assertLessEqual(sum(p['who']=='owner' for p in packets), 3)
        s.execute('player.x=player.x+1;now=now+100;CVPMPServer.tick()')
        self.assertFalse(any(p['who']=='owner' for p in take(s, 'packets')))

    def test_last_visible_load_sends_one_clear_then_stays_idle(self):
        n=Network();s=n.server
        s.execute('root=link(C,A,rope)');n.publish()
        for _ in range(5): n.tick(.05)
        s.execute("beside(C);assert(R:command(player,{id=root,revision=S.graph.links[root].revision,side='a',op='release'}))")
        s.execute('now=now+100;CVPMPServer.tick()')
        packets=take(s,'packets')
        clears=[p for p in packets if p['who']=='owner' and p['name']=='loads']
        self.assertEqual(len(clears),1)
        self.assertFalse(clears[0]['args']['loads'])
        for packet in packets: n.receive(packet)
        n.clients['owner'].execute("assert(next(CVPMPClient.loads)==nil)")
        s.execute('for i=1,5 do now=now+100;CVPMPServer.tick() end')
        self.assertFalse(any(p['name']=='loads' for p in take(s,'packets')))

    def test_changed_graph_sends_without_waiting_for_heartbeat(self):
        n = Network(); s = n.server
        s.execute('now=now+100;CVPMPServer.tick()'); take(s, 'packets')
        s.execute('link(A,B,rope);now=now+100;CVPMPServer.tick()')
        self.assertTrue(any(p['who']=='owner' for p in take(s, 'packets')))

    def test_motion_batches_pose_invalidation_and_vehicle_sampling(self):
        l = environment(); l.execute(''' 
            link(C,A,rope);link(C,B,chain)
            local calls,anchors=0,0
            local sample=H.sample
            H.sample=function(e) if e.kind=='vehicle' then anchors=anchors+1 end;return sample(e) end
            for _,b in ipairs({body,body2}) do b.invalidateCorpse=function() calls=calls+1 end end
            for _,dt in ipairs({1/60,1/30,.1}) do
                calls=0;anchors=0;car.x=car.x+.1;now=now+dt*1000
                Sim:tick(S.graph,S.index,dt,now)
                assert(calls<=2,'pose invalidated per substep')
                assert(anchors==1,'same vehicle transform repeatedly sampled')
                for _,r in pairs(Sim.records) do assert(r.body:getAngle()==r.angle) end
            end
            intact(body);intact(body2)
        ''')

    def test_stationary_body_skips_pose_writes_but_validates_membership(self):
        l = environment(); l.execute('''
            local sq=body:getSquare();local x,y,z=body:getX(),body:getY(),body:getZ()
            local invalidations,writes=0,0
            body.invalidateRenderChunkLevel=function() invalidations=invalidations+1 end
            local set=body.setX;body.setX=function(b,v) writes=writes+1;set(b,v) end
            for i=1,120 do World.move(body,x,y,z,sq) end
            assert(invalidations==0 and writes==0)
            World.move(body,x+.01,y,z,sq);assert(invalidations==1 and writes==1)
            sq:removeCorpse(body)
            assert(not pcall(World.move,body,body:getX(),y,z,sq))
        ''')


if __name__ == '__main__':
    unittest.main()
