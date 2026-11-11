"""Free endpoint curves reach the native world scene without gameplay mutation."""
from pathlib import Path
import unittest
from test_link_runtime import environment


def scene():
    l = environment()
    l.execute("package.preload['CVP_LinkPresentation']=assert(loadstring(...))",
              Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkPresentation.lua').read_text(encoding='utf-8-sig'))
    l.execute('''
        drawn={};removed={};vehicles={};drawCalls={};vehicleCalls={}
        function getNumActivePlayers() return 1 end
        function getSpecificPlayer() return player end
        CVPFreeRopeScene={update=function(id,points,chain) drawCalls[id]=(drawCalls[id] or 0)+1;drawn[id]={points=equipmentCopy(points),chain=chain} end,
            vehicle=function(id,car,first) vehicleCalls[id]=(vehicleCalls[id] or 0)+1;vehicles[id]={car=car,first=first} end,
            remove=function(id) drawn[id]=nil;removed[id]=true;vehicles[id]=nil end}
        installNativeRopeScene(CVPFreeRopeScene)
        Renderer=require('CVP_LinkPresentation').new(H)
        function render()
            local samples=H.samples(S.graph);assert(Renderer:update(S.graph,samples,.05))
            return samples
        end
        function endpoints(id,samples)
            local points=drawn[id].points;local a,b=points[1],points[#points]
            local first,last=samples[id].a,samples[id].b
            assert(math.abs(a.x-first.x)<1e-6 and math.abs(a.y-first.y)<1e-6 and math.abs(a.z-first.z*3)<1e-6)
            assert(math.abs(b.x-last.x)<1e-6 and math.abs(b.y-last.y)<1e-6 and math.abs(b.z-last.z*3)<1e-6)
        end
    ''')
    return l


class LinkPresentationTests(unittest.TestCase):
    def test_new_curve_remains_owned_after_vehicle_binding_failure(self):
        l=scene();l.execute('''
            local id=link(C,A,rope)
            CVPFreeRopeScene.vehicle=function() error('binding failure after upload') end
            assert(not pcall(render))
            assert(drawn[id] and Renderer.curves[id])
            Renderer:clear()
            assert(not drawn[id] and removed[id] and next(Renderer.curves)==nil)
        ''')

    def test_new_detail_remains_owned_after_partial_publication(self):
        l=scene();l.execute('''
            CVPVisualAttachment={}
            CVPFreeRopeScene.vehicle=function() error('detail binding failure') end
            local ref={kind='vehicle',key='sql:71',point='hitch'}
            local endpoint={x=2,y=0,z=0}
            local ok=pcall(Renderer.detail,Renderer,'binding:partial',{material='Base.Rope'},
                ref,endpoint,{},{{x=2,y=0}},car)
            assert(not ok and drawn['binding:partial'] and Renderer.details['binding:partial'])
            Renderer:clear();assert(not drawn['binding:partial'])
        ''')

    def test_carry_failure_keeps_release_owner(self):
        l=scene();l.execute('''
            local releases=0
            Renderer.host.players={holder=player}
            CVPVisualAttachment={hand=function(p,out) out.x=0;out.y=0;out.z=0;return true end,
                carry=function() error('carry failed after override') end,
                release=function(p) assert(p==player);releases=releases+1 end}
            local a={kind='held',holder='holder',x=0,y=0,z=0}
            local b={kind='ground',x=2,y=0,z=.025}
            local graph={links={held={id='held',a=a,b=b,length=4,material='Base.Rope'}}}
            assert(not pcall(Renderer.update,Renderer,graph,{held={a=a,b=b}},.05))
            assert(Renderer.held[player]);Renderer:clear();assert(releases==1)
        ''')

    def test_native_curve_receives_same_inputs_and_keeps_state_across_frames(self):
        l=scene();l.execute("""
            local Rope=require 'CVP_Rope'
            local states={};local calls=0
            CVPFreeRopeScene.shape=function(id,r,ax,ay,az,dt,chain)
                assert(not states[id] or states[id]==r)
                states[id]=r;calls=calls+1
                local points=Rope.shape(r,ax,ay,az,dt)
                CVPFreeRopeScene.update(id,points,chain)
            end
            local id=link(C,A,rope);local samples=render();endpoints(id,samples)
            local original=states[id];assert(calls==1 and original.ropeSegments==16 and original.ropePasses==8)
            car.x=car.x+.1;samples=render();endpoints(id,samples);assert(calls==2 and states[id]==original)
            Renderer:clear();states={};render();assert(states[id]~=original and calls==3)
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body)
        """)

    def test_binding_reuses_points_preserves_snapshot_and_retries_failure(self):
        l=scene();l.execute("""
            CVPVisualAttachment={}
            local ref={kind='body',point='feet'};local link={material='Base.Rope'}
            local players={{x=0,y=0}};local keep={}
            local function draw(x)
                keep={};Renderer:detail('k',link,ref,{x=x,y=0,z=.04},keep,players)
                Renderer.details=keep
            end
            draw(1);local state=keep.k;local points=state.points;local first=points[1]
            local snapshot=drawn.k.points
            draw(2);assert(keep.k==state and state.points==points and points[1]==first)
            assert(snapshot[1].x==.97 and drawn.k.points[1].x==1.97)
            local upload=CVPFreeRopeScene.update
            CVPFreeRopeScene.update=function() error('failed') end
            assert(not pcall(draw,3));assert(state.x==2 and state.uploadPending)
            CVPFreeRopeScene.update=upload
            draw(2);assert(not state.uploadPending and points[1].x==1.97)
            ref.kind='vehicle';draw(2);assert(#state.points==9)
            ref.kind='body';draw(2);assert(#state.points==2)
        """)

    def test_shared_body_pose_is_read_once_and_refreshes_next_update(self):
        l=scene();l.execute("""
            local reads=0;local position=4
            local b={getGrabLegsPosition=true,isAnimal=function() return false end,
                getX=function() reads=reads+1;return position end,
                getY=function() reads=reads+1;return 0 end,
                getZ=function() reads=reads+1;return 0 end}
            H.body=function() return b end
            local ref={kind='body',key='body',point='feet'}
            local ground={kind='ground',x=0,y=0,z=.04}
            local link={id='a',a=ground,b=ref,length=4,material='Base.Rope'}
            local second=equipmentCopy(link);second.id='b'
            local endpoint={kind='body',key='body',point='feet',x=5,y=0,z=.04}
            local samples={a={a=ground,b=endpoint},b={a=ground,b=endpoint}}
            local graph={links={a=link,b=second}}
            Renderer:update(graph,samples,.05);assert(reads==3)
            assert(endpoint.x==5 and endpoint.z==.04)
            position=6;Renderer:update(graph,samples,.05);assert(reads==6)
        """)

    def test_front_and_rear_points_reach_native_rope_and_binding(self):
        from test_vehicle_anchors import SETUP
        l=scene();l.execute(SETUP+"""
            CVPVisualAttachment={release=function() end}
            local calls={}
            CVPFreeRopeScene.vehicle=function(id,v,first,point) calls[id]={point=point,first=first} end
            local f=link(front,A,rope);local rear=link(C,B,chain)
            player.x=car.x;player.y=car.y;render()
            assert(calls[f].point=='front' and calls[rear].point=='hitch')
            local P=require 'CVP_LinkPresentation'
            assert(calls[P.bindingId(S.graph.links[f],'a')].point=='front')
            assert(calls[P.bindingId(S.graph.links[rear],'a')].point=='hitch')
        """)

    def test_completed_snapshot_matches_fresh_curve_after_free_end_moves(self):
        l=scene();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
            player.isDead=function() return true end
            local ok,err,points=R:samples(true);assert(ok,err)
            local row=S.graph.links[id];assert(row.b.kind=='ground')
            row.b.x=row.a.x+100;row.b.y=row.a.y
            ok,err,points=R:samples(true);assert(ok,err)
            local frame=require('CVP_SimulationFrame').capture(R.simulation,S.graph,{},now,0,1,H,points)
            row=S.graph.links[id] -- Maintenance commits a replacement graph.
            assert(frame.endpoints[id].b.x==row.b.x,'snapshot retained the pre-drag free end')
            assert(Renderer:update(S.graph,frame.endpoints,.05))
            local reused=equipmentCopy(drawn)
            local fresh=require('CVP_LinkPresentation').new(H)
            assert(fresh:update(S.graph,nil,.05))
            for key,curve in pairs(reused) do
                assert(#curve.points==#drawn[key].points)
                for i,p in ipairs(curve.points) do local q=drawn[key].points[i]
                    assert(p.x==q.x and p.y==q.y and p.z==q.z)
                end
            end
        ''')

    def test_empty_presentation_reuses_empty_state_and_clears_last_details(self):
        l=scene();l.execute('''
            next=nil
            local curves,details,held=Renderer.curves,Renderer.details,Renderer.held
            for i=1,100 do assert(Renderer:update({links={}},nil,.01)) end
            assert(Renderer.curves==curves and Renderer.details==details and Renderer.held==held)
            local releases=0
            CVPVisualAttachment={release=function(p) assert(p==player);releases=releases+1 end}
            Renderer.details.knot={};Renderer.held[player]=true
            Renderer:update({links={}},nil,.01);Renderer:update({links={}},nil,.01)
            assert(removed.knot and releases==1)
        ''')

    def test_sleeping_upload_skips_only_unchanged_and_retries_failure(self):
        l=scene();l.execute('''
            local a={kind='ground',x=0,y=0,z=.025}
            local b={kind='ground',x=2,y=0,z=.025}
            local row={id='sleep',a=a,b=b,length=4,material='Base.Rope'}
            local graph={links={sleep=row}};local samples={sleep={a=a,b=b}}
            for i=1,1000 do assert(Renderer:update(graph,samples,.05)) end
            assert(Renderer.curves.sleep.ropeSleeping)
            local calls=drawCalls.sleep;local old=drawn.sleep.points[1].x
            for i=1,30 do Renderer:update(graph,samples,.05) end
            assert(drawCalls.sleep==calls and not Renderer.curves.sleep.sent)
            a.x=a.x+2;b.x=b.x+2
            local update=CVPFreeRopeScene.update
            CVPFreeRopeScene.update=function() error('injected upload failure') end
            assert(not pcall(Renderer.update,Renderer,graph,samples,.05))
            assert(drawn.sleep.points[1].x==old and Renderer.curves.sleep.uploadPending)
            CVPFreeRopeScene.update=update;Renderer:update(graph,samples,.05)
            assert(drawCalls.sleep==calls+1 and drawn.sleep.points[1].x==old+2)
            assert(not Renderer.curves.sleep.uploadPending)
            row.material='Base.HeavyChain';Renderer:update(graph,samples,.05)
            assert(drawn.sleep.chain)
            local options={getOption=function(_,key) return {getValue=function() return key=='RopeQuality' and 2 or true end} end}
            PZAPI={ModOptions={getOptions=function() return options end}}
            Renderer:update(graph,samples,.05);assert(#drawn.sleep.points==9)
            Renderer:clear();Renderer:update(graph,samples,.05);assert(drawn.sleep)
        ''')

    def test_shared_hitch_survives_link_removal_and_clears_on_hide(self):
        l=scene();l.execute("""
            CVPVisualAttachment={release=function() end}
            local P=require 'CVP_LinkPresentation';local graph={links={}};local samples={}
            for i=1,32 do local id='rope'..i
                graph.links[id]={id=id,a=C,b={kind='ground'},length=4,material='Base.Rope'}
                samples[id]={a={kind='vehicle',key=C.key,x=player.x,y=player.y,z=.25},
                    b={kind='ground',x=player.x+4,y=player.y,z=.025}}
            end
            local binding=P.bindingId(graph.links.rope1,'a')
            Renderer:update(graph,samples,.05)
            local n=0;for _ in pairs(Renderer.details) do n=n+1 end
            assert(n==1 and drawCalls[binding]==1 and vehicles[binding].car==car)
            local binds=vehicleCalls.rope2
            for _,s in pairs(samples) do s.a.x=s.a.x+.1;s.b.x=s.b.x+.1 end
            Renderer:update(graph,samples,.05)
            assert(drawCalls[binding]==2 and vehicleCalls.rope2==binds)
            assert(vehicleCalls[binding]==1)
            graph.links.rope1=nil;samples.rope1=nil;Renderer:update(graph,samples,.05)
            assert(drawn[binding] and drawCalls[binding]==2 and not drawn.rope1)
            local replacement={};H.vehicle=function() return replacement end
            Renderer:update(graph,samples,.05)
            assert(vehicles[binding].car==replacement and vehicles.rope2.car==replacement)
            player.x=player.x+100;Renderer:update(graph,samples,.05);assert(not drawn[binding])
            player.x=player.x-100;Renderer:update(graph,samples,.05);assert(drawn[binding])
            PZAPI={ModOptions={getOptions=function() return {getOption=function()
                return {getValue=function() return false end} end} end}}
            Renderer:update(graph,samples,.05);assert(next(drawn)==nil and next(vehicles)==nil)
            PZAPI=nil;Renderer:update(graph,samples,.05);assert(drawn[binding])
            Renderer:update({links={}},nil,.05);assert(next(drawn)==nil)
        """)

    def test_shared_bindings_keep_vehicle_point_and_material_separate(self):
        l=scene();l.execute("""
            CVPVisualAttachment={release=function() end}
            local P=require 'CVP_LinkPresentation';local graph={links={}};local samples={}
            for i,material in ipairs({'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}) do
                local id='link'..i
                graph.links[id]={id=id,a={kind='ground'},b=C,length=4,material=material}
                samples[id]={a={kind='ground',x=player.x+4,y=player.y,z=.025},
                    b={kind='vehicle',key=C.key,x=player.x,y=player.y,z=.25}}
            end
            local ropeID=P.bindingId(graph.links.link1,'b');local chainID=P.bindingId(graph.links.link2,'b')
            assert(chainID==P.bindingId(graph.links.link3,'b') and ropeID~=chainID)
            Renderer:update(graph,samples,.05)
            assert(not drawn[ropeID].chain and drawn[chainID].chain and drawCalls[chainID]==1)
            assert(vehicles.link1.first==false and vehicles[ropeID].first==true)
            local ref=equipmentCopy(C);ref.point='front';graph.links.link1.b=ref
            assert(P.bindingId(graph.links.link1,'b')~=ropeID)
            ref.point=C.point;ref.key=C.key..'-other';assert(P.bindingId(graph.links.link1,'b')~=ropeID)
            graph.links.link2=nil;graph.links.link3=nil;Renderer:update(graph,samples,.05)
            assert(not drawn[chainID])
        """)

    def test_human_knot_and_rope_share_corrected_visual_endpoint(self):
        l=scene();l.execute("""
            local id=link(A,B,rope)
            body.getGrabLegsPosition=function() end
            body.isAnimal=function() return false end
            CVPVisualAttachment={release=function() end}
            function getNumActivePlayers() return 1 end;function getSpecificPlayer() return player end
            local samples=H.samples(S.graph);local original=equipmentCopy(samples)
            Renderer:update(S.graph,samples,.05)
            local p=drawn[id].points[1]
            assert(math.abs(p.x-(body.x+(original[id].a.x-body.x)*.75))<1e-6)
            assert(math.abs(p.z-(body:getZ()+.04)*3)<1e-6)
            local knot=drawn['binding:'..id..':a'].points
            assert(math.abs((knot[1].x+knot[2].x)/2-p.x)<1e-6 and knot[1].z==p.z)
            assert(samples[id].a.x==original[id].a.x and samples[id].a.z==original[id].a.z)
        """)

    def test_hand_is_visual_only_and_released_when_link_disappears(self):
        l=scene();l.execute('''
            H.players={owner=player};local carrying={};local handX=3
            CVPVisualAttachment={hand=function(p,out) out.x=handX;out.y=2;out.z=.4;return true end,
                carry=function(p,material) carrying[p]=material end,release=function(p) carrying[p]=nil end}
            local graph={links={held={id='held',a={kind='held',holder='owner'},b={kind='ground'},length=4,material='Base.Rope'}}}
            local samples={held={a={kind='held',holder='owner',x=0,y=0,z=.02},b={kind='ground',x=2,y=2,z=.02}}}
            assert(Renderer:update(graph,samples,.05));assert(carrying[player]=='Base.Rope')
            assert(drawn.held.points[1].x==3 and samples.held.a.x==0 and graph.links.held.length==4)
            handX=4;Renderer:update(graph,samples,.05);assert(drawn.held.points[1].x==4)
            Renderer:update({links={}},nil,.05);assert(not carrying[player] and not drawn.held)
        ''')

    def test_decorative_bindings_are_near_only_and_never_transfer_gear(self):
        l=scene();l.execute('''
            CVPVisualAttachment={release=function() end}
            function getNumActivePlayers() return 1 end;function getSpecificPlayer() return player end
            local id=link(A,B,rope);local original=E.get(S.graph.links[id].equipment)
            render();assert(drawn['binding:'..id..':a'] and drawn['binding:'..id..':b'])
            player.x=player.x+100;render();assert(not drawn['binding:'..id..':a'])
            assert(E.get(S.graph.links[id].equipment)==original)
            Renderer:clear();assert(next(drawn)==nil)
        ''')

    def test_both_ground_ends_still_render_without_any_body_or_vehicle(self):
        l = scene(); l.execute('''
            local id=link(A,B,rope);edit(id,'release','a');edit(id,'release','b')
            local gear=E.get(S.graph.links[id].equipment);local writes=equipmentWrites
            body.sq=nil;body2.sq=nil;car.getSquare=function() return nil end
            for i=1,10 do local samples=render();endpoints(id,samples) end
            assert(drawn[id] and not drawn[id].chain and E.get(S.graph.links[id].equipment)==gear)
            assert(equipmentWrites==writes and not body.sq and not body2.sq)
            Renderer:clear();assert(not drawn[id] and S.graph.links[id])
        ''')

    def test_each_attachment_orientation_and_material_uses_exact_world_endpoints(self):
        for reverse in (False, True):
            for material in ('Base.Rope', 'Base.HeavyChain', 'Base.HeavyChain_Hook'):
                with self.subTest(reverse=reverse, material=material):
                    l = scene(); l.globals().reverse = reverse; l.globals().material = material
                    l.execute('''
                        rope.t=material;local id=link(reverse and A or C,reverse and C or A,rope)
                        local samples=render();endpoints(id,samples)
                        assert(vehicles[id].car==car and vehicles[id].first==not reverse)
                        assert(drawn[id].chain==(material~='Base.Rope'))
                        local length=S.graph.links[id].length;local x=body.x
                        for i=1,5 do car.x=car.x+.1;samples=render();endpoints(id,samples) end
                        assert(body.x==x and S.graph.links[id].length==length);intact(body)
                    ''')

    def test_unload_hides_curve_and_reload_restores_it_without_gear_transfer(self):
        l = scene(); l.execute('''
            local id=link(A,B,rope);render();local square=body2.sq;body2.sq=nil
            render();assert(not drawn[id] and removed[id] and S.graph.links[id])
            body2.sq=square;local samples=render();endpoints(id,samples)
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body);intact(body2)
        ''')

    def test_releasing_car_keeps_curve_and_removes_render_anchor(self):
        l = scene(); l.execute('''
            local id=link(C,A,rope);render();assert(vehicles[id].car==car)
            edit(id,'release','a');local samples=render();endpoints(id,samples)
            assert(drawn[id] and not vehicles[id].car and S.graph.links[id].a.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body)
        ''')

    def test_removal_clears_render_but_preview_clear_never_returns_items(self):
        l = scene(); l.execute('''
            local id=link(A,B,rope);render();Renderer:clear()
            assert(E.get(S.graph.links[id].equipment)==rope and not drawn[id])
            render();edit(id,'remove','b');render()
            assert(not drawn[id] and rope:getContainer()==storage)
        ''')

    def test_server_does_not_allocate_or_submit_visual_curves(self):
        l = scene(); l.execute('''
            local id=link(A,B,rope);function isServer() return true end
            assert(Renderer:update(S.graph,H.samples(S.graph),.05))
            assert(next(drawn)==nil and next(Renderer.curves)==nil)
        ''')


if __name__ == '__main__':
    unittest.main()
