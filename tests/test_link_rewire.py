"""Rewire independent endpoints through the real authority's visit/commit transaction."""
import unittest
from test_link_runtime import environment
from test_link_graph import plain


class LinkRewireTests(unittest.TestCase):
    def test_rewire_keeps_ids_gear_owners_and_loot_until_single_commit(self):
        l = environment(); l.execute('''
            first=link(C,A,rope);second=link(C,B,chain);before=equipmentCopy(S.graph)
            beside(C);plan=assert(R:prepareRewire(player,C));writes=equipmentWrites
            for i=2,#plan.steps do
                beside(plan.steps[i]);local ok,result=R:visitRewire(player,plan.token);assert(ok,result)
                if i<#plan.steps then
                    assert(not result.done and equipmentWrites==writes)
                    assert(S.graph.links[first].a.kind=='vehicle' and S.graph.links[second].a.kind=='vehicle')
                else assert(result.done and equipmentWrites==writes+1) end
            end
            assert(S.graph.links[first].equipment==before.links[first].equipment)
            assert(S.graph.links[second].equipment==before.links[second].equipment)
            assert(S.graph.links[first].owner==before.links[first].owner and S.graph.links[second].owner==before.links[second].owner)
            assert(E.get(S.graph.links[first].equipment)==rope and E.get(S.graph.links[second].equipment)==chain)
            assert(S.graph.links[first].a.kind=='vehicle' and S.graph.links[second].a.kind=='body')
            local ok=R:visitRewire(player,plan.token);assert(not ok and equipmentWrites==writes+1)
            intact(body);intact(body2)
        ''')

    def test_reverse_endpoint_order_remains_valid(self):
        l = environment(); l.execute('''
            local a=link(A,C,rope);local b=link(B,C,chain)
            beside(C);local plan=assert(R:prepareRewire(player,C))
            for i=2,#plan.steps do beside(plan.steps[i]);assert(R:visitRewire(player,plan.token)) end
            assert(S.graph.links[a].a.key=='A' and S.graph.links[b].a.key=='B')
            assert(S.graph.links[b].b.kind=='body');assert(G.index(S.graph))
        ''')

    def test_cancellation_timeout_and_failed_write_never_leave_half_a_layout(self):
        for mode in ('cancel', 'timeout', 'write'):
            with self.subTest(mode=mode):
                l = environment(); l.execute('''
                    first=link(C,A,rope);second=link(C,B,chain);before=equipmentCopy(S.graph)
                    beside(C);plan=assert(R:prepareRewire(player,C))
                    for i=2,#plan.steps-1 do beside(plan.steps[i]);assert(R:visitRewire(player,plan.token)) end
                ''')
                if mode == 'cancel':
                    l.execute("assert(S:disconnect('player'))")
                elif mode == 'timeout':
                    l.execute('now=now+120001')
                else:
                    l.execute('equipmentWriteFailure=true')
                l.execute('beside(plan.steps[#plan.steps]);assert(not R:visitRewire(player,plan.token))')
                self.assertEqual(plain(l.globals().before), plain(l.globals().S.graph))
                l.execute('assert(E.get(S.graph.links[first].equipment)==rope);intact(body);intact(body2)')
                if mode == 'write':
                    l.execute('equipmentWriteFailure=false;assert(R:visitRewire(player,plan.token));assert(S.graph.links[second].a.kind=="body")')

    def test_movement_membership_ownership_disable_and_unload_invalidate_plan(self):
        for mutation in ('body.x=body.x+1', 'car.x=car.x+1', 'speed=2', 'body.sq=nil',
                         "SandboxVars.CorpseProxyLab.Enabled=false", "SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1",
                         "local row=S.graph.links[first];assert(S:command(player,{id=first,revision=row.revision,side='a',op='release'}))"):
            with self.subTest(mutation=mutation):
                l = environment(); l.execute('''
                    first=link(C,A,rope);second=link(C,B,chain);beside(C);plan=assert(R:prepareRewire(player,C))
                '''); l.execute(mutation)
                before = plain(l.globals().S.graph)
                l.execute('local ok=R:visitRewire(player,plan.token);assert(not ok)')
                self.assertEqual(before, plain(l.globals().S.graph))

    def test_foreign_equipment_limit_and_free_ends_reject_before_start(self):
        for mutation in ("player.getUsername=function() return 'other' end;SandboxVars.CorpseProxyLab.AllowDetachOthers=false",
                         'SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1',
                         "edit(second,'release','b')"):
            with self.subTest(mutation=mutation):
                l = environment(); l.execute('first=link(C,A,rope);second=link(C,B,chain)'); l.execute(mutation)
                before = plain(l.globals().S.graph)
                l.execute('beside(C);assert(not R:prepareRewire(player,C))')
                self.assertEqual(before, plain(l.globals().S.graph))

    def test_remote_visits_cannot_skip_unvisited_endpoints(self):
        l = environment(); l.execute('''
            link(C,A,rope);link(C,B,chain);beside(C);local plan=assert(R:prepareRewire(player,C))
            player.x=50;local ok,err=R:visitRewire(player,plan.token)
            assert(not ok and err=='endpoint not reachable')
            assert(S.rewires.player.step==2)
            beside(plan.steps[2]);assert(R:visitRewire(player,plan.token));assert(S.rewires.player.step==3)
        ''')


if __name__ == '__main__':
    unittest.main()
