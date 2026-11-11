"""Resume from saved graph tails, not a cancelled client job or spare inventory item."""
import unittest
from test_link_client import client
from test_link_multiplayer import Network


class RopeResumeTests(unittest.TestCase):
    def test_continuation_keeps_front_rear_and_unloaded_tails_independent(self):
        l=client();l.execute('''            local front=G.copy(C);front.point='front'
            local rearId=link(C,A,rope);local frontId=link(front,B,chain)
            -- Continuation requires a shared rope, independent of the root's material.
            local graph=G.copy(S.graph)
            graph.links[rearId].allocation=graph.links[rearId].length
            graph.links[frontId].material='Base.Rope';graph.links[frontId].allocation=graph.links[frontId].length
            local actions=CVPRuntime.actions
            actions.api.graph=function() return graph end
            local target={kind='ground',x=0,y=1,z=0}
            local rear=assert(actions:continuation(player,C,{target},true))
            local ahead=assert(actions:continuation(player,front,{target},true))
            assert(rear.id==rearId and rear.source.key=='A' and rear.count==1)
            assert(ahead.id==frontId and ahead.source.key=='B' and ahead.count==1)
            local sample=H.sample;H.sample=function(e,...) if e.kind=='body' and e.key=='A' then return nil end;return sample(e,...) end
            assert(not actions:continuation(player,C,{target},true))
            assert(actions:continuation(player,front,{target},true).id==frontId)
            H.sample=sample;graph.links[rearId].b={kind='ground',x=0,y=0,z=0}
            assert(not actions:continuation(player,C,{target},true))
        ''')

    def test_sp_resume_after_cancel_reuses_original_and_returns_once(self):
        l=client();l.execute('''
            carMenu();choose('IGUI_CVP_TieNearestBodies')
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            local id,first=next(S.graph.links);local key=first.equipment
            -- Discard the entire client queue, as after restarting the client.
            CVPRuntime.actions.jobs={};carMenu();choose('IGUI_CVP_AddNearestBodies');completeJob()
            local n=0;for _,r in pairs(S.graph.links) do n=n+1;assert(r.equipment==key) end
            assert(n==2 and S.graph.links[id].a.kind=='vehicle' and E.get(key)==rope and chain:getContainer()==storage)
            carMenu();choose('IGUI_CVP_DismantleAll');completeJob()
            assert(rope:getContainer()==storage and storage:getItems():size()==2);intact(body);intact(body2)
        ''')

    def test_grouped_resume_uses_remainder_before_spare(self):
        l=client();l.execute('''
            extra=item('Base.Rope');storage:AddItem(extra)
            carMenu();choose('IGUI_CVP_TieSeparateTrains')
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            carMenu();choose('IGUI_CVP_TieSeparateTrains');completeJob()
            local roots,n=0,0;local key
            for _,r in pairs(S.graph.links) do n=n+1;if r.a.kind=='vehicle' then roots=roots+1 end;assert(not key or key==r.equipment);key=r.equipment end
            assert(n==2 and roots==1 and extra:getContainer()==storage)
        ''')

    def test_resume_respects_foreign_ownership_and_chain_limit(self):
        for denied in ('owner','limit'):
            l=client();l.globals().denied=denied;l.execute('''
                carMenu();choose('IGUI_CVP_TieNearestBodies')
                while not next(S.graph.links) do finishStage() end
                require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
                if denied=='owner' then
                    SandboxVars.CorpseProxyLab.AllowDetachOthers=false
                    player.getUsername=function() return 'other' end
                else SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1 end
                carMenu()
                local old=next(S.graph.links);local revision=S.graph.links[old].revision
                choose('IGUI_CVP_AddNearestBodies');completeJob()
                assert(S.graph.links[old].revision==revision)
                local roots=0;for _,row in pairs(S.graph.links) do if row.a.kind=='vehicle' then roots=roots+1 end end
                assert(roots==2 and chain:getContainer()~=storage)
                local n=0;for _ in pairs(S.graph.links) do n=n+1 end;assert(n==2 and chain:getContainer()~=storage)
            ''')

    def test_resume_revalidates_stale_tail_without_spending_original(self):
        l=client();l.execute('''
            carMenu();choose('IGUI_CVP_TieNearestBodies')
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            carMenu();choose('IGUI_CVP_AddNearestBodies')
            local id=next(S.graph.links);edit(id,'release','a');completeJob()
            local n=0;for _ in pairs(S.graph.links) do n=n+1 end
            assert(n==1 and rope:getContainer()~=storage and chain:getContainer()==storage)
        ''')

    def test_multiplayer_resume_without_inventory_rope_and_return_once(self):
        n=Network();s=n.server;c=n.clients['owner']
        c.execute("carMenu();choose('IGUI_CVP_TieNearestBodies')")
        for _ in range(20):
            c.execute('finishStage()');n.pump()
            if s.eval('next(S.graph.links)~=nil'):break
        c.execute("require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()")
        n.pump();n.publish()
        c.execute("CVPMPClient.actions.jobs={};carMenu();choose('IGUI_CVP_AddNearestBodies')")
        n.finish();n.publish()
        s.execute('''
            local n=0;local key;for _,r in pairs(S.graph.links) do n=n+1;assert(not key or key==r.equipment);key=r.equipment end
            assert(n==2 and require('CVP_Equipment').get(key)==rope and chain:getContainer()==storage)
        ''')
        c.execute("carMenu();choose('IGUI_CVP_DismantleAll')");n.finish();n.publish()
        s.execute('assert(rope:getContainer()==storage and not next(S.graph.links))')
        c.execute('assert(storage:getItems():size()==2 and storage:getItemWithID(rope.id))')


if __name__=='__main__':unittest.main()
