"""Focused context routing through existing authority/queues; no live UI claims."""
import unittest
from test_link_client import client
from test_link_multiplayer import Network


class FocusedMenuTests(unittest.TestCase):
    def test_end_body_menu_explains_free_end_without_returning_material(self):
        l=client();l.execute('''
            local id=link(C,A,rope);menu(body)
            local release=assert(menuBranch(context,getText('IGUI_CVP_DetachBody')))
            assert(release.toolTip.description==getText('IGUI_CVP_DetachBodyHint'))
            release.run();completeJob()
            assert(S.graph.links[id].a.kind=='vehicle' and S.graph.links[id].b.kind=='ground')
            assert(rope:getContainer()~=storage);intact(body)
        ''')

    def test_multiple_selected_bodies_offer_their_own_detach_action(self):
        l=client();l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain)
            options={};context.children={};callbacks.OnFillWorldObjectContextMenu(0,context,{body,body2},false)
            local middle,edge,middleOption=0,0,nil
            for _,opt in ipairs(options) do
                if opt.label==getText('IGUI_CVP_DetachBodyMiddle') then middle=middle+1;middleOption=opt end
                if opt.label==getText('IGUI_CVP_DetachBody') then edge=edge+1 end
                assert(opt.label~=getText('IGUI_CVP_LinkRelease'))
            end
            assert(middle==1 and edge==1)
            middleOption.onHighlight(middleOption,{player=0},true)
            assert(require('CVP_Feedback').previews[0].bodies[1]==body)
            middleOption.run();completeJob()
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint')
            assert(S.graph.links[tail].b.key=='B' and rope:getContainer()~=storage and chain:getContainer()~=storage)
            intact(body);intact(body2)
        ''')

    def test_middle_body_menu_explains_and_preserves_continuous_tether(self):
        l=client();l.execute("""
            local ropeId=link(A,B,rope);local chainId=link(B,C,chain);menu(body2)
            local release=assert(menuBranch(context,getText('IGUI_CVP_DetachBodyMiddle')))
            assert(release.toolTip.description==getText('IGUI_CVP_DetachBodyMiddleHint'))
            assert(not menuBranch(context,getText('IGUI_CVP_LinkRelease')))
            local ropeOption,chainOption
            for _,opt in ipairs(options) do
                if opt.label==getText('IGUI_CVP_LinkRemoveRope') then ropeOption=opt end
                if opt.label==getText('IGUI_CVP_LinkRemoveChain') then chainOption=opt end
            end
            assert(ropeOption and chainOption)
            release.run();completeJob()
            assert(S.graph.links[ropeId].b.kind=='joint' and S.graph.links[chainId].a.kind=='joint')
            assert(S.graph.links[ropeId].b.key==S.graph.links[chainId].a.key)
            assert(rope:getContainer()~=storage and chain:getContainer()~=storage)
            intact(body);intact(body2)
        """)

    def test_existing_loose_end_keeps_new_vehicle_link_out_of_quick_actions(self):
        l=client();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');menu(body2)
            assert(menuBranch(context,getText('IGUI_CVP_ReconnectBody')))
            assert(not menuBranch(context,getText('IGUI_CVP_AttachCar')))
            local more=assert(menuBranch(context,getText('IGUI_CVP_MoreActions'))).subMenu
            local fresh=assert(menuBranch(more,getText('IGUI_CVP_AttachCar')))
            assert(fresh.toolTip.description:find(getText('IGUI_CVP_NewMaterialHint',getText('IGUI_CVP_Chain')),1,true))
            choose('IGUI_CVP_ReconnectBody');completeJob()
            assert(S.graph.links[id].b.key=='B' and chain:getContainer()==storage)
        ''')

    def test_shared_segment_remove_hint_counts_other_segments(self):
        l=client();l.execute('''
            carMenu();choose('IGUI_CVP_TieNearestBodies');completeJob();menu(body2)
            local found=false
            for _,opt in ipairs(options) do if opt.label==getText('IGUI_CVP_LinkRemoveRopeSection') then
                found=true;assert(opt.toolTip.description==getText('IGUI_CVP_RemoveSharedHint','1'))
            end end
            assert(found)
        ''')

    def test_methods_live_inside_mod_menu_and_stale_end_explains_refresh(self):
        l=client();l.execute('''
            carMenu()
            local more=assert(menuBranch(context,getText('IGUI_CVP_MoreActions'))).subMenu
            local methods=assert(menuBranch(more,getText('IGUI_CVP_AttachMethods'))).subMenu
            assert(menuBranch(methods,getText('IGUI_CVP_SharedMethod')))
            assert(not menuBranch(more,getText('IGUI_CVP_TieSeparateTrains')))
            assert(menuBranch(methods,getText('IGUI_CVP_TieSeparateTrains')))
            local id=link(A,B,rope);menu(body);edit(id,'release','b')
            choose('IGUI_CVP_DetachBody');local job=completeJob()
            assert(job.feedback.reason=='IGUI_CVP_ConnectionChanged')
        ''')

    def test_held_end_menu_shows_state_and_length_even_when_target_is_blocked(self):
        l=client();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
            menu(body)
            local held,blocked=false,false
            for _,opt in ipairs(options) do
                if opt.label==getText('IGUI_CVP_DropHeldRope') then
                    held=true;assert(opt.toolTip.description==getText('IGUI_CVP_HeldRopeHint'))
                elseif opt.label==getText('IGUI_CVP_LinkBindBody') then
                    blocked=true;assert(opt.notAvailable)
                    assert(opt.toolTip.description:find(getText('IGUI_CVP_LinkLoop'),1,true))
                    assert(opt.toolTip.description:find(getText('IGUI_CVP_LengthHint','0.0','12.0'),1,true))
                end
            end
            assert(held and blocked)
            menu(body2)
            for _,opt in ipairs(options) do if opt.label==getText('IGUI_CVP_LinkBindBody') then
                assert(not opt.notAvailable and opt.toolTip.description)
            end end
        ''')

    def test_reconnect_full_body_is_visible_with_reason(self):
        l=client();l.execute('''
            local extra=item('Base.Rope');storage:AddItem(extra)
            local id=link(C,B,extra);edit(id,'release','b')
            link(C,A,rope);link(A,B,chain);menu(body)
            local found=false
            for _,opt in ipairs(options) do if opt.label==getText('IGUI_CVP_ReconnectBody') then
                found=true;assert(opt.notAvailable)
                assert(opt.toolTip.description:find(getText('IGUI_CVP_LinkFullBody'),1,true))
            end end
            assert(found)
        ''')

    def test_body_reconnect_reuses_ground_end_from_body_or_car(self):
        for source in ('A', 'C'):
            l=client();l.globals().source=source;l.execute('''
                local id=link(source=='A' and A or C,B,rope)
                edit(id,'release','b');menu(body2)
                choose('IGUI_CVP_ReconnectBody');completeJob()
                assert(S.graph.links[id].b.key=='B' and S.graph.links[id].a.kind==(source=='A' and 'body' or 'vehicle'))
                local count=0;for _ in pairs(S.graph.links) do count=count+1 end
                assert(count==1 and chain:getContainer()==storage and rope:getContainer()~=storage)
                intact(body);intact(body2)
            ''')

    def test_body_reconnect_explains_loop_without_allowing_it(self):
        l=client();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');menu(body)
            local found=false
            for _,opt in ipairs(options) do if opt.label==getText('IGUI_CVP_ReconnectBody') then
                found=true;assert(opt.notAvailable and opt.toolTip.description:find(getText('IGUI_CVP_LinkLoop'),1,true))
            end end
            assert(found)
        ''')

    def test_multiplayer_body_reconnect_preserves_original_equipment(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute("id=link(C,B,rope)")
        n.publish()
        c.execute("menu(body2);choose('IGUI_CVP_DetachBody')");n.finish();n.publish()
        c.execute("menu(body2);choose('IGUI_CVP_ReconnectBody')");n.finish();n.publish()
        s.execute('''
            local row=S.graph.links[id];assert(row.a.kind=='vehicle' and row.b.key=='B')
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end
            assert(count==1 and rope:getContainer()~=storage and chain:getContainer()==storage)
        ''')

    def test_multiplayer_middle_body_detach_keeps_links_and_materials(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute('root=link(C,A,chain);tail=link(A,B,rope)');n.publish()
        c.execute("menu(body);choose('IGUI_CVP_DetachBodyMiddle')");n.finish();n.publish()
        s.execute('''
            assert(S.graph.links[root].a.kind=='vehicle' and S.graph.links[root].b.kind=='joint')
            assert(S.graph.links[tail].a.kind=='joint' and S.graph.links[tail].b.key=='B')
            assert(S.graph.links[root].b.key==S.graph.links[tail].a.key)
            assert(rope:getContainer()~=storage and chain:getContainer()~=storage)
            for _,b in ipairs({body,body2}) do
                assert(b.world and b.inv:getItems():size()==1 and b.inv:getItems():get(0):getFullType()=='Base.Watch')
            end
        ''')


    def test_projected_roof_and_sides_do_not_pick_adjacent_ground(self):
        l=client();l.execute('''
            local sx,sy
            CVPViewpoint={active=function() return true end,
                project=function(x,y,z) sx=x;sy=y-z;return true end,
                screenX=function() return sx end,screenY=function() return sy end}
            car.getScript=function() return {getExtents=function()
                return {x=function() return 2 end,y=function() return 2.44949 end,z=function() return 4 end}
            end} end
            car.getWorldPos=function(_,x,y,z,out)
                out.x=function() return x end;out.y=function() return z end
            end
            local Menu=require('CVP_Menu')
            assert(Menu.vehicleScreenHit(car,0,-2.5))
            assert(Menu.vehicleScreenHit(car,0,1.5))
            assert(not Menu.vehicleScreenHit(car,1.1,-2.5))
            assert(not Menu.vehicleScreenHit(car,0,-3.1))
        ''')

    def test_viewpoint_roof_fallback_requires_actual_vehicle_contour(self):
        l=client();l.execute('''
            Viewpoint={Mouse={worldX=function() return 1 end,worldY=function() return 2 end}}
            car.getPoly=function() return {containsPoint=function(_,x,y) return x==1 and y==2 end} end
            local Menu=require('CVP_Menu')
            assert(Menu.viewpointVehicle(player)==car)
            assert(Menu.begin(player,context,{},true).vehicle==car)
            Viewpoint.Mouse.worldX=function() return 3 end
            assert(Menu.viewpointVehicle(player)==nil)
            Viewpoint.Mouse.worldX=function() return nil end
            assert(Menu.viewpointVehicle(player)==nil)
            Viewpoint.Mouse.worldX=function() return 1 end
            car.z=1;assert(Menu.viewpointVehicle(player)==nil)
        ''')

    def test_vehicle_choice_orders_by_player_distance_and_preserves_selected_chain(self):
        l=client();l.execute('''
            local old=link(A,B,rope);local saved=equipmentCopy(S.graph.links[old])
            local extra=item('Base.Rope');storage:AddItem(extra)
            local far={};for k,v in pairs(car) do far[k]=v end;far.md={};far.x=8;far.y=0
            far.getId=function() return 99 end;far.getSqlId=function() return 99 end
            cell.getVehicles=function() return {iterator=function() local rows={far,car};local i=0
                return {hasNext=function() return i<2 end,next=function() i=i+1;return rows[i] end} end} end
            player.x=8;player.y=0;menu(body2)
            local main=context.children[1];assert(main.subMenu and #main.subMenu.children==2)
            assert(menuBranch(context,getText('IGUI_CVP_MoreActions')))
            main.subMenu.children[1].onHighlight(main.subMenu.children[1],{player=0},true)
            assert(require('CVP_Feedback').previews[0].vehicle==far)
            local choice=main.subMenu.children[2]
            choice.onHighlight(choice,{player=0},true)
            local preview=require('CVP_Feedback').previews[0];assert(preview.bodies[1]==body2 and preview.vehicle==car)
            choice.run();completeJob()
            local count=0;for id,row in pairs(S.graph.links) do
                count=count+1
                if id~=old then assert(row.a.key=='B' and row.b.kind=='vehicle' and E.get(row.equipment)==extra) end
            end
            assert(count==2 and S.graph.links[old].revision==saved.revision and E.get(saved.equipment)==rope)
            intact(body);intact(body2)
        ''')

    def test_missing_preferred_material_falls_back_and_names_actual_material(self):
        l=client();l.execute(''' 
            player.md.CVPMaterial='Base.Rope';storage:Remove(rope);menu(body)
            local main=context.children[1]
            assert(not main.notAvailable)
            main.run();completeJob();local _,row=next(S.graph.links)
            assert(E.get(row.equipment)==chain and player.md.CVPMaterial=='Base.Rope')
        ''')

    def test_one_material_is_automatic_without_material_submenu(self):
        l=client();l.execute('''
            storage:Remove(rope);menu(body)
            assert(not context.children[1].notAvailable)
            local more=context.children[2].subMenu
            assert(not menuBranch(more,getText('IGUI_CVP_MaterialMenu',getText('IGUI_CVP_Chain'))))
        ''')

    def test_held_end_primary_binds_existing_connection_not_new_equipment(self):
        l=client();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
            menu(body2);local main=context.children[1]
            assert(main.label==getText('IGUI_CVP_LinkBindBody'))
            main.run();completeJob();assert(S.graph.links[id].b.key=='B' and chain:getContainer()==storage)
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1)
        ''')

    def test_detach_body_leaves_continuous_tether_without_refunding(self):
        l=client();l.execute('''
            local tail=link(A,B,rope);local root=link(C,A,chain);menu(body)
            local main=context.children[1]
            assert(main.label==getText('IGUI_CVP_DetachBodyMiddle') and not main.subMenu)
            main.onHighlight(main,{player=0},true)
            assert(require('CVP_Feedback').previews[0].bodies[1]==body)
            main.run();completeJob()
            assert(S.graph.links[tail].a.kind=='joint' and S.graph.links[tail].b.key=='B')
            assert(S.graph.links[root].a.kind=='vehicle' and S.graph.links[root].b.kind=='joint')
            assert(rope:getContainer()~=storage and chain:getContainer()~=storage)
            intact(body);intact(body2)
        ''')

    def test_ground_click_has_no_nearby_body_list_and_only_clicked_square_ends(self):
        l=client();l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');local e=S.graph.links[id].b
            local sq=getCell():getGridSquare(math.floor(e.x),math.floor(e.y),0)
            local function ground(square)
                options={};context.children={};callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return square end}},false)
            end
            ground(gridSquare(100,100,0));assert(#context.children==0)
            ground(sq);assert(context.children[1].label==getText('IGUI_CVP_LinkTakeRope'))
            for _,opt in ipairs(options) do assert(not opt.label:find(getText('IGUI_CVP_BodyMenu','1'),1,true)) end
            context.children[1].run();completeJob();assert(S.graph.links[id].b.kind=='held')
        ''')

    def test_cancel_primary_preserves_items_and_graph(self):
        l=client();l.execute('''
            menu(body);context.children[1].run();local job=activeJob()
            require('CVP_Feedback').cancel(player);callbacks.OnTick()
            assert(job.finished and not next(S.graph.links))
            assert(rope:getContainer()==storage and chain:getContainer()==storage);intact(body)
        ''')

    def test_selected_attachment_point_reaches_authority(self):
        l=client();l.execute('''
            menu(body);local more=context.children[2].subMenu
            assert(not menuBranch(more,getText('IGUI_CVP_PointMenu')))
            PZAPI={ModOptions={getOptions=function() return {getOption=function(_,id)
                return {getValue=function() return id=='AttachmentPoint' and 3 or true end}
            end} end}}
            menu(body)
            context.children[1].run();completeJob();local _,row=next(S.graph.links);assert((row.a.kind=='body' and row.a or row.b).point=='neck')
        ''')

    def test_multiple_loose_ends_require_selection_and_highlight_selected_end(self):
        l=client();l.execute('''
            local a=link(C,A,rope);local b=link(C,B,chain);edit(a,'release','a');edit(b,'release','a')
            local e=S.graph.links[a].a;local sq=getCell():getGridSquare(math.floor(e.x),math.floor(e.y),0)
            options={};context.children={};callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return sq end}},false)
            local main=context.children[1];assert(main.label==getText('IGUI_CVP_ChooseLoose') and #main.subMenu.children==2)
            local choice=main.subMenu.children[1];choice.onHighlight(choice,{player=0},true)
            local preview=require('CVP_Feedback').previews[0]
            assert(#preview.bodies==1 and (preview.bodies[1]==body or preview.bodies[1]==body2))
            local found=false;for _,p in ipairs(preview.endpoints) do
                if p.x==e.x and p.y==e.y then found=true end
            end;assert(found,'selected loose end must remain highlighted')
            assert(not choice.subMenu);choice.run();completeJob()
            local ground,held=0,0
            for _,row in pairs(S.graph.links) do if row.a.kind=='ground' then ground=ground+1 elseif row.a.kind=='held' then held=held+1 end end
            assert(ground==1 and held==1 and rope:getContainer()~=storage and chain:getContainer()~=storage)
        ''')

    def test_explicit_other_body_choice_is_lazy_and_executes_existing_action(self):
        l=client();l.execute('''
            menu(body);local more=context.children[2].subMenu
            local choice=assert(menuBranch(more,getText('IGUI_CVP_LinkOtherBody')))
            assert(#choice.subMenu.children==0);choice.onHighlight(choice,more,true)
            assert(#choice.subMenu.children==1);local opt=choice.subMenu.children[1]
            opt.onHighlight(opt,{player=0},true);assert(#require('CVP_Feedback').previews[0].bodies==2)
            opt.run();completeJob();local _,row=next(S.graph.links);assert(row.a.key=='A' and row.b.key=='B')
        ''')

    def test_moved_target_during_primary_approach_keeps_inventory(self):
        l=client();l.execute('''
            menu(body);context.children[1].run();local job=activeJob()
            body.x=body.x+1.1;assert(finishJob(job) and job.feedback.reason=='IGUI_CVP_BodyMoved');assert(not next(S.graph.links))
            assert(rope:getContainer()==storage and chain:getContainer()==storage)
        ''')

    def test_mp_cancel_primary_does_not_send_mutation(self):
        n=Network();c=n.clients['owner']
        c.execute('menu(body);context.children[1].run();require("CVP_Feedback").cancel(player);CVPMPClient.tick()')
        n.pump()
        n.server.execute('assert(not next(S.graph.links) and rope:getContainer()==storage and chain:getContainer()==storage)')

    def test_mp_primary_adds_car_without_replacing_body_chain(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute('old=link(A,B,rope);lootA=body:getContainer():getItems():get(0);lootB=body2:getContainer():getItems():get(0)');n.publish()
        c.execute('menu(body2);assert(not context.children[1].notAvailable);context.children[1].run()')
        n.finish();n.publish()
        s.execute('''
            assert(S.graph.links[old].a.key=='A' and S.graph.links[old].b.key=='B')
            local count=0;for id,row in pairs(S.graph.links) do count=count+1;if id~=old then assert(row.a.key=='B' and row.b.kind=='vehicle' and require('CVP_Equipment').get(row.equipment)==chain) end end
            assert(count==2 and body:getSquare() and body2:getSquare())
            assert(body:getContainer():getItems():get(0)==lootA and body2:getContainer():getItems():get(0)==lootB)
        ''')
        for peer in n.clients.values():
            self.assertEqual(peer.globals().equipmentWrites,0)


if __name__=='__main__':unittest.main()
