"""Vehicle alternatives use actual menus, queues and SP/MP authority handlers."""
import unittest
from test_link_client import client
from test_link_multiplayer import Network


class TrainMenuTests(unittest.TestCase):
    def test_parallel_and_sequential_hints_explain_their_actual_routes(self):
        l=client();l.execute('''
            carMenu();local parallel,sequence
            for _,opt in ipairs(options) do
                if opt.label==getText('IGUI_CVP_QuickNearby',getText('IGUI_CVP_Rope'),'1') then parallel=opt end
                if opt.label==getText('IGUI_CVP_QuickSequence',getText('IGUI_CVP_Rope'),'1') then sequence=opt end
            end
            assert(parallel and not parallel.notAvailable and parallel.toolTip.description==getText('IGUI_CVP_QuickNearbyHint'))
            assert(sequence and not sequence.notAvailable and sequence.toolTip.description==getText('IGUI_CVP_QuickSequenceHint'))
            driving=true;carMenu();parallel=nil
            for _,opt in ipairs(options) do
                if opt.label==getText('IGUI_CVP_QuickNearby',getText('IGUI_CVP_Rope'),'1') then parallel=opt end
            end
            assert(parallel and parallel.notAvailable and parallel.toolTip.description==getText('IGUI_CVP_LeaveVehicle'))
        ''')

    def test_unloaded_body_still_counts_in_its_own_menu_branch(self):
        l=client();l.execute('''            link(C,A,rope);link(C,B,chain)
            body2.sq=nil;H.discover();carMenu()
            local choices={}
            for _,opt in ipairs(options) do
                for i=1,2 do if opt.label==getText('IGUI_CVP_TrainChoice',tostring(i),'1') then choices[i]=opt end end
            end
            assert(choices[1] and choices[2],'unloaded body must not become an empty or merged train')
            assert(rope:getContainer()~=storage and chain:getContainer()~=storage)
        ''')

    def test_grouped_menu_starts_each_new_rope_at_vehicle(self):
        for mode in ('IGUI_CVP_SharedMethod', 'IGUI_CVP_TieSeparateTrains', 'IGUI_CVP_TieNearestBodies'):
            l=client();l.globals().mode=mode;l.execute('''
                extra=item('Base.Rope');storage:AddItem(extra)
                local at=H.sample(C);move(body,at.x+7,at.y);move(body2,at.x,at.y+7)
                carMenu();choose(mode);completeJob()
                local n,roots=0,0;local keys={}
                for _,r in pairs(S.graph.links) do n=n+1;keys[r.equipment]=true;if r.a.kind=='vehicle' then roots=roots+1 end end
                assert(n==2 and roots==(mode=='IGUI_CVP_SharedMethod' and 1 or 2));local originals=0;for _ in pairs(keys) do originals=originals+1 end
                assert(originals==2 and chain:getContainer()==storage);intact(body);intact(body2)
            ''')

    def test_alternatives_are_inside_mod_menu_and_main_action_unchanged(self):
        l=client();l.execute('''
            carMenu();local primary=0
            for _,o in ipairs(context.children) do
                if o.label==getText('IGUI_CVP_TieNearestBodies') then primary=primary+1 end
                assert(o.label~=getText('IGUI_CVP_TieSeparateTrains'))
                assert(o.label~=getText('IGUI_CVP_QuickNearby',getText('IGUI_CVP_Rope'),'1'))
            end
            assert(primary==1)
            choose('IGUI_CVP_TieSeparateTrains');completeJob()
            local n=0;local key;for _,r in pairs(S.graph.links) do n=n+1;assert(not key or key==r.equipment);key=r.equipment end
            assert(n==2 and E.get(key)==rope)
            carMenu();local opt=choose('IGUI_CVP_DetachFromCar')
            opt.onHighlight(opt,{player=0},true)
            assert(#require('CVP_Feedback').previews[0].bodies==2)
            completeJob();assert(rope:getContainer()~=storage)
        ''')

    def test_grouped_chain_limit_starts_an_independent_root(self):
        l=client();l.execute('''
            extra=item('Base.Rope');storage:AddItem(extra)
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1
            carMenu();choose('IGUI_CVP_TieSeparateTrains');completeJob()
            local n=0;for _,r in pairs(S.graph.links) do n=n+1;assert(r.a.kind=='vehicle') end
            assert(n==2 and chain:getContainer()==storage)
        ''')

    def test_selected_train_highlight_and_detach_preserve_other_root(self):
        l=client();l.execute('''
            first=link(C,A,rope);second=link(C,B,chain);carMenu()
            local opt=choose('IGUI_CVP_TrainChoice','1','1')
            opt.onHighlight(opt,{player=0},true)
            local preview=require('CVP_Feedback').previews[0];assert(#preview.bodies==1)
            local selected=preview.bodies[1];completeJob()
            local detached=0
            for _,r in pairs(S.graph.links) do
                if r.a.kind=='ground' then detached=detached+1;assert(H.body(r.b)==selected) end
            end
            assert(detached==1 and rope:getContainer()~=storage and chain:getContainer()~=storage)
            intact(body);intact(body2)
        ''')

    def test_detach_all_preserves_items_and_each_train(self):
        l=client();l.execute('''
            link(C,A,rope);link(C,B,chain);carMenu();choose('IGUI_CVP_DetachCargo');completeJob()
            local n=0;for _,r in pairs(S.graph.links) do n=n+1;assert(r.a.kind=='ground' and r.b.kind=='body') end
            assert(n==2 and rope:getContainer()~=storage and chain:getContainer()~=storage)
            intact(body);intact(body2)
        ''')

    def test_cancel_dismantle_shared_train_keeps_root_and_returns_original_once(self):
        l=client();l.execute('''
            carMenu();choose('IGUI_CVP_TieNearestBodies');completeJob()
            carMenu();choose('IGUI_CVP_DismantleAll')
            local function count() local n=0;for _ in pairs(S.graph.links) do n=n+1 end;return n end
            while count()==2 do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            assert(count()==1 and rope:getContainer()~=storage)
            for _,r in pairs(S.graph.links) do assert(r.a.kind=='vehicle') end
            carMenu();choose('IGUI_CVP_DismantleAll');completeJob()
            assert(count()==0 and rope:getContainer()==storage and storage:getItems():size()==2)
            intact(body);intact(body2)
        ''')

    def test_stale_dismantle_menu_stops_without_consuming_items(self):
        l=client();l.execute('''
            local root=link(C,A,rope);carMenu()
            edit(root,'release','a');choose('IGUI_CVP_DismantleAll');completeJob()
            assert(S.graph.links[root] and rope:getContainer()~=storage);intact(body)
        ''')

    def test_multiplayer_grouped_menu_and_full_dismantle_return_two_originals(self):
        n=Network();s=n.server;c=n.clients['owner']
        for vm in (s,*n.clients.values()):
            vm.execute('''
                extra=item('Base.Rope');storage:AddItem(extra)
                local host=serverMode and H or CVPMPClient.host
                local at=host.sample({kind='vehicle',native=17,point='hitch'})
                World.move(body,at.x+7,at.y,0,gridSquare(math.floor(at.x+7),math.floor(at.y),0))
                World.move(body2,at.x,at.y+7,0,gridSquare(math.floor(at.x),math.floor(at.y+7),0));host.discover()
            ''')
        c.execute("carMenu();choose('IGUI_CVP_TieNearestBodies')");n.finish();n.publish()
        s.execute("local n=0;for _,r in pairs(S.graph.links) do n=n+1;assert(r.a.kind=='vehicle') end;assert(n==2)")
        c.execute("carMenu();choose('IGUI_CVP_DismantleAll')");n.finish();n.publish()
        s.execute("assert(not next(S.graph.links) and rope:getContainer()==storage and extra:getContainer()==storage and chain:getContainer()==storage)")
        c.execute("assert(storage:getItems():size()==3 and storage:getItemWithID(rope.id) and storage:getItemWithID(extra.id))")

    def test_grouped_cancel_preserves_first_train_and_spare_in_sp_and_mp(self):
        l=client();l.execute('''
            extra=item('Base.Rope');storage:AddItem(extra)
            carMenu();choose('IGUI_CVP_TieNearestBodies')
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            local n=0;for _ in pairs(S.graph.links) do n=n+1 end
            assert(n==1 and extra:getContainer()==storage and chain:getContainer()==storage)
            intact(body);intact(body2)
        ''')
        n=Network();s=n.server;c=n.clients['owner']
        for vm in (s,*n.clients.values()):vm.execute("extra=item('Base.Rope');storage:AddItem(extra)")
        c.execute("carMenu();choose('IGUI_CVP_TieNearestBodies')")
        for _ in range(20):
            c.execute('finishStage()');n.pump()
            if s.eval('next(S.graph.links)~=nil'):break
        c.execute("require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()")
        n.pump();n.publish()
        s.execute("local n=0;for _ in pairs(S.graph.links) do n=n+1 end;assert(n==1 and extra:getContainer()==storage and chain:getContainer()==storage)")

    def test_foreign_train_disables_bulk_operations_without_hiding_own_train(self):
        l=client();l.execute('''
            link(C,A,rope);local username=player.getUsername
            player.getUsername=function() return 'other' end;link(C,B,chain);player.getUsername=username
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false;carMenu()
            local blocked=0
            for _,o in ipairs(options) do
                if o.label==getText('IGUI_CVP_DismantleAll') or o.label==getText('IGUI_CVP_DetachCargo') then
                    assert(o.notAvailable);blocked=blocked+1
                end
            end
            assert(blocked==2)
            local enabled=0
            for _,o in ipairs(options) do
                if o.label==getText('IGUI_CVP_TrainChoice','1','1') or o.label==getText('IGUI_CVP_TrainChoice','2','1') then
                    if not o.notAvailable then enabled=enabled+1;o.run() end
                end
            end
            assert(enabled==1);completeJob();assert(chain:getContainer()~=storage)
        ''')

    def test_multiplayer_selected_detach_preserves_other_train(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute('link(C,A,rope);link(C,B,chain)');n.publish()
        c.execute("carMenu();choose('IGUI_CVP_TrainChoice','1','1')");n.finish();n.publish()
        s.execute('''
            local roots,n=0,0;for _,r in pairs(S.graph.links) do n=n+1;if r.a.kind=='vehicle' then roots=roots+1 end end
            assert(n==2 and roots==1 and rope:getContainer()~=storage and chain:getContainer()~=storage)
        ''')

    def test_multiplayer_cancel_dismantle_shared_rope_then_retry(self):
        n=Network();s=n.server;c=n.clients['owner']
        c.execute("carMenu();choose('IGUI_CVP_TieNearestBodies')");n.finish();n.publish()
        c.execute("carMenu();choose('IGUI_CVP_DismantleAll')")
        for _ in range(20):
            c.execute('finishStage()');n.pump()
            if s.eval('(function() local n=0;for _ in pairs(S.graph.links) do n=n+1 end;return n end)()')==1:break
        c.execute("require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()")
        n.pump();n.publish()
        s.execute("assert(rope:getContainer()~=storage);local n=0;for _,r in pairs(S.graph.links) do n=n+1;assert(r.a.kind=='vehicle') end;assert(n==1)")
        c.execute("carMenu();choose('IGUI_CVP_DismantleAll')");n.finish();n.publish()
        s.execute("assert(not next(S.graph.links) and rope:getContainer()==storage)")
        c.execute("assert(storage:getItems():size()==2)")


if __name__=='__main__':unittest.main()
