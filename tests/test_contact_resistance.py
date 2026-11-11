"""No intra-chain contacts; taut ropes and independent contact paths retain load."""
import unittest
from test_link_simulation import environment


def dense(n, topology, material, factory=environment):
    l=factory()
    l.globals().n=n;l.globals().topology=topology;l.globals().material=material
    l.execute('''
        all={body,body2};ends={A,B};ids={};gearById={}
        for i=3,n do
            local b=corpse();b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
            b.getSquare=body.getSquare;b.setSquare=body.setSquare
            b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
            sq:addCorpse(b);all[i]=b;ends[i]={kind='body',key=b.md.CVPBodyKey,point='feet'}
        end
        for i,b in ipairs(all) do move(b,-2+((i-1)%8)*.18,math.floor((i-1)/8)*.18) end
        H.discover()
        for i,b in ipairs(all) do
            local gear=item(material);storage:AddItem(gear)
            local parent=i>1 and (topology=='chain' or topology=='mixed' and i==2) and ends[i-1] or C
            local id=link(parent,ends[i],gear);ids[i]=id;gearById[id]=gear
        end
        function drive(dt,dx,dy)
            car.x=car.x+dx;car.y=car.y+(dy or 0);now=now+dt*1000
            local requests,loads=Sim:tick(S.graph,S.index,dt,now)
            assert(#requests==0)
            return loads[car] or 0
        end
        function unchangedItems()
            for _,b in ipairs(all) do intact(b) end
            for id,gear in pairs(gearById) do assert(E.get(S.graph.links[id].equipment)==gear) end
        end
    ''')
    return l


class ContactResistanceTests(unittest.TestCase):
    def test_compressed_chain_has_no_contact_forces_or_slack_load(self):
        for count in (2,8,32):
            l=environment();l.globals().count=count;l.execute("""
                local load=require 'CVP_Load';local rope=require 'CVP_Rope'
                local rows,contacts={},{}
                for i=1,count do rows[i]={x=0,y=0,z=0,angle=0,mass=75,taut=i==1,parent=rows[i-1],pushX=9,pushY=9} end
                rope.separate(rows,contacts);load.connect(rows,contacts)
                assert(#contacts==0 and rows[1].loadConnected)
                for i,r in ipairs(rows) do assert(r.pushX==0 and r.pushY==0);if i>1 then assert(not r.loadConnected) end end
                for _,r in ipairs(rows) do r.taut=true end
                load.connect(rows,contacts)
                for _,r in ipairs(rows) do assert(r.loadConnected) end
            """)

    def test_contact_membership_changes_when_chains_join_or_split(self):
        l=environment();l.execute("""
            local rope=require 'CVP_Rope';local a={x=0,y=0,z=0,angle=0};local b={x=.2,y=0,z=0,angle=0}
            local rows,contacts={a,b},{}
            rope.separate(rows,contacts);assert(#contacts==2 and a.pushX~=0)
            b.parent=a;rope.separate(rows,contacts);assert(#contacts==0 and a.pushX==0 and b.pushX==0)
            b.parent=nil;rope.separate(rows,contacts);assert(#contacts==2)
        """)

    def test_collecting_contacts_does_not_change_body_forces_or_add_a_pair_scan(self):
        l=environment();l.execute('''
            local rope=require 'CVP_Rope';local rows={}
            for i=1,32 do rows[i]={x=(i%8)*.18,y=math.floor(i/8)*.18,z=0,angle=.2*i} end
            local sqrt=math.sqrt;local queries=0
            math.sqrt=function(...) queries=queries+1;return sqrt(...) end
            rope.separate(rows);local firstQueries=queries;local expected={}
            for i,r in ipairs(rows) do expected[i]={r.pushX,r.pushY} end
            queries=0;local contacts={};rope.separate(rows,contacts)
            assert(#contacts>0 and queries==firstQueries)
            for i,r in ipairs(rows) do assert(r.pushX==expected[i][1] and r.pushY==expected[i][2]) end
        ''')

    def test_current_dense_chains_load_only_through_taut_ropes(self):
        for material in ('Base.Rope','Base.HeavyChain'):
            for fps in (30,60,120):
                with self.subTest(material=material,fps=fps):
                    l=dense(32,'chain',material)
                    l.execute("""
                        local fps=...;local loaded=false
                        for tick=1,16*fps do
                            local force=drive(1/fps,.5/fps);loaded=loaded or force>0
                            local path=true
                            for _,r in ipairs(Sim.groups[1].records) do
                                path=path and r.taut and not r.failed
                                assert((r.loadConnected==true)==(path==true))
                                assert(r.pushX==0 and r.pushY==0)
                                -- Reaction is recorded at the root and can include
                                -- the load of every body downstream of it.
                                assert(r.loadMass>=0 and r.loadMass<math.huge)
                                if r.parent then assert(r.loadMass==0) end
                            end
                        end
                        assert(loaded,'taut chain never loads vehicle');unchangedItems()
                    """,fps)

    def test_independent_and_mixed_groups_retain_full_steady_load(self):
        for count in (2,8,32):
            for topology in ('parallel','mixed'):
                with self.subTest(count=count,topology=topology):
                    l=dense(count,topology,'Base.HeavyChain')
                    l.execute('''
                        local force
                        for i=1,240 do force=drive(.05,.025) end
                        local nominal=0;for _,r in pairs(Sim.records) do nominal=nominal+r.mass end
                        -- At steady speed on the fixture surface, force is in N,
                        -- not kg; small transient constraint forces are possible.
                        local expected=nominal*9.81*.65
                        assert(force>expected*.98 and force<expected*1.02)
                        unchangedItems()
                    ''')

    def test_slack_root_release_unload_and_disable_stop_resistance(self):
        for mutation in ('length','release','unload','disable'):
            with self.subTest(mutation=mutation):
                l=dense(8,'chain','Base.HeavyChain');l.globals().mutation=mutation
                l.execute('''
                    for i=1,240 do drive(.05,.025) end
                    local first=Sim.groups[1].records[1];local id=first.link.id
                    if mutation=='length' then S.graph.links[id].length=S.graph.links[id].length+3
                    elseif mutation=='release' then edit(id,'release',first.edge.side)
                    elseif mutation=='unload' then all[8].sq=nil;H.discover()
                    else SandboxVars.CorpseProxyLab.Enabled=false end
                    assert(drive(.05,.001)==0,'disconnected group still loads vehicle')
                    if mutation~='unload' then unchangedItems() end
                ''')

    def test_rewire_uses_current_load_paths_and_retains_materials(self):
        from test_link_runtime import environment as runtime
        l=dense(32,'parallel','Base.HeavyChain',runtime)
        l.execute('''
            beside(C);local plan=assert(R:prepareRewire(player,C))
            for i=2,#plan.steps do beside(plan.steps[i]);assert(R:visitRewire(player,plan.token)) end
            for tick=1,320 do
                car.x=car.x+.025;run()
                assert(#Sim.groups==1 and #Sim.groups[1].records==32)
            end
            -- Root reaction includes downstream bodies, in equivalent mass units.
            local nominal,actual=0,0
            for _,r in ipairs(Sim.groups[1].records) do
                nominal=nominal+r.mass;actual=actual+(r.loadMass or 0)
            end
            assert(actual>nominal*.98 and actual<nominal*1.02 and #impulses>0)
            unchangedItems();assert(R:save())
        ''')

    def test_degraded_chain_load_excludes_slack_tail_and_stops_with_anchor(self):
        from test_link_runtime import environment as runtime
        l=dense(32,'parallel','Base.HeavyChain',runtime)
        l.execute('''
            beside(C);local plan=assert(R:prepareRewire(player,C))
            for i=2,#plan.steps do beside(plan.steps[i]);assert(R:visitRewire(player,plan.token)) end
            for i=1,160 do car.x=car.x+.025;run() end
            local group=Sim.groups[1];assert(group.nativeFallback)
            local connected,nominal=0,0
            for _,r in ipairs(group.records) do if r.loadConnected then
                connected=connected+1;nominal=nominal+r.mass
            end end
            assert(connected>0 and connected<32,'fixture needs a slack tail')
            local force=R.loads[car] or 0
            assert(force>0 and force<=nominal*9.81*.65*1.01,'fallback charged an unconnected body')
            -- A clock/trajectory correction must never be converted into drag.
            R.motionCorrection=true;car.x=car.x+.025;now=now+50
            local requests,loads=R:simulate(.05,now)
            assert(#requests==0 and (loads[car] or 0)==0,'correction created resistance')
            for i=1,20 do run() end
            assert((R.loads[car] or 0)==0,'stopped anchor retained resistance')
            unchangedItems()
        ''')

    def test_load_change_does_not_change_poses_at_turn_reverse_or_variable_steps(self):
        a=dense(32,'chain','Base.Rope');b=dense(32,'chain','Base.Rope')
        b.execute('''
            require('CVP_Load').connect=function(records)
                local path=true
                for _,r in ipairs(records) do path=path and r.taut and not r.failed;r.loadConnected=path end
            end
        ''')
        for tick in range(120):
            for l in (a,b):
                l.execute('''
                    local i=...;local dt=({.016,.017,.1})[i%3+1]
                    drive(dt,(i<60 and .5 or -.5)*dt,math.sin(i*.1)*dt*.1)
                    pose={}
                    for _,body in ipairs(all) do
                        pose[#pose+1]=body.x;pose[#pose+1]=body.y;pose[#pose+1]=body.angle
                    end
                    unchangedItems()
                ''',tick)
            self.assertEqual(list(a.globals().pose.values()),list(b.globals().pose.values()))

    def test_chain_reaction_snapshot_applies_only_at_mp_physics_owner(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server
        s.execute('''
            World.move(body,-2,0,0,gridSquare(-2,0,0))
            World.move(body2,-2.9,0,0,gridSquare(-3,0,0))
            root=link(C,A,rope);tail=link(A,B,chain)
        ''')
        n.publish()
        n.clients['owner'].execute('physicsOwner=true')
        n.clients['friend'].execute('physicsOwner=false')
        for _ in range(40): n.tick(.05)
        s.execute('assert(R.loads[car]>0 and #impulses==0)')
        expected=s.eval('R.loads[car]')
        for c in n.clients.values():
            self.assertAlmostEqual(expected,c.eval("CVPMPClient.loads['sql:71'].resistanceForceN"))
        owner=n.clients['owner'];friend=n.clients['friend']
        owner.execute('assert(#impulses>0)')
        friend.execute('assert(#impulses==0)')
        before=len(owner.globals().impulses)
        s.execute('car.getNetPlayerId=function() return 2 end')
        owner.execute('physicsOwner=false')
        friend.execute('physicsOwner=true')
        for _ in range(5): n.tick(.05)
        friend.execute('assert(#impulses>0)')
        self.assertEqual(before,len(owner.globals().impulses))


if __name__=='__main__':
    unittest.main()
