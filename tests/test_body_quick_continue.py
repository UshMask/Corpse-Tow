"""Body-click continuation uses the existing authoritative shared-rope queue."""
import unittest
from test_link_client import client
from test_link_multiplayer import Network

class BodyQuickContinueTests(unittest.TestCase):
    def test_start_at_body_then_reuse_rope_without_spare(self):
        l=client();l.execute("""
            menu(body);choose('IGUI_CVP_AttachCar');completeJob()
            local id,first=next(S.graph.links);assert(first.allocation)
            menu(body2)
            local main=assert(menuBranch(context,getText('IGUI_CVP_ContinueTrain')))
            assert(not main.notAvailable and not main.subMenu)
            main.onHighlight(main,{player=0},true)
            local preview=require('CVP_Feedback').previews[0]
            assert(preview.vehicle==car and #preview.bodies==2)
            main.run();completeJob()
            local count=0
            for _,row in pairs(S.graph.links) do
                count=count+1;assert(row.equipment==first.equipment)
                if row.id~=id then assert(row.a.key=='A' and row.b.key=='B') end
            end
            assert(count==2 and chain:getContainer()==storage)
            intact(body);intact(body2)
        """)

    def test_cancel_batch_then_continue_from_remaining_body(self):
        l=client();l.execute("""
            carMenu();choose('IGUI_CVP_TieNearestBodies')
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            local _,first=next(S.graph.links)
            local target=first.b.key=='A' and body2 or body
            menu(target);choose('IGUI_CVP_ContinueTrain');completeJob()
            local count=0;for _,r in pairs(S.graph.links) do count=count+1;assert(r.equipment==first.equipment) end
            assert(count==2 and chain:getContainer()==storage)
        """)

    def test_stale_choice_does_not_start_another_train(self):
        l=client();l.execute("""
            menu(body);choose('IGUI_CVP_AttachCar');completeJob()
            local id=next(S.graph.links);menu(body2)
            local opt=assert(menuBranch(context,getText('IGUI_CVP_ContinueTrain')))
            edit(id,'release','b');local revision=S.graph.revision
            opt.run();local job=completeJob()
            assert(job.feedback.reason=='IGUI_CVP_ConnectionChanged')
            assert(S.graph.revision==revision and chain:getContainer()==storage)
        """)

    def test_multiple_tails_require_choice(self):
        l=client();l.execute("""
            extra=item('Base.Rope');storage:AddItem(extra)
            CVPRuntime.actions:ropeBatch(player,C,{A});completeJob()
            local anchor=H.sample(C);move(body2,anchor.x+1,anchor.y)
            -- Explicitly create a separate shared root through the authority.
            player.x=anchor.x;player.y=anchor.y
            local token=assert(S:prepare(player,C,extra:getID(),true))
            assert(R:create(player,token,B))
            local b=corpse();b.netID='103';b.md.CVPBodyKey='third'
            b.getSquare=body.getSquare;b.setSquare=body.setSquare
            b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
            b.world=false;sq:addCorpse(b);move(b,anchor.x+2,anchor.y);H.discover()
            menu(b)
            local opt=assert(menuBranch(context,getText('IGUI_CVP_ContinueTrain')))
            assert(opt.subMenu and #opt.subMenu.children==2)
            opt.subMenu.children[2].run();completeJob()
            local tail
            for _,r in pairs(S.graph.links) do if r.b.key=='third' then tail=r end end
            assert(tail and tail.a.key=='B' and E.get(tail.equipment)==extra)
        """)

    def test_multiplayer_body_clicks_share_one_original(self):
        n=Network();s=n.server;c=n.clients['owner']
        c.execute("menu(body);choose('IGUI_CVP_AttachCar')");n.finish();n.publish()
        c.execute("menu(body2);choose('IGUI_CVP_ContinueTrain')");n.finish();n.publish()
        s.execute("""
            local count=0;local key
            for _,row in pairs(S.graph.links) do
                count=count+1;assert(row.allocation);assert(not key or key==row.equipment);key=row.equipment
            end
            assert(count==2 and require('CVP_Equipment').get(key)==rope and chain:getContainer()==storage)
        """)

    def test_continue_near_tail_when_vehicle_is_outside_menu_radius(self):
        l=client();l.execute("""
            local anchor=H.sample(C)
            move(body,anchor.x+11,anchor.y)
            CVPRuntime.actions:ropeBatch(player,C,{A});completeJob()
            move(body2,anchor.x+13,anchor.y)
            player.x=body2:getX();player.y=body2:getY()
            local extra=item('Base.Rope');storage:AddItem(extra)
            menu(body2)
            assert(menuBranch(context,getText('IGUI_CVP_ContinueTrain')),'continuation missing at distant tail')
            choose('IGUI_CVP_ContinueTrain');completeJob()
            local count=0;for _,r in pairs(S.graph.links) do count=count+1 end
            assert(count==2)
        """)

    def test_continuation_does_not_offer_tail_on_another_floor(self):
        l=client();l.execute("""
            menu(body);choose('IGUI_CVP_AttachCar');completeJob()
            body.z=1
            menu(body2)
            assert(not menuBranch(context,getText('IGUI_CVP_ContinueTrain')),'wrong-floor continuation offered')
        """)

    def test_cancel_during_continuation_leaves_existing_links_and_can_retry(self):
        l=client();l.execute("""
            menu(body);choose('IGUI_CVP_AttachCar');completeJob()
            local revision=S.graph.revision
            menu(body2);choose('IGUI_CVP_ContinueTrain')
            finishStage()
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            assert(S.graph.revision==revision)
            menu(body2);choose('IGUI_CVP_ContinueTrain');completeJob()
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end
            assert(count==2 and chain:getContainer()==storage)
        """)

    def test_vehicle_starts_moving_after_menu_no_material_spent(self):
        l=client();l.execute("""
            menu(body);choose('IGUI_CVP_AttachCar');completeJob()
            menu(body2);local opt=assert(menuBranch(context,getText('IGUI_CVP_ContinueTrain')))
            local revision=S.graph.revision
            car.getCurrentSpeedKmHour=function() return 20 end
            opt.run();local job=completeJob()
            assert(job.feedback.reason=='IGUI_CVP_StopVehicle')
            assert(S.graph.revision==revision and chain:getContainer()==storage)
        """)

    def test_continuation_hint_matches_remaining_length(self):
        for distance,expected in ((1,'IGUI_CVP_ContinueReuseHint'),(3,'IGUI_CVP_ContinueNewRopeHint')):
            with self.subTest(distance=distance):
                l=client();l.globals().gap=distance;l.globals().expected=expected
                l.execute("""
                    local anchor=H.sample(C);move(body,anchor.x+10,anchor.y)
                    CVPRuntime.actions:ropeBatch(player,C,{A});completeJob()
                    move(body2,anchor.x+10+gap,anchor.y);player.x=body2:getX();player.y=body2:getY()
                    extra=item('Base.Rope');storage:AddItem(extra)
                    menu(body2);local opt=assert(menuBranch(context,getText('IGUI_CVP_ContinueTrain')))
                    assert(opt.toolTip.description:find(getText(expected),1,true))
                    opt.run();completeJob()
                    assert((extra:getContainer()==storage)==(gap==1))
                """)
