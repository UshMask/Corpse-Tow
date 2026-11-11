"""Player-facing menu structure, backed by real actions and authority."""
import unittest
from test_link_client import client
from test_horse_towing import install_horse


class MenuModelTests(unittest.TestCase):
    def tractor(self, horse):
        l=install_horse(client()) if horse else client()
        l.execute("""
            function rootOption(key)
                local o=menuBranch(context,getText(key));assert(o,'missing root action: '..key)
                assert(not o.subMenu);return o
            end
        """)
        if horse:
            l.execute("""
                tractor=T
                function openTractor()
                    ISWorldObjectContextMenu.fetchVars={clickedAnimals={horse}}
                    menu({})
                end
            """)
        else:
            l.execute('tractor=C;openTractor=carMenu')
        return l

    def test_same_primary_actions_for_both_tractors_and_no_nested_duplicates(self):
        for horse in (False, True):
            with self.subTest(horse=horse):
                l=self.tractor(horse);l.execute("""
                    openTractor();rootOption('IGUI_CVP_TieNearestBodies').run();completeJob()
                    openTractor();local detach=rootOption(tractor.kind=='horse' and 'IGUI_CVP_DetachFromHorse' or 'IGUI_CVP_DetachFromCar')
                    assert(detach.toolTip.description==getText('IGUI_CVP_DetachFromHint'))
                    local more=assert(menuBranch(context,getText('IGUI_CVP_MoreActions'))).subMenu
                    assert(not menuBranch(more,getText('IGUI_CVP_PointMenu')))
                    for _,material in ipairs({'IGUI_CVP_Rope','IGUI_CVP_Chain','IGUI_CVP_HookChain'}) do
                        assert(not menuBranch(more,getText('IGUI_CVP_MaterialMenu',getText(material))))
                    end
                    assert(not menuBranch(more,getText('IGUI_CVP_DetachCargo')))
                    assert(not menuBranch(more,getText('IGUI_CVP_TieNearestBodies')))
                    assert(menuBranch(more,getText('IGUI_CVP_DismantleAll')))
                    detach.onHighlight(detach,{player=0},true)
                    local preview=require('CVP_Feedback').previews[0]
                    assert(#preview.bodies==2)
                    for _,e in ipairs(preview.endpoints or {}) do
                        assert(type(e.x)=='number' and type(e.y)=='number' and type(e.z)=='number','preview must contain world coordinates')
                    end
                    detach.run();completeJob()
                    local roots=0
                    for _,row in pairs(S.graph.links) do
                        if row.a.kind=='ground' then roots=roots+1 end
                        assert(row.a.kind~='horse' and row.a.kind~='vehicle')
                    end
                    assert(roots==1 and rope:getContainer()~=storage)
                    intact(body);intact(body2)
                """)

    def test_add_action_and_empty_scene_for_both_tractors(self):
        for horse in (False, True):
            with self.subTest(horse=horse):
                l=self.tractor(horse);l.execute("""
                    link(tractor,A,rope);openTractor()
                    local add=rootOption('IGUI_CVP_AddNearestBodies')
                    assert(not menuBranch(context,getText('IGUI_CVP_TieNearestBodies')))
                    add.onHighlight(add,{player=0},true)
                    local preview=require('CVP_Feedback').previews[0]
                    assert(#preview.bodies==1 and preview.bodies[1]==body2)
                    add.run();completeJob();openTractor()
                    assert(not menuBranch(context,getText('IGUI_CVP_AddNearestBodies')))
                    assert(not menuBranch(context,getText('IGUI_CVP_TieNearestBodies')))
                    assert(menuBranch(context,getText('IGUI_CVP_DetachTrainChoose')).subMenu)
                """)

    def test_chain_fallback_and_disabled_horse_explain_the_actual_reason(self):
        for horse in (False, True):
            with self.subTest(horse=horse):
                l=self.tractor(horse);l.execute("""
                    player.md.CVPMaterial='Base.Rope';storage:Remove(rope)
                    openTractor();rootOption('IGUI_CVP_TieNearestBodies').run();completeJob()
                    local _,row=next(S.graph.links);assert(E.get(row.equipment)==chain)
                """)
        l=self.tractor(True);l.execute("""
            SandboxVars.CorpseProxyLab.HorseTowing=false;openTractor()
            local o=rootOption('IGUI_CVP_TieNearestBodies')
            assert(o.notAvailable and o.toolTip.description==getText('IGUI_CVP_HorseDisabled'))
            assert(not next(S.graph.links) and rope:getContainer()==storage)
        """)

    def test_held_end_has_direct_bind_and_drop_without_consuming_new_material(self):
        for horse in (False, True):
            with self.subTest(horse=horse):
                l=self.tractor(horse);l.execute("""
                    local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
                    openTractor();rootOption('IGUI_CVP_DropHeldRope')
                    local label=getText(tractor.kind=='horse' and 'IGUI_CVP_LinkBindHorse' or 'IGUI_CVP_LinkBindCar')
                    local bind=assert(menuBranch(context,label));assert(not bind.notAvailable)
                    bind.run();completeJob();assert(S.graph.links[id].b.kind==tractor.kind)
                    assert(chain:getContainer()==storage)
                """)

    def test_cargo_release_counts_detached_roots_and_keeps_equipment(self):
        for horse in (False, True):
            with self.subTest(horse=horse):
                l=self.tractor(horse);l.execute("""
                    link(tractor,A,rope);link(tractor,B,chain);openTractor()
                    local choices=assert(menuBranch(context,getText('IGUI_CVP_DetachTrainChoose'))).subMenu
                    local all=assert(menuBranch(choices,getText('IGUI_CVP_DetachCargo')))
                    all.run();local job=completeJob()
                    assert(job.feedback.kind=='cargo' and job.feedback.done==2)
                    for _,row in pairs(S.graph.links) do assert(row.a.kind=='ground') end
                    assert(E.get(S.graph.links[next(S.graph.links)].equipment))
                """)

    def test_body_can_be_detached_directly_while_holding_its_rope(self):
        l=self.tractor(False);l.execute("""
            local id=link(A,B,rope);edit(id,'release','b');edit(id,'take','b')
            menu(body);rootOption('IGUI_CVP_DetachBody').run();completeJob()
            assert(S.graph.links[id].a.kind=='ground' and S.graph.links[id].b.kind=='held')
            intact(body);assert(E.get(S.graph.links[id].equipment)==rope)
        """)

    def test_multiple_loads_have_direct_reconnect_for_both_tractors(self):
        for horse in (False, True):
            with self.subTest(horse=horse):
                l=self.tractor(horse);l.execute("""
                    local one=link(tractor,A,rope);local two=link(tractor,B,chain)
                    edit(one,'release','a');edit(two,'release','a');openTractor()
                    local direct=rootOption('IGUI_CVP_ReconnectNearest')
                    direct.onHighlight(direct,{player=0},true)
                    assert(#require('CVP_Feedback').previews[0].bodies==1)
                    assert(not menuBranch(context,getText('IGUI_CVP_ReconnectChoose')))
                    direct.run();completeJob()
                    local attached=0
                    for _,row in pairs(S.graph.links) do
                        if row.a.kind==tractor.kind then attached=attached+1 end
                    end
                    assert(attached==1 and rope:getContainer()~=storage and chain:getContainer()~=storage)
                """)

    def test_horse_reconnects_existing_load_without_new_equipment(self):
        l=self.tractor(True);l.execute("""
            local id=link(T,A,rope);edit(id,'release','a');openTractor()
            pickedVehicle=car
            openTractor()
            local o=rootOption('IGUI_CVP_ReconnectHorse');o.onHighlight(o,{player=0},true)
            o.run();local job=completeJob();assert(S.graph.links[id].a.kind=='horse')
            assert(job.feedback.done==1 and job.feedback.kind=='reconnect')
            assert(context.children[1].label==getText('IGUI_CVP_TieNearestBodies'))
            assert(chain:getContainer()==storage and rope:getContainer()~=storage)
        """)


if __name__=='__main__':unittest.main()
