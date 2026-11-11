"""Real Lua ledger hand-off and item-owned rendering; no live game acceptance."""
from pathlib import Path
import unittest
from test_link_runtime import environment


def ground_scene(lua):
    lua.execute("package.preload.CVP_GroundRopeScene=assert(loadstring(...))",
                Path('CorpseProxyLab/42/media/lua/client/CVP_GroundRopeScene.lua').read_text())
    lua.execute('''
        function getNumActivePlayers() return 1 end
        drawn={};updates=0
        CVPFreeRopeScene={update=function(id,points) drawn[id]=points;updates=updates+1 end,
            remove=function(id) drawn[id]=nil end}
        Scene=require 'CVP_GroundRopeScene';Scene.scanned=true
    ''')


class GroundEquipmentTests(unittest.TestCase):
    def test_empty_scene_skips_ui_and_clears_hover_without_next(self):
        l=environment();ground_scene(l)
        l.execute('''
            next=nil
            PZAPI={ModOptions={getOptions=function() error('idle options read') end}}
            function getMouseX() error('idle mouse read') end
            function getNumActivePlayers() error('idle player scan') end
            Scene.hover={};drawn['ground:pickup-marker']={}
            Scene.tick();Scene.draw()
            assert(not Scene.hover and not drawn['ground:pickup-marker'])
        ''')

    def test_discovery_flushes_current_ground_pose_before_return_and_retries_failure(self):
        for server in (False, True):
            with self.subTest(server=server):
                l=environment();l.globals().serverMode=server
                l.execute('''
                    function isServer() return serverMode end
                    function sendRemoveItemFromContainer() end
                    function sendAddItemToContainer() end
                    local id=link(A,B,rope);run()
                    edit(id,'release','a');edit(id,'release','b')
                    local link=S.graph.links[id];local key=link.equipment
                    R.recovered[player]=now+10000
                    assert(E.hasFreeWork(S.graph,S.index))
                    link.a.x=12.25;link.a.y=7.25;link.b.x=13.25;link.b.y=7.25;S.dirty=true
                    local revision=S.persistedRevision
                    equipmentWriteFailure=true;assert(not R:discover({player}))
                    assert(not rope:getWorldItem() and E.get(key)==rope)
                    assert(S.dirty and S.persistedRevision==revision)
                    equipmentWriteFailure=false;assert(R:discover({player}))
                    local object=assert(rope:getWorldItem());local square=object:getSquare()
                    assert(square:getX()==12 and square:getY()==7,'returned stale persisted position')
                    assert(not next(S.graph.links));assert(R:discover({player}))
                    assert(rope:getWorldItem()==object and square:getWorldObjects():size()==1)
                    intact(body);intact(body2)
                ''')

    def test_free_original_is_a_vanilla_world_item_and_can_be_reused(self):
        for material in ('Base.Rope', 'Base.HeavyChain', 'Base.HeavyChain_Hook'):
            l=environment();l.globals().material=material
            l.execute('''
                gear=item(material);gear.md.marker='original';storage:AddItem(gear)
                id=link(A,B,gear);edit(id,'release','a');edit(id,'release','b')
                assert(not gear:getWorldItem());assert(E.dropFree());assert(S:refresh())
                assert(not next(S.graph.links));assert(gear:getWorldItem())
                local sq=gear:getWorldItem():getSquare()
                assert(sq:getWorldObjects():get(0):getItem()==gear and gear.md.marker=='original')
                local count=sq:getWorldObjects():size();assert(E.dropFree());assert(sq:getWorldObjects():size()==count)
                takeGround(gear,storage);assert(gear:getContainer()==storage)
                local other=link(A,B,gear);assert(S.graph.links[other] and not gear:getWorldItem())
            ''')

    def test_attached_and_held_ends_do_not_become_pickable(self):
        l=environment();l.execute('''
            id=link(A,B,rope);edit(id,'release','a');assert(E.dropFree());assert(E.get(S.graph.links[id].equipment)==rope)
            edit(id,'take','a');edit(id,'release','b');assert(E.dropFree());assert(not rope:getWorldItem())
            edit(id,'drop','a');assert(E.dropFree());assert(rope:getWorldItem())
        ''')

    def test_shared_spool_returns_once_only_after_entire_rope_is_free(self):
        l=environment();l.execute('''
            local a={kind='ground',x=0,y=0,z=0}
            local b={kind='body',key='A',point='feet',x=2,y=0,z=0}
            local c={kind='ground',x=4,y=0,z=0}
            key=assert(E.hold(rope,nil,{link={id='one',a=a,b=b,owner='player',shared=true}}))
            local g=E.links();local updated=assert(G.create(g,'two',b,c,key,'Base.Rope','player',32,true))
            assert(E.editLinks(updated,g.revision));assert(E.dropFree());assert(not rope:getWorldItem())
            g=E.links();updated=assert(G.unloadBody(g,'A',b,'player'))
            assert(E.editLinks(updated,g.revision));assert(E.dropFree())
            assert(not next(E.links().links) and rope:getWorldItem())
            assert(#rope.md.CVPGroundRope.parts==2 and rope:getWorldItem():getSquare():getWorldObjects():size()==1)
        ''')

    def test_extended_rope_returns_two_originals_with_disjoint_visual_halves(self):
        l=environment();l.execute('''
            id=link(A,B,rope);extra=item('Base.Rope');storage:AddItem(extra)
            assert(E.hold(extra,nil,{extend={id=id,revision=S.graph.links[id].revision,owner='player'}}))
            assert(S:refresh());edit(id,'release','a');edit(id,'release','b');assert(E.dropFree())
            assert(not next(E.links().links) and rope:getWorldItem() and extra:getWorldItem())
            assert(rope~=extra and rope.md.CVPGroundRope.parts[1][7]==9 and extra.md.CVPGroundRope.parts[1][6]==9)
        ''')

    def test_failed_checkpoint_then_restart_reconciles_the_same_world_item(self):
        l=environment();l.execute('''
            id=link(A,B,rope);edit(id,'release','a');edit(id,'release','b')
            equipmentCheckpointFailure=true;assert(not E.dropFree());assert(rope:getWorldItem())
            local original=rope:getWorldItem();local square=original:getSquare()
            local saved=serializeEquipment();loadEquipment(saved);E=require 'CVP_Equipment'
            equipmentCheckpointFailure=false;assert(E.dropFree())
            assert(not next(E.links().links) and rope:getWorldItem()==original and square:getWorldObjects():size()==1)
        ''')

    def test_failed_world_add_retains_original_for_retry(self):
        l=environment();l.execute('''
            id=link(A,B,rope);edit(id,'release','a');edit(id,'release','b')
            local link=E.links().links[id];local key=link.equipment
            local _,x,y,z=require('CVP_GroundRope').recipe(E.links(),G.index(E.links()),key)
            local sq=gridSquare(x,y,z);local add=sq.AddWorldInventoryItem
            sq.AddWorldInventoryItem=function() error('disk/world unavailable') end
            assert(not E.dropFree());assert(E.get(key)==rope and not rope:getWorldItem())
            sq.AddWorldInventoryItem=add;assert(E.dropFree());assert(rope:getWorldItem())
        ''')

    def test_extended_return_resumes_after_only_one_original_reached_the_world(self):
        l=environment();l.execute('''
            id=link(A,B,rope);extra=item('Base.Rope');storage:AddItem(extra)
            assert(E.hold(extra,nil,{extend={id=id,revision=S.graph.links[id].revision,owner='player'}}))
            assert(S:refresh());edit(id,'release','a');edit(id,'release','b')
            local old=E.release;local returns=0
            E.release=function(...) returns=returns+1;if returns==2 then return false,'interrupted' end;return old(...) end
            assert(not E.dropFree());E.release=old
            local saved=serializeEquipment();loadEquipment(saved);E=require 'CVP_Equipment'
            assert(E.dropFree());assert(not next(E.links().links))
            local found={};local total=0
            for _,q in pairs(grid) do for _,o in ipairs(q.ground) do
                local i=o:getItem();assert(not found[i:getID()]);found[i:getID()]=true;total=total+1
            end end
            assert(total==2 and found[rope:getID()] and found[extra:getID()])
        ''')

    def test_joint_connected_to_an_attached_other_rope_stays_bound(self):
        l=environment();l.execute('''
            local M=require 'CVP_GroundRope';local g=G.empty()
            local joint={kind='joint',key='join',x=2,y=0,z=0}
            g=assert(G.create(g,'free',{kind='ground',x=0,y=0,z=0},joint,'one','Base.Rope','player'))
            g=assert(G.create(g,'attached',joint,{kind='body',key='A',point='feet',x=4,y=0,z=0},'two','Base.Rope','player'))
            assert(not M.eligible(g,G.index(g),'one'))
        ''')

    def test_unloaded_ground_is_deferred_and_runtime_materializes_after_loading(self):
        l=environment();l.execute('''
            id=link(A,B,rope);edit(id,'release','a');edit(id,'release','b')
            unloaded=true;assert(E.dropFree());assert(not rope:getWorldItem())
            unloaded=false;run();assert(rope:getWorldItem() and not next(S.graph.links))
        ''')

    def test_scene_follows_item_pickup_chunk_reload_and_display_option(self):
        l=environment();ground_scene(l)
        l.execute('''
            id=link(A,B,rope);edit(id,'release','a');edit(id,'release','b');assert(E.dropFree())
            local square=rope:getWorldItem():getSquare();Scene.square(square);Scene.tick()
            assert(next(drawn));local count=updates;Scene.tick();assert(updates==count)
            local show=true
            PZAPI={ModOptions={getOptions=function() return {getOption=function() return {getValue=function() return show end} end} end}}
            show=false;Scene.tick();assert(not next(drawn));show=true;Scene.tick();assert(next(drawn))
            unloaded=true;Scene.tick();assert(not next(drawn))
            unloaded=false;Scene.square(square);Scene.tick();assert(next(drawn))
            takeGround(rope,storage);Scene.tick();assert(not next(drawn) and not next(Scene.items))
            square:AddWorldInventoryItem((function() storage:Remove(rope);return rope end)())
            Scene.added(rope:getWorldItem());Scene.tick();assert(next(drawn))
            takeGround(rope,storage);storage:Remove(rope);square:AddWorldInventoryItem(rope)
            Scene.added(rope:getWorldItem());Scene.tick();assert(next(drawn))
        ''')

    def test_shape_bounds_and_ground_height(self):
        l=environment();l.execute('''
            local M=require 'CVP_GroundRope'
            local recipe={version=1,parts={{0,0,4,0,12,1,17}}}
            local points=assert(M.points(recipe,100,200,2,'Base.Rope'))[1]
            assert(#points==17 and points[1].x==100 and points[17].x==104)
            for _,p in ipairs(points) do assert(math.abs(p.z-6.075)<.0001) end
            recipe.parts[1][1]=0/0;assert(not M.points(recipe,0,0,0,'Base.Rope'))
            recipe.parts[1][1]=0;recipe.parts[1][7]=100000;assert(not M.points(recipe,0,0,0,'Base.Rope'))
        ''')

    def test_ground_item_copy_renders_on_two_clients_without_loading_the_ledger(self):
        from test_link_multiplayer import vm
        from lua_fixture import copy_packet
        server=vm(True)
        server.execute('''
            id=link(A,B,rope)
            for _,side in ipairs({'a','b'}) do local row=S.graph.links[id];beside(row[side])
                assert(R:command(player,{op='release',id=id,revision=row.revision,side=side}))
            end
            now=now+2000;CVPMPServer.tick();assert(rope:getWorldItem() and not next(S.graph.links))
        ''')
        metadata=copy_packet(server.globals().rope.md)
        coords=[server.eval(f'rope:getWorldItem():getSquare():get{axis}()') for axis in ('X','Y','Z')]
        for who in ('owner','friend'):
            client=vm(False,who);ground_scene(client)
            client.globals().worldMetadata=client.table_from(metadata,recursive=True)
            client.globals().worldCoords=client.table_from(coords)
            client.execute('''
                local gear=item('Base.Rope');gear.md=worldMetadata
                local q=gridSquare(unpack(worldCoords));q:AddWorldInventoryItem(gear)
                Scene.added(gear:getWorldItem());Scene.tick();assert(next(drawn))
                assert(not package.loaded.CVP_Equipment,'client opened authoritative ledger')
                takeGround(gear,localPlayer:getInventory());Scene.tick();assert(not next(drawn))
            ''')

    def test_hover_hint_is_transient_and_marks_the_real_pickup_square(self):
        l=environment();ground_scene(l)
        l.execute('''
            id=link(A,B,rope);edit(id,'release','a');edit(id,'release','b');assert(E.dropFree())
            local square=rope:getWorldItem():getSquare();Scene.square(square);Scene.tick()
            CVPViewpoint=nil
            IsoUtils={XToScreen=function(x) return x*100 end,YToScreen=function(_,y) return y*100 end}
            IsoCamera={getOffX=function() return 0 end,getOffY=function() return 0 end,
                getScreenLeft=function() return 0 end,getScreenTop=function() return 0 end}
            function getCore() return {getZoom=function() return 1 end} end
            local first=next(Scene.items);local entry=Scene.items[first];local point=entry.curves[1][1]
            mx=point.x*100;my=point.y*100
            function getMouseX() return mx end;function getMouseY() return my end
            labels={};UIFont={Small='small'}
            function getTextManager() return {DrawStringCentre=function(_,font,x,y,text) labels[#labels+1]={x=x,y=y,text=text} end} end
            Scene.draw();assert(#labels==2 and labels[2].x==(square:getX()+.5)*100)
            assert(labels[2].text==getText('IGUI_CVP_GroundPickup',getText('IGUI_CVP_Rope')))
            assert(drawn['ground:pickup-marker'])
            local marker=drawn['ground:pickup-marker'];local submitted=updates
            for i=1,32 do Scene.draw() end
            assert(updates==submitted and drawn['ground:pickup-marker']==marker,'stationary hover rebuilt geometry')
            -- Projection still follows the camera without rebuilding world geometry.
            IsoCamera.getOffX=function() return 10 end;mx=mx-10;labels={};Scene.draw()
            assert(labels[2].x==(square:getX()+.5)*100-10 and updates==submitted)
            CVPViewpoint={active=function() return true end,
                project=function(x,y) px=x*100-10;py=y*100;return true end,
                screenX=function() return px end,screenY=function() return py end}
            labels={};Scene.draw();assert(#labels==2 and updates==submitted)
            CVPViewpoint=nil
            local savedNext=next;next=nil;CVPFeedback={previews={}}
            labels={};Scene.draw();assert(#labels==2,'Kahlua has no global next')
            CVPFeedback.previews[0]={};labels={};Scene.draw();assert(#labels==0)
            assert(not drawn['ground:pickup-marker'])
            next=savedNext;CVPFeedback=nil
            square.isCanSee=function() return false end;labels={};Scene.draw()
            assert(#labels==0 and not drawn['ground:pickup-marker'],'hidden pickup square must not be disclosed')
            square.isCanSee=function() return true end
            mx=100000;my=100000;labels={};Scene.draw();assert(#labels==0)
        ''')


if __name__ == '__main__':
    unittest.main()
