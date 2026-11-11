"""Existing equipment reconnects through the normal two-stage SP/MP command path."""
import unittest
from test_link_client import client
from test_link_actions import scene


class ReconnectTrainTests(unittest.TestCase):
    def test_free_end_preview_does_not_cross_car_into_an_independent_train(self):
        l=client();l.execute('''
            link(C,A,rope);link(C,B,chain)
            local extra=item('Base.Rope');storage:AddItem(extra)
            local id=link(A,{kind='ground',x=0,y=0,z=.025},extra)
            local e=S.graph.links[id].b;local square=gridSquare(math.floor(e.x),math.floor(e.y),0)
            options={};context.children={}
            callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return square end}},false)
            local opt=context.children[1];assert(opt.label==getText('IGUI_CVP_LinkTakeRope'))
            opt.onHighlight(opt,{player=0},true)
            local preview=require('CVP_Feedback').previews[0]
            assert(#preview.bodies==1 and preview.bodies[1]==body)
        ''')

    def test_picking_free_end_highlights_entire_body_train(self):
        l=client();l.execute('''
            link(A,B,rope);local id=link(C,A,chain);edit(id,'release','a')
            local e=S.graph.links[id].a;local square=gridSquare(math.floor(e.x),math.floor(e.y),0)
            options={};context.children={}
            callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return square end}},false)
            local opt=context.children[1];assert(opt.label==getText('IGUI_CVP_LinkTakeChain'))
            opt.onHighlight(opt,{player=0},true)
            local preview=require('CVP_Feedback').previews[0];local seen={}
            for _,b in ipairs(preview.bodies) do seen[b]=true end
            assert(seen[body] and seen[body2] and #preview.bodies==2)
        ''')

    def test_bare_rope_is_not_offered_as_a_body_train(self):
        l=client(); l.execute('''
            local id=link(C,A,chain);edit(id,'release','a');edit(id,'release','b')
            carMenu()
            assert(context.children[1].label~=getText('IGUI_CVP_ReconnectChoose'))
            for _,o in ipairs(options) do
                assert(o.label~=getText('IGUI_CVP_ReconnectTrain'))
                assert(o.label~=getText('IGUI_CVP_ReconnectChoose'))
            end
            assert(S.graph.links[id].a.kind=='ground' and S.graph.links[id].b.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==chain);intact(body)
        ''')

    def test_empty_tethers_do_not_hide_the_actual_train_in_car_menu(self):
        l=client(); l.execute('''
            local empty=link(C,A,chain);edit(empty,'release','a');edit(empty,'release','b')
            local train=link(C,B,rope);edit(train,'release','a')
            carMenu();assert(context.children[1].label==getText('IGUI_CVP_TieNearestBodies'))
            choose('IGUI_CVP_ReconnectTrain');completeJob()
            assert(S.graph.links[train].a.kind=='vehicle')
            assert(S.graph.links[empty].a.kind=='ground' and S.graph.links[empty].b.kind=='ground')
            local before=body2.x
            for i=1,50 do car.x=car.x+.04;now=now+50;callbacks.OnTick() end
            assert(body2.x>before+.1,'selected train did not resume towing')
            assert(not S.graph.links[empty] and chain:getWorldItem(),'fully free chain must become a floor item')
            assert(E.get(S.graph.links[train].equipment)==rope);intact(body);intact(body2)
        ''')

    def test_bare_end_can_still_be_attached_with_an_explicit_name(self):
        l=client(); l.execute('''
            local id=link(C,A,chain);edit(id,'release','a');edit(id,'release','b');edit(id,'take','a')
            carMenu()
            choose('IGUI_CVP_LinkBindLooseCar')
            completeJob()
            assert(S.graph.links[id].a.kind=='vehicle' and S.graph.links[id].b.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==chain);intact(body)
        ''')

    def test_reconnect_preview_includes_tail_and_stale_menu_cannot_take_changed_end(self):
        l=client(); l.execute('''
            link(A,B,rope);local id=link(C,A,chain);edit(id,'release','a');carMenu()
            local selected
            for _,o in ipairs(options) do if o.label==getText('IGUI_CVP_ReconnectTrain') then selected=o end end
            assert(selected);selected.onHighlight(selected,{player=0},true)
            local preview=require('CVP_Feedback').previews[0];assert(#preview.bodies==2)
            local found={};for _,b in ipairs(preview.bodies) do found[b]=true end
            assert(found[body] and found[body2])
            edit(id,'take','a');selected.run()
            assert(activeJob().finished and S.graph.links[id].a.kind=='held')
            assert(E.get(S.graph.links[id].equipment)==chain)
        ''')

    def test_existing_vehicle_component_cannot_be_reconnected_into_loop(self):
        l=client(); l.execute('''
            link(C,A,chain);local id=link(A,B,rope);edit(id,'release','b');carMenu()
            for _,o in ipairs(options) do if o.label==getText('IGUI_CVP_ReconnectTrain') then
                assert(o.notAvailable and o.toolTip and o.toolTip.description)
            end end
        ''')

    def test_single_train_is_primary_and_mass_attachment_remains_available(self):
        l=client(); l.execute('''
            local id=link(C,A,chain);edit(id,'release','a');local equipment=S.graph.links[id].equipment
            carMenu();assert(context.children[1].label==getText('IGUI_CVP_TieNearestBodies'))
            local mass=false
            for _,o in ipairs(options) do if o.label==getText('IGUI_CVP_TieNearestBodies') then mass=true end end
            assert(mass)
            choose('IGUI_CVP_ReconnectTrain');completeJob()
            assert(S.graph.links[id].a.kind=='vehicle' and S.graph.links[id].equipment==equipment)
            assert(E.get(equipment)==chain and rope:getContainer()==storage);intact(body)
        ''')

    def test_multiple_trains_require_choice_and_highlight_the_whole_selected_train(self):
        l=client(); l.execute('''
            local one=link(C,A,chain);local two=link(C,B,rope)
            edit(one,'release','a');edit(two,'release','a');carMenu()
            assert(context.children[1].label==getText('IGUI_CVP_ReconnectNearest'))
            local count=0
            for _,o in ipairs(options) do if o.label:find('Тел: ',1,true) or o.label:find('Bodies: ',1,true) then
                if o.label:find(getText('IGUI_CVP_Chain'),1,true) then
                    o.onHighlight(o,{player=0},true)
                    local preview=require('CVP_Feedback').previews[0]
                    assert(preview and #preview.bodies==1 and preview.bodies[1]==body)
                    o.run();completeJob();count=count+1
                end
            end end
            assert(count==1 and S.graph.links[one].a.kind=='vehicle' and S.graph.links[two].a.kind=='ground')
        ''')

    def test_reconnect_and_cancel_before_or_after_take_in_sp_and_mp(self):
        for mp in (False,True):
            for stage in ('before','after','finish'):
                with self.subTest(mp=mp,stage=stage):
                    l=scene(mp); l.globals().stage=stage
                    l.execute('''
                        local mode=clientMode;clientMode=false
                        local tail=link(A,B,rope);local id=link(C,A,chain);edit(id,'release','a')
                        local equipment=S.graph.links[id].equipment;local revision=S.graph.links[id].revision
                        clientMode=mode
                        local job=Actions:reconnect(player,id,revision,'a',C)
                        if stage~='before' then
                            while #requests==0 do finishStage() end
                            assert(S.graph.links[id].a.kind=='held')
                        end
                        if stage=='finish' then assert(finishJob(job));assert(S.graph.links[id].a.kind=='vehicle')
                        else
                            require('CVP_Feedback').cancel(player);Actions:update()
                            assert(job.finished and S.graph.links[id].a.kind==(stage=='before' and 'ground' or 'held'))
                        end
                        clientMode=false
                        assert(S.graph.links[id].equipment==equipment and E.get(equipment)==chain)
                        assert(E.get(S.graph.links[tail].equipment)==rope and chain:getContainer()~=storage)
                        intact(body);intact(body2)
                    ''')

    def test_vehicle_moving_after_pickup_stops_bind_and_preserves_held_end(self):
        l=scene(); l.execute('''
            local id=link(C,A,chain);edit(id,'release','a')
            local job=Actions:reconnect(player,id,S.graph.links[id].revision,'a',C)
            while #requests==0 do finishStage() end
            car.x=car.x+1;finishStage()
            assert(job.finished and #requests==1 and S.graph.links[id].a.kind=='held')
            assert(E.get(S.graph.links[id].equipment)==chain)
        ''')

    def test_cancel_waiting_for_mp_take_reply_never_sends_bind(self):
        l=scene(True); l.execute('''
            clientMode=false;local id=link(C,A,chain);edit(id,'release','a');clientMode=true
            deferReply=true
            local job=Actions:reconnect(player,id,S.graph.links[id].revision,'a',C)
            while #requests==0 do finishStage() end
            requests[1]:execute();assert(S.graph.links[id].a.kind=='held')
            require('CVP_Feedback').cancel(player);Actions:update();requests[1]:reply()
            assert(job.finished and #requests==1 and S.graph.links[id].a.kind=='held')
            clientMode=false;assert(E.get(S.graph.links[id].equipment)==chain)
        ''')


if __name__=='__main__':
    unittest.main()
