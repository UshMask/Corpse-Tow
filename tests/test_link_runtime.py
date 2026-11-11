"""Authoritative lifecycle, upgrade and movement with real Lua modules."""
from pathlib import Path
import unittest
from test_link_simulation import environment as simulation
from test_link_graph import plain


def environment(saved=None):
    lua = simulation()
    root = Path('CorpseProxyLab/42/media/lua/shared')
    lua.execute("package.preload['CVP_LinkRuntime']=assert(loadstring(...))",
                (root / 'CVP_LinkRuntime.lua').read_text(encoding='utf-8-sig'))
    if saved is not None:
        lua.globals().saved = lua.table_from(saved, recursive=True)
        lua.execute('loadEquipment(saved);E=require "CVP_Equipment";storage:Remove(rope);storage:Remove(chain)')
    lua.execute('''
        CVPSkeletonNative={version=function() return '2-graph-clocks' end,sync=function() end,retire=function() return false end}
        R=require('CVP_LinkRuntime').new(H);assert(R:start());S=R.service;Sim=R.simulation
        function run(players)
            now=now+50;local ok,err=R:tick(players or {player},.05);assert(ok,err)
        end
    ''')
    return lua


def migration_environment():
    lua=environment()
    from legacy_fixture import install_migration_seed
    install_migration_seed(lua)
    return lua


class LinkRuntimeTests(unittest.TestCase):
    def test_physics_clock_retains_time_and_wakes_for_topology_and_recovery(self):
        for fps in (30, 60, 144, 300):
            with self.subTest(fps=fps):
                l=environment();l.globals().fps=fps;l.execute("""
                    link(C,A,rope)
                    local calls,elapsed=0,0
                    Sim.tick=function(_,graph,index,dt) calls=calls+1;elapsed=elapsed+dt;return {},{[car]=75} end
                    for i=1,fps*2 do
                        local requests,loads=R:simulate(1/fps,i*1000/fps);R.loads=loads
                        assert(loads[car]==75 and #requests==0)
                    end
                    assert(calls<=201 and calls>=math.min(fps,90)*2)
                    assert(math.abs(elapsed+(R.motionElapsed or 0)-2)<1e-8)
                    local before=calls;S.index={};R:simulate(.001,2100);assert(calls==before+1)
                    Sim.pendingPoses={};R:simulate(.001,2101);assert(calls==before+2)
                """)

    def test_disabled_towing_does_not_reuse_previous_load(self):
        l=environment();l.execute("""
            link(C,A,rope);run()
            R.loads={[car]=75};R.motionElapsed=0
            H.enabled=function() return false end
            local requests,loads=R:simulate(.001,now)
            assert(next(loads)==nil);intact(body)
        """)

    def test_attach_follows_small_settling_but_rejects_large_displacement(self):
        for displacement in (.5,1.1):
            with self.subTest(displacement=displacement):
                l=environment();l.globals().shift=displacement
                l.execute("""
                    local root=link(C,A,rope)
                    beside(A);local token=assert(R:prepare(player,A,chain:getID()))
                    move(body,body.x,body.y+shift)
                    beside(B);local ok,why=R:create(player,token,B)
                    if shift<=1 then assert(ok,why);assert(chain:getContainer()~=storage)
                    else assert(not ok and why=='first endpoint moved');assert(chain:getContainer()==storage) end
                    assert(E.get(S.graph.links[root].equipment)==rope)
                    intact(body);intact(body2)
                """)

    def test_presentation_resamples_ground_and_dropped_held_ends(self):
        l=environment();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
            player.isDead=function() return true end
            local ok,err,points=R:samples(true);assert(ok,err)
            assert(S.graph.links[id].b.kind=='ground')
            local Frame=require 'CVP_SimulationFrame'
            local frame=Frame.capture(Sim,S.graph,{},now,.05,1,H,points)
            assert(frame.endpoints[id].b.x==S.graph.links[id].b.x)
            player.isDead=function() return false end
            local row=S.graph.links[id];row.b.x=row.a.x+100;row.b.y=row.a.y
            local before=row.b.x
            ok,err,points=R:samples(true);assert(ok,err)
            assert(S.graph.links[id].b.x<before)
            frame=Frame.capture(Sim,S.graph,{},now,.05,2,H,points)
            assert(frame.endpoints[id].b.x==S.graph.links[id].b.x)
            intact(body);intact(body2);assert(E.get(S.graph.links[id].equipment)==rope)
        ''')

    def test_failed_sampling_does_not_publish_visual_points(self):
        l=environment();l.execute('''
            link(C,A,rope)
            S.tick=function() return false,'write failed' end
            local ok,err,points=R:samples(true)
            assert(not ok and err=='write failed' and points==nil)
        ''')

    def test_attaching_car_to_another_players_body_chain_requires_permission(self):
        l = environment(); l.execute('''
            player.getUsername=function() return 'other' end;local tail=link(A,B,rope)
            player.getUsername=function() return 'player' end;SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            beside(C);local token=assert(R:prepare(player,C,chain:getID()));beside(A)
            local ok,err=R:create(player,token,A)
            assert(not ok and err=='not owner' and chain:getContainer()==storage)
            assert(S.graph.links[tail].owner=='other')
            SandboxVars.CorpseProxyLab.AllowDetachOthers=true
            assert(R:create(player,token,A));assert(chain:getContainer()~=storage)
        ''')

    def test_binding_own_free_end_to_foreign_chain_does_not_bypass_permission(self):
        l = environment(); l.execute('''
            player.getUsername=function() return 'other' end;link(A,B,rope)
            player.getUsername=function() return 'player' end
            local own=link(C,{kind='ground',x=0,y=0,z=.025},chain);edit(own,'release','a')
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false;beside(S.graph.links[own].b)
            local ok,err=R:command(player,{id=own,revision=S.graph.links[own].revision,side='b',op='bind',target=A})
            assert(not ok and err=='not owner' and S.graph.links[own].b.kind=='ground')
            assert(E.get(S.graph.links[own].equipment)==chain)
        ''')

    def test_independent_trains_on_same_car_do_not_share_link_ownership(self):
        l = environment(); l.execute('''
            player.getUsername=function() return 'other' end;local first=link(C,A,rope)
            player.getUsername=function() return 'player' end;SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            local second=link(C,B,chain)
            assert(S.graph.links[first].owner=='other' and S.graph.links[second].owner=='player')
        ''')

    def test_body_target_checks_its_moving_car_before_prepare_and_commit(self):
        l = environment(); l.execute('''
            link(C,A,rope);speed=2;beside(A)
            local token,err=R:prepare(player,A,chain:getID());assert(not token and err=='stop vehicle')
            speed=0;token=assert(R:prepare(player,A,chain:getID()));beside(B);speed=2
            local ok,err=R:create(player,token,B);assert(not ok and err=='stop vehicle')
            assert(chain:getContainer()==storage);speed=0;assert(R:create(player,token,B))
        ''')

    def test_upgrade_preserves_complete_chain_lengths_ids_gear_and_loot(self):
        for version in (2, 3):
            with self.subTest(version=version):
                l = migration_environment(); l.globals().version = version
                l.execute('''
                    local root,tail=legacy(version);local id=root.connection.id;local child=tail.connection.id
                    local length=root.length;local childLength=tail.length
                    run()
                    assert(not body.md.CVPTether and not body2.md.CVPTether)
                    assert(S.graph.links[id].length==length and S.graph.links[child].length==childLength)
                    assert(E.get(S.graph.links[id].equipment)==rope and E.get(S.graph.links[child].equipment)==chain)
                    assert(next(E.members(car.md.CVPVehicleKey,car.md.CVPConnections))==nil)
                    for i=1,30 do car.x=car.x+.04;run() end
                    assert(body.x>.1 and body2.x>-2.9)
                    intact(body);intact(body2)
                ''')

    def test_saved_legacy_chain_loads_in_current_only_vm_and_returns_originals(self):
        first=migration_environment()
        first.execute("rope.md.marker='saved-rope';chain.md.marker='saved-chain';legacy(3)")
        saved=plain(first.globals().equipmentDisk)
        metadata={name:plain(first.globals()[name].md) for name in ('body','body2','car')}
        ids={name:first.globals()[name].getID(first.globals()[name]) for name in ('rope','chain')}
        second=environment(saved)
        second.globals().old=second.table_from(metadata,recursive=True)
        second.globals().ids=second.table_from(ids)
        second.execute('''            assert(not package.preload.CVP_LegacyCore and not legacy)
            body.md=old.body;body2.md=old.body2;car.md=old.car;H.discover()
            local root=body.md.CVPTether;local tail=body2.md.CVPTether
            local a,b=root.connection.id,tail.connection.id
            run();assert(S.graph.links[a] and S.graph.links[b])
            assert(not body.md.CVPTether and not body2.md.CVPTether)
            local ropeItem=E.get(S.graph.links[a].equipment)
            local chainItem=E.get(S.graph.links[b].equipment)
            assert(ropeItem:getID()==ids.rope and ropeItem.md.marker=='saved-rope')
            assert(chainItem:getID()==ids.chain and chainItem.md.marker=='saved-chain')
            assert(R:save());run();assert(S.graph.links[a] and S.graph.links[b])
            edit(b,'remove','b');edit(a,'remove','b');run()
            assert(ropeItem:getContainer()==storage and chainItem:getContainer()==storage)
            assert(#storage.rows==2 and not next(S.graph.links));intact(body);intact(body2)
        ''')

    def test_unloaded_legacy_tail_defers_entire_train(self):
        l = migration_environment(); l.execute('''
            local root,tail=legacy(3);local square=body2.sq;body2.sq=nil
            run();assert(next(S.graph.links)==nil and body.md.CVPTether)
            assert(E.get(root.equipmentKey)==rope)
            body2.sq=square;now=1100;run()
            assert(S.graph.links[root.connection.id] and S.graph.links[tail.connection.id])
            assert(not body.md.CVPTether and not body2.md.CVPTether)
            intact(body);intact(body2)
        ''')

    def test_stretched_legacy_link_is_not_refitted_during_import(self):
        l = migration_environment(); l.execute('''
            local root,tail=legacy(3);local length=root.length;car.x=24
            -- Migration itself preserves the attachment; the subsequent solver
            -- releases only the car end when it observes the excessive separation.
            H.discover();assert(require('CVP_Legacy').migrate(R))
            assert(S.graph.links[root.connection.id].length==length)
            run();assert(S.graph.links[root.connection.id].a.kind=='ground')
            assert(S.graph.links[tail.connection.id].a.kind=='body')
            assert(E.get(S.graph.links[root.connection.id].equipment)==rope)
        ''')

    def test_vehicle_teleport_drops_car_end_before_smoothed_anchor_moves_body(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain);run()
            local x,y=body.x,body2.x;car.x=30;run()
            assert(body.x==x and body2.x==y)
            assert(S.graph.links[root].a.kind=='ground' and S.graph.links[tail].a.kind=='body')
        ''')

    def test_selected_middle_body_release_keeps_tail_towing_without_return(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain);run()
            edit(tail,'release','a');local x=body2.x
            for i=1,20 do car.x=car.x+.06;run() end
            assert(body2.x>x and not S.index.byBody.A)
            assert(S.graph.links[tail].b.kind=='body' and S.graph.links[root].b.kind=='joint')
            assert(E.get(S.graph.links[tail].equipment)==chain and chain:getContainer()~=storage)
            intact(body);intact(body2)
        ''')

    def test_ground_release_uses_floor_height_not_vehicle_hitch_height(self):
        l = environment(); l.execute('''
            local id=link(C,A,rope);edit(id,'release','a')
            assert(S.graph.links[id].a.z==require('CVP_Rope').floorHeight)
        ''')

    def test_recovery_retries_periodically_without_stopping_unrelated_towing(self):
        # Compare identical scenarios: unrelated recovery must not suppress movement.
        control = environment(); control.execute('''
            link(C,A,rope);for i=1,120 do car.x=car.x+.01;run() end
            controlPosition=body.x
        ''')
        expected = control.globals().controlPosition
        l = environment(); l.globals().expectedPosition=expected; l.execute('''
            link(C,A,rope);local recover=E.recover;local attempts=0
            E.recover=function(p) attempts=attempts+1;return false,'pending unrelated transfer' end
            for i=1,120 do car.x=car.x+.01;run() end
            assert(attempts==2 and body.x>0 and math.abs(body.x-expectedPosition)<1e-8 and R.recoveryErrors[player])
            E.recover=recover;now=11000;run();assert(not R.recoveryErrors[player])
        ''')

    def test_full_thirty_two_body_chain_moves_and_disconnect_keeps_every_item(self):
        l = environment(); l.execute('''
            local all={body,body2};local ends={A,B};local items={rope,chain}
            local root=link(C,A,rope);link(A,B,chain)
            for i=3,32 do
                local b=corpse();b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
                b.getSquare=body.getSquare;b.setSquare=body.setSquare
                b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
                sq:addCorpse(b);move(b,-(i-1)*3,0)
                H.discover();local endpoint={kind='body',key=b.md.CVPBodyKey,point='feet'}
                local material=item('Base.Rope');storage:AddItem(material)
                link(ends[i-1],endpoint,material);all[i]=b;ends[i]=endpoint;items[i]=material
            end
            local native=CVPWorldNative.move;local writes={}
            CVPWorldNative.move=function(b,...)
                writes[b]=(writes[b] or 0)+1;return native(b,...)
            end
            -- Allow the 32-link chain to take up slack before checking its tail.
            for i=1,120 do
                writes={};car.x=car.x+.05;run()
                for _,b in ipairs(all) do assert((writes[b] or 0)<=1,'intermediate native pose write') end
            end
            assert(#Sim.groups==1 and #Sim.groups[1].records==32)
            assert(body.x>.1 and all[32].x>-92.99)
            local before={};for i,b in ipairs(all) do before[i]=b.x;intact(b) end
            edit(root,'release','a');car.x=car.x+2;run()
            local count=0;for _,row in pairs(S.graph.links) do
                count=count+1;assert(E.get(row.equipment):getContainer()~=storage)
            end;assert(count==32)
            for i,b in ipairs(all) do assert(b.x==before[i]);intact(b) end
        ''')

    def test_disconnect_death_and_seat_drop_held_end_even_with_unloaded_other_end(self):
        for event in ('disconnect', 'death', 'seat'):
            with self.subTest(event=event):
                l = environment(); l.globals().event = event
                l.execute('''
                    local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
                    body.sq=nil
                    if event=='death' then player.isDead=function() return true end
                    elseif event=='seat' then driving=true end
                    run(event=='disconnect' and {} or {player})
                    assert(S.graph.links[id].b.kind=='ground')
                    assert(E.get(S.graph.links[id].equipment)==rope and next(S.index.held)==nil)
                ''')

    def test_loaded_body_deletion_releases_its_ends_without_gear_refund(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain);run()
            body.sq:removeCorpse(body);run()
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint')
            assert(S.graph.links[tail].b.key=='B')
            assert(E.get(S.graph.links[root].equipment)==rope and E.get(S.graph.links[tail].equipment)==chain)
            assert(not body.world);intact(body2)
        ''')

    def test_chunk_unload_is_not_deletion_or_refund(self):
        l = environment(); l.execute('''
            local id=link(A,B,rope);run();body.sq=nil
            for i=1,30 do run() end
            assert(S.graph.links[id].a.kind=='body' and E.get(S.graph.links[id].equipment)==rope)
        ''')

    def test_failed_system_release_suspends_motion_and_retries_without_write_storm(self):
        l = environment(); l.execute('''
            local id=link(C,A,rope);run()
            body.md.CorpseTowingVehicleToken='other';equipmentWriteFailure=true
            local attempts=0;local write=CVPEquipmentPersistence.write
            CVPEquipmentPersistence.write=function(...) attempts=attempts+1;return write(...) end
            now=now+50;assert(not R:tick({player},.05))
            local x=body.x
            for i=1,30 do now=now+50;car.x=car.x+.1;assert(not R:tick({player},.05)) end
            assert(attempts==1 and body.x==x and E.get(S.graph.links[id].equipment)==rope)
            equipmentWriteFailure=false;now=now+5000;run()
            assert(S.graph.links[id].b.kind=='ground' and body.x==x)
        ''')

    def test_failed_upgrade_write_preserves_legacy_and_retry_completes_once(self):
        l = migration_environment(); l.execute('''
            local root,tail=legacy(3);equipmentWriteFailure=true
            assert(not R:tick({player},.05));assert(next(E.links().links)==nil)
            assert(body.md.CVPTether and body2.md.CVPTether and E.get(root.equipmentKey)==rope)
            equipmentWriteFailure=false;now=6000;run()
            local rows=0;for _ in pairs(S.graph.links) do rows=rows+1 end;assert(rows==2)
            assert(not body.md.CVPTether and not body2.md.CVPTether);intact(body);intact(body2)
        ''')

    def test_fresh_runtime_drops_old_hold_and_returns_saved_original_properties(self):
        first = environment(); first.execute('''
            rope.md.keep={nested='original'};linkID=link(A,B,rope)
            edit(linkID,'release','b');edit(linkID,'take','b');assert(R:save())
        ''')
        second = environment(plain(first.globals().equipmentDisk))
        second.globals().linkID = first.globals().linkID
        second.execute('''
            assert(S.graph.links[linkID].b.kind=='ground')
            local key=S.graph.links[linkID].equipment;local original=assert(E.get(key))
            assert(original.md.keep.nested=='original')
            edit(linkID,'remove','b')
            assert(original:getContainer()==storage and not E.get(key) and next(S.graph.links)==nil)
        ''')


if __name__ == '__main__':
    unittest.main()
