"""Straight-segment collision, authoritative pause/resume and MP feedback."""
import unittest
from test_link_simulation import environment


WORLD = '''
    O=require 'CVP_LinkObstacles'
    nativeQueries=0;tileQueries=0;wallX=nil;wallY=nil;missingX=nil;solidX=nil
    local read=cell.getGridSquare
    cell.getGridSquare=function(s,x,y,z)
        tileQueries=tileQueries+1
        if missingX==x then return nil end
        local q=read(s,x,y,z);if not q then return end
        q.tx=x;q.ty=y
        q.isSolid=function() return solidX==x end
        q.isBlockedTo=function(a,b)
            nativeQueries=nativeQueries+1
            return wallX and ((a.tx<wallX)~=(b.tx<wallX))
                or wallY and ((a.ty<wallY)~=(b.ty<wallY)) or false
        end
        return q
    end
    function pos(x,y,z) return {x=x,y=y or .5,z=z or 0} end
'''


class LinkObstacleTests(unittest.TestCase):
    def test_same_endpoint_tiles_do_not_cache_a_blocked_ray_as_the_whole_rectangle(self):
        l=environment();l.execute(WORLD);l.execute('''
            local read=cell.getGridSquare
            cell.getGridSquare=function(s,x,y,z)
                local q=read(s,x,y,z)
                q.isBlockedTo=function(a,b)
                    return a.ty==0 and b.ty==0 and ((a.tx==0 and b.tx==1) or (a.tx==1 and b.tx==0))
                end
                return q
            end
            local c=O.new()
            assert(O.check(c,pos(.1,.1),pos(1.9,1.9))==O.blocked)
            assert(not O.check(c,pos(.1,.9),pos(1.1,1.9)),'different ray in same rectangle must remain open')
            assert(O.check(c,pos(.1,.1),pos(1.9,1.9))==O.blocked)
        ''')

    def test_obstacle_outside_actual_ray_does_not_block_it(self):
        l=environment();l.execute(WORLD);l.execute('''
            local read=cell.getGridSquare
            cell.getGridSquare=function(s,x,y,z)
                if x==0 and y==1 then return nil end
                return read(s,x,y,z)
            end
            local c=O.new()
            assert(not O.check(c,pos(.2,.2),pos(2.8,1.2)),'failed rectangle proof must fall back to the actual ray')
            assert(O.check(c,pos(.2,.2),pos(.2,1.2))==O.unloaded)
        ''')

    def test_full_segment_in_both_directions_and_negative_coordinates(self):
        l=environment();l.execute(WORLD);l.execute('''
            local a,b=pos(-5.2,.4),pos(6.7,.4)
            assert(not O.check(O.new(),a,b));wallX=2
            assert(O.check(O.new(),a,b)==O.blocked and O.check(O.new(),b,a)==O.blocked)
            wallX=-2;assert(O.check(O.new(),a,b)==O.blocked)
            wallX=nil;wallY=-1
            assert(O.check(O.new(),pos(.4,-5.2),pos(.4,6.7))==O.blocked)
            assert(not O.check(O.new(),pos(.4,2),pos(.4,5)))
        ''')

    def test_corner_supercover_and_zero_length_boundaries(self):
        l=environment();l.execute(WORLD);l.execute('''
            wallX=1
            assert(O.check(O.new(),pos(.5,.5),pos(1.5,1.5))==O.blocked)
            assert(O.check(O.new(),pos(1.5,1.5),pos(.5,.5))==O.blocked)
            assert(O.check(O.new(),pos(1,1),pos(.5,.5))==O.blocked)
            assert(not O.check(O.new(),pos(1,1),pos(1,1)))
            wallX=nil;wallY=1
            assert(O.check(O.new(),pos(.5,.5),pos(1.5,1.5))==O.blocked)
        ''')

    def test_floor_unloaded_and_solid_intermediate_tiles_fail_closed(self):
        l=environment();l.execute(WORLD);l.execute('''
            local a,b=pos(.5),pos(12.5)
            missingX=6;assert(O.check(O.new(),a,b)==O.unloaded)
            missingX=nil;solidX=6;assert(O.check(O.new(),a,b)==O.blocked)
            solidX=nil;assert(not O.check(O.new(),a,b))
            assert(O.check(O.new(),a,pos(2,.5,1))==O.blocked)
            assert(O.check(O.new(),a,pos(10000))==O.blocked and tileQueries<100)
        ''')

    def test_native_queries_cached_per_tick_and_door_rechecked_next_tick(self):
        l=environment();l.execute(WORLD);l.execute('''
            local a,b=pos(.2,.2),pos(24.1,12.3);local cache=O.new()
            assert(not O.check(cache,a,b));local calls=nativeQueries;local tiles=tileQueries
            for i=1,120 do assert(not O.check(cache,a,b)) end
            assert(nativeQueries==calls and tileQueries==tiles and calls<=96 and tiles<=49)
            wallX=8;assert(O.check(O.new(),a,b)==O.blocked)
            wallX=nil;assert(not O.check(O.new(),a,b))
        ''')

    def test_create_rejects_wall_before_item_transfer_and_retries_when_open(self):
        l=environment();l.execute(WORLD);l.execute('''
            move(body2,5,.5);move(body,0,.5)
            beside(A);local token=assert(S:prepare(player,A,rope.id));beside(B);wallX=2
            local ok,why=S:create(player,token,B)
            assert(not ok and why==O.blocked and rope:getContainer()==storage and not next(S.graph.links))
            wallX=nil;assert(S:create(player,token,B));intact(body);intact(body2)
        ''')

    def test_bind_rejects_wall_without_losing_carried_end(self):
        l=environment();l.execute(WORLD);l.execute('''
            move(body2,5,.5);move(body,0,.5);local id=link(A,B,rope)
            edit(id,'release','b');edit(id,'take','b');wallX=2;beside(B)
            local row=S.graph.links[id];local rev=row.revision
            local ok,why=S:command(player,{id=id,revision=rev,side='b',op='bind',target=B})
            assert(not ok and why==O.blocked and S.graph.links[id].revision==rev)
            assert(S.graph.links[id].b.kind=='held' and E.get(row.equipment)==rope)
            wallX=nil;edit(id,'bind','b',B);assert(S.graph.links[id].b.kind=='body')
        ''')

    def test_blocked_train_stays_still_keeps_gear_and_resumes(self):
        l=environment();l.execute(WORLD);l.execute('''
            move(body2,-5,.5);move(body,0,.5)
            local root=link(C,A,rope);local tail=link(A,B,chain);wallX=-2
            local x,y=body.x,body2.x;car.x=car.x+1
            for i=1,10 do local requests,loads=step();assert(#requests==0 and not next(loads)) end
            assert(body.x==x and body2.x==y and Sim.obstacles[root]==O.blocked and Sim.obstacles[tail]==O.blocked)
            assert(Sim.records[root].blocked and not Sim.records[root].taut)
            assert(E.get(S.graph.links[root].equipment)==rope and E.get(S.graph.links[tail].equipment)==chain)
            wallX=nil;for i=1,20 do step() end
            assert(not next(Sim.obstacles) and body.x>x+.01 and body2.x>y+.01)
            intact(body);intact(body2)
        ''')

    def test_unloaded_path_pauses_without_graph_edits_and_recovers(self):
        l=environment();l.execute(WORLD);l.execute('''
            car.x=8;local root=link(C,A,rope);local revision=S.graph.links[root].revision
            local x=body.x;missingX=4;car.x=car.x+.8;step()
            assert(body.x==x and Sim.obstacles[root]==O.unloaded and S.graph.links[root].revision==revision)
            missingX=nil;for i=1,15 do step() end
            assert(not Sim.obstacles[root] and body.x>x+.01);intact(body)
        ''')

    def test_independent_vehicle_root_keeps_moving_when_other_root_is_blocked(self):
        l=environment();l.execute(WORLD);l.execute('''
            move(body2,-5,.5);local stuck=link(C,B,chain);local clear=link(C,A,rope)
            wallX=-2;local x,y=body.x,body2.x
            for i=1,20 do car.x=car.x+.03;step() end
            assert(body.x>x+.01 and body2.x==y and Sim.obstacles[stuck] and not Sim.obstacles[clear])
            intact(body);intact(body2)
        ''')

    def test_candidate_attachment_pose_cannot_cross_wall_before_world_move(self):
        l=environment();l.execute(WORLD);l.execute('''
            local id=link(C,A,rope);step();local r=Sim.records[id];local x,y,angle=body.x,body.y,body.angle
            local Rope=require 'CVP_Rope';local Geometry=require 'CVP_Geometry'
            Rope.step=function() return 5,.5,true end
            Geometry.resolve=function(_,x,y,a) return x,y,a,false end
            wallX=2;r.ax=0;r.ay=.5
            require('CVP_Core').advance(r,0,.5,0,.01,O.new())
            assert(r.ropeBlocked==O.blocked and body.x==x and body.y==y and body.angle==angle)
            assert(r.vx==0 and r.vy==0 and not r.taut);intact(body)
        ''')

    def test_sp_menu_explains_obstruction_and_keeps_remove_available(self):
        from test_link_client import client
        l=client();l.execute(WORLD);l.execute('''
            car.x=8;local id=link(C,A,rope);wallX=4
            now=now+50;assert(R:tick({player},.05));menu(body)
            local found=false
            for _,o in ipairs(options) do if o.label==getText(O.blocked) then found=true;assert(o.notAvailable) end end
            assert(found);choose('IGUI_CVP_LinkRemoveRope');completeJob()
            assert(not next(S.graph.links) and rope:getContainer()==storage);intact(body)
        ''')

    def test_two_clients_receive_pause_reason_and_clear_it_when_path_opens(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server;s.execute(WORLD)
        s.execute('car.x=8;id=link(C,A,rope);wallX=4;now=now+50;assert(R:tick({player},.05))')
        n.publish()
        for c in n.clients.values():
            c.execute('''
                local id=next(CVPMPClient.graph.links)
                assert(CVPMPClient.obstacles[id]=='IGUI_CVP_LinkBlocked')
                menu(body);local found=false
                for _,o in ipairs(options) do if o.label==getText('IGUI_CVP_LinkBlocked') then found=true;assert(o.notAvailable) end end
                assert(found)
            ''')
        s.execute('wallX=nil;now=now+50;assert(R:tick({player},.05))');n.publish()
        for c in n.clients.values():c.execute('assert(not next(CVPMPClient.obstacles))')

    def test_door_closing_during_rewire_keeps_old_layout_and_allows_retry(self):
        from test_link_runtime import environment as runtime
        from test_link_graph import plain
        l=runtime();l.execute(WORLD);l.execute('''
            first=link(C,A,rope);second=link(C,B,chain);beside(C)
            plan=assert(R:prepareRewire(player,C));before=equipmentCopy(S.graph)
            for i=2,#plan.steps-1 do beside(plan.steps[i]);assert(R:visitRewire(player,plan.token)) end
            wallX=-1;beside(plan.steps[#plan.steps]);local ok,why=R:visitRewire(player,plan.token)
            assert(not ok and why==O.blocked)
        ''')
        self.assertEqual(plain(l.globals().before),plain(l.globals().S.graph))
        l.execute('''
            wallX=nil;assert(R:visitRewire(player,plan.token));assert(S.graph.links[second].a.kind=='body')
            assert(E.get(S.graph.links[first].equipment)==rope and E.get(S.graph.links[second].equipment)==chain)
        ''')

    def test_extended_rope_obstacle_survives_fresh_vm_save_load(self):
        from test_link_runtime import environment as runtime
        from test_link_graph import plain
        l=runtime();l.execute(WORLD);l.execute('''
            id=link(C,A,rope);extra=item('Base.Rope');extra.md={personal='extra'};storage:AddItem(extra)
            beside(A);assert(R:command(player,{id=id,revision=S.graph.links[id].revision,side='b',op='extend',gear=extra.id}))
            car.x=20;wallX=10;run();assert(Sim.obstacles[id]==O.blocked);assert(R:save())
            assert(S.graph.links[id].extension)
        ''')
        restored=runtime(plain(l.globals().equipmentDisk));restored.execute(WORLD);restored.execute('''
            car.x=20;wallX=10;local id,row=next(S.graph.links);local key=row.equipment;local extra=row.extension
            local x=body.x;run();assert(Sim.obstacles[id]==O.blocked and body.x==x)
            assert(E.get(extra).md.personal=='extra' and E.get(key).id~=E.get(extra).id)
            wallX=nil;for i=1,20 do run() end
            assert(body.x>x+.01 and not Sim.obstacles[id] and S.graph.links[id].extension==extra)
            intact(body)
        ''')

    def test_one_eight_thirty_two_bodies_pause_at_varied_tick_rates(self):
        for count in (1,8,32):
            for fps in (15,60,144):
                with self.subTest(count=count,fps=fps):
                    l=environment();l.execute(WORLD);l.globals().count=count;l.globals().fps=fps
                    l.execute('''
                        car.x=6;local root=link(C,A,rope);local last=A
                        for i=2,count do
                            local b=i==2 and body2 or corpse()
                            if i>2 then
                                b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
                                b.getSquare=body.getSquare;b.setSquare=body.setSquare
                                b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
                                sq:addCorpse(b);move(b,-(i-1)*3,0)
                            end
                            H.discover();local ref={kind='body',key=b.md.CVPBodyKey,point='feet'}
                            local gear=item('Base.Rope');storage:AddItem(gear);link(last,ref,gear);last=ref
                        end
                        local before={};for i=1,count do before[i]=bodies[i].x end
                        wallX=3;car.x=car.x+.5
                        for i=1,fps do
                            local requests,loads=Sim:tick(S.graph,S.index,1/fps,now+i*1000/fps)
                            assert(#requests==0 and not next(loads) and Sim.obstacles[root]==O.blocked)
                        end
                        for i=1,count do assert(bodies[i].x==before[i]);intact(bodies[i]) end
                        wallX=nil
                        for i=1,fps do Sim:tick(S.graph,S.index,1/fps,now+1000+i*1000/fps) end
                        assert(not next(Sim.obstacles) and body.x>before[1]+.01)
                        for i=1,count do intact(bodies[i]) end
                    ''')

    def test_invalid_mp_obstacle_does_not_replace_a_good_snapshot(self):
        from test_link_multiplayer import Network,take
        from test_link_graph import plain
        for mode in ('unknown-link','unknown-reason'):
            n=Network();s=n.server;c=n.clients['owner'];s.execute('link(C,A,rope)');n.publish()
            before=plain(c.globals().CVPMPClient.graph)
            s.execute('publish()');page=next(p for p in take(s,'packets') if p['who']=='owner')
            id=next(iter(before['links']))
            page['args']['obstacles']={('missing' if mode=='unknown-link' else id):
                                      ('IGUI_CVP_LinkBlocked' if mode=='unknown-link' else 'arbitrary text')}
            n.receive(page)
            self.assertEqual(before,plain(c.globals().CVPMPClient.graph))
            self.assertFalse(plain(c.globals().CVPMPClient.obstacles))


if __name__=='__main__':unittest.main()
