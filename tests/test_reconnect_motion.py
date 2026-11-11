"""A reattached free end must pull its original bodies, not just update the rope."""
import unittest
from test_link_simulation import environment
from test_link_multiplayer import Network


class ReconnectMotionTests(unittest.TestCase):
    def test_mp_reconnect_ignores_empty_tether_and_moves_original_body_on_both_clients(self):
        n=Network();s=n.server;c=n.clients['owner']
        s.execute('''
            function release(id,side)
                beside(S.graph.links[id][side]);assert(R:command(player,{op='release',id=id,
                    revision=S.graph.links[id].revision,side=side}))
            end
            empty=link(C,A,chain);release(empty,'a');release(empty,'b')
            train=link(C,B,rope);release(train,'a');equipment=S.graph.links[train].equipment
        ''')
        n.publish()
        c.execute("carMenu();assert(context.children[1].label==getText('IGUI_CVP_TieNearestBodies'));choose('IGUI_CVP_ReconnectTrain')")
        n.finish()
        before=s.globals().body2.x
        for _ in range(50):
            n.tick(.04)
        s.execute('''
            assert(S.graph.links[train].a.kind=='vehicle' and S.graph.links[train].b.kind=='body')
            assert(not S.graph.links[empty] and chain:getWorldItem())
            local count=0
            for _,q in pairs(grid) do for _,o in ipairs(q.ground) do
                if o:getItem()==chain then count=count+1 end
            end end
            assert(count==1,'released chain must remain one original world item')
            assert(require('CVP_Equipment').get(equipment)==rope)
            assert(worldCount(body2)==1 and body2.inv:getItems():size()==1)
        ''')
        self.assertGreater(s.globals().body2.x,before+.1)
        for client in n.clients.values():
            self.assertGreater(client.globals().body2.x,before+.1)
            client.execute("assert(worldCount(body2)==1 and body2.inv:getItems():size()==1)")

    def test_reconnecting_either_end_resumes_motion_and_preserves_items(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                l = environment(); l.globals().reverse = reverse
                l.execute('''
                    local root=link(C,A,chain);local tail=link(A,B,rope)
                    for i=1,20 do car.x=car.x+.04;step() end
                    edit(root,'release','a')
                    for i=1,20 do step() end
                    local id,side=root,'a'
                    if reverse then
                        -- Release B from the tail, keeping A and the other free end.
                        edit(tail,'release','b');id=tail;side='b'
                    end
                    local equipment=S.graph.links[id].equipment
                    edit(id,'take',side)
                    beside(C)
                    local ok,why=S:command(player,{op='bind',id=id,
                        revision=S.graph.links[id].revision,side=side,target=C})
                    assert(ok,why)
                    local x=body.x
                    for i=1,50 do car.x=car.x+.04;step() end
                    assert(body.x>x+.1,'reattached body remained stationary')
                    assert(S.graph.links[id][side].kind=='vehicle')
                    assert(E.get(equipment)==(reverse and rope or chain))
                    intact(body);intact(body2)
                ''')


if __name__ == '__main__':
    unittest.main()
