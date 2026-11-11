"""Terminal attachment nodes must remain movable after their neighbour is removed."""
import unittest
from test_link_simulation import environment

class TerminalTailTests(unittest.TestCase):
    def test_zero_time_keeps_committed_endpoint_geometry(self):
        lua=environment()
        lua.execute("""
            local joint={kind='joint',key='k',x=5,y=2,z=.025}
            local free={kind='ground',x=4,y=2,z=.025}
            H.joints={k=joint};H.freeEnds={saved=free}
            Sim.obstacles={marker=true}
            Sim:tick(S.graph,S.index,0,now)
            assert(H.joints.k==joint and H.freeEnds.saved==free)
            assert(Sim.obstacles.marker)
        """)

    def test_single_section_joint_tail_is_planned_and_dragged(self):
        lua=environment()
        lua.execute("""
            local root=link(C,A,rope)
            S.graph.links.tail={id='tail',revision=1,owner='player',
                equipment='tail-gear',material='Base.Rope',length=.4,
                a={kind='body',key='A',point='feet',x=0,y=0,z=.025},
                b={kind='joint',key='empty:test',x=20,y=0,z=.025}}
            S.index=assert(G.index(S.graph))
            Sim:build(S.graph,S.index)
            local found=false
            for _,group in ipairs(Sim.groups) do
                for _,span in ipairs(group.spans) do
                    if #span==1 and span[1].id=='tail' then found=true end
                end
                require('CVP_LinkJoints').place(group,S.graph,H)
            end
            assert(found,'terminal single-section joint was omitted from the simulation plan')
            local a=H.sample(S.graph.links.tail.a)
            local b=H.sample(S.graph.links.tail.b)
            assert(G.distance(a,b)<=.400001,'terminal joint stayed pinned beyond rope length')
            assert(b.z==.025,'free tail was lifted off the ground')
            assert(S.graph.links.tail.length==.4,'dragging changed rope budget')
        """)

class OrphanEndpointTests(unittest.TestCase):
    def test_release_makes_remaining_joint_pickable_without_changing_budget(self):
        from test_link_graph import environment
        lua=environment()
        lua.execute("""
            local j={kind='joint',key='knot',x=1,y=0,z=.025}
            add('left',bodyEnd('A'),j);add('right',j,bodyEnd('B',2))
            local length=graph.links.left.length
            release('right','a')
            assert(graph.links.left.b.kind=='ground' and not graph.links.left.b.key)
            assert(graph.links.left.length==length)
            take('left','b')
            assert(graph.links.left.b.kind=='held')
            assert(not G.take(graph,'right',graph.links.right.revision,'a','alice'))
        """)

    def test_load_recovers_orphan_without_mutating_saved_input(self):
        from test_link_graph import environment
        lua=environment()
        lua.execute("""
            add('tail',bodyEnd('A'),{kind='joint',key='old',x=1,y=0,z=.2})
            local saved=graph
            local fixed,changed=G.dropHolders(saved)
            assert(changed and saved.links.tail.b.kind=='joint')
            assert(fixed.links.tail.b.kind=='ground' and fixed.links.tail.b.z==.025)
            assert(not G.index(fixed).byJoint.old)
            local again,changedAgain=G.dropHolders(fixed)
            assert(not changedAgain and again.revision==fixed.revision)
        """)

if __name__=='__main__': unittest.main()

