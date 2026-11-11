import unittest
from test_link_client import client
from test_link_multiplayer import Network

SCENE = '''
third=corpse();third.md.CVPBodyKey='D';third.netID='103'
third.getSquare=body.getSquare;third.setSquare=body.setSquare
third.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;third.getAngle=body.getAngle
third.sq=gridSquare(0,0,0);third.sq:addCorpse(third);move(third,-6,0);H.discover();D={kind='body',key='D',point='feet'}
extra=item('Base.Rope');storage:AddItem(extra)
ids={link(C,A,rope),link(A,B,chain),link(B,D,extra)}
function tow(n)
 for i=1,n do car.x=car.x+.05;now=now+50;assert(R:tick({player},.05)) end
end
'''

class ContinuousRopeTests(unittest.TestCase):
    def test_reused_body_detaches_again_without_merging_tethers_or_losing_gear(self):
        l=client();l.execute(SCENE+'''
            assert(S:unloadBody('A',{x=body.x,y=body.y,z=.05}))
            local firstJoint=S.graph.links[ids[1]].b.key
            local more1=item('Base.Rope');local more2=item('Base.Rope')
            storage:AddItem(more1);storage:AddItem(more2)
            ids[#ids+1]=link(C,A,more1)
            ids[#ids+1]=link(A,{kind='ground',x=body.x+1,y=body.y,z=.05},more2)
            edit(ids[#ids-1],'release','b')
            assert(S.graph.links[ids[#ids-1]].b.key~=firstJoint)
            assert(#S.index.byJoint[firstJoint]==2 and not S.index.byBody.A)
            assert(S:flush());local saved=serializeEquipment();loadEquipment(saved);assert(S:load())
            local x=third.x;tow(100);assert(third.x>x+.1)
            for _,id in ipairs(ids) do edit(id,'remove','a') end
            for _,gear in ipairs({rope,chain,extra,more1,more2}) do
                local count=0;for _,i in ipairs(storage.rows) do if i==gear then count=count+1 end end
                assert(count==1,'lost or duplicated tether')
            end
            assert(not next(S.graph.links))
        ''')

    def test_long_span_tows_checks_walls_and_returns_every_original_rope(self):
        from test_link_obstacles import WORLD
        l=client();l.execute(WORLD+'''
            local previous=C;local ids,gear,cargo={},{},{}
            for i=1,12 do
                local b=corpse();b.md.CVPBodyKey='long'..i;b.netID=tostring(200+i)
                b.getSquare=body.getSquare;b.setSquare=body.setSquare
                b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
                b.sq=gridSquare(0,0,0);b.sq:addCorpse(b);move(b,-9*i,.5);H.discover()
                local ref={kind='body',key=b.md.CVPBodyKey,point='feet'}
                local rope=item('Base.Rope');storage:AddItem(rope)
                ids[#ids+1]=link(previous,ref,rope);gear[#gear+1]=rope;cargo[#cargo+1]=b;previous=ref
            end
            for i=1,11 do local b=cargo[i]
                assert(S:unloadBody(b.md.CVPBodyKey,{x=b.x,y=b.y,z=.05}))
            end
            local tail=cargo[12];local x=tail.x
            wallX=-50
            for i=1,10 do car.x=car.x+.05;now=now+50;assert(R:tick({player},.05)) end
            assert(tail.x==x and Sim.obstacles[ids[1]]==O.blocked)
            wallX=nil
            for i=1,100 do car.x=car.x+.05;now=now+50;assert(R:tick({player},.05)) end
            assert(tail.x>x+.1 and not next(Sim.obstacles),'valid long span stopped')
            assert(S:flush());local saved=serializeEquipment();loadEquipment(saved);assert(S:load())
            for _,id in ipairs(ids) do edit(id,'remove','a') end
            for _,rope in ipairs(gear) do
                local count=0;for _,i in ipairs(storage.rows) do if i==rope then count=count+1 end end
                assert(count==1,'lost or duplicated original rope')
            end
            assert(not next(S.graph.links))
        ''')

    def test_first_middle_last_body_detachment_keeps_tail_and_equipment(self):
        for key in ('A','B','D'):
            with self.subTest(key=key):
                l=client();l.execute(SCENE);l.globals().removeKey=key
                l.execute('''
                    local b=H.body({key=removeKey});local before=third.x
                    assert(S:unloadBody(removeKey,{x=b.x,y=b.y,z=.05}))
                    assert(not S.index.byBody[removeKey]);assert(G.index(S.graph))
                    local frozen=b.x;tow(100)
                    assert(b.x==frozen,'detached cargo moved')
                    if removeKey~='D' then assert(third.x>before+.1,'tail stopped') end
                    for _,id in ipairs(ids) do assert(E.get(S.graph.links[id].equipment)) end
                    for _,id in ipairs(ids) do edit(id,'remove','a') end
                    assert(rope:getContainer()==storage and chain:getContainer()==storage and extra:getContainer()==storage)
                    assert(not next(S.graph.links))
                ''')

    def test_all_bodies_removed_keeps_tether_and_save_reload(self):
        l=client();l.execute(SCENE+'''
            for _,key in ipairs({'A','B','D'}) do local b=H.body({key=key})
                assert(S:unloadBody(key,{x=b.x,y=b.y,z=.05}))
            end
            tow(80);assert(not next(S.index.byBody));assert(S:flush())
            local saved=serializeEquipment();loadEquipment(saved);assert(S:load())
            assert(G.index(S.graph));tow(40)
            for _,id in ipairs(ids) do edit(id,'remove','a') end
            assert(rope:getContainer()==storage and chain:getContainer()==storage and extra:getContainer()==storage)
        ''')

    def test_shared_rope_survives_removal_and_returns_once(self):
        l=client();l.execute('''
            carMenu();choose('IGUI_CVP_TieNearestBodies');completeJob()
            local ids={};local key
            for id,row in pairs(S.graph.links) do ids[#ids+1]=id;key=row.equipment end
            assert(#ids==2)
            assert(S:unloadBody('A',{x=body.x,y=body.y,z=.05}))
            local x=body2.x
            for i=1,80 do car.x=car.x+.05;now=now+50;assert(R:tick({player},.05)) end
            assert(body2.x>x+.1 and E.get(key)==rope)
            edit(ids[1],'remove','a');assert(rope:getContainer()~=storage)
            edit(ids[2],'remove','a');assert(rope:getContainer()==storage)
            local count=0;for _,i in ipairs(storage.rows) do if i==rope then count=count+1 end end;assert(count==1)
        ''')

    def test_fresh_vm_reload_preserves_joint_and_tail_towing(self):
        from test_link_graph import plain
        from test_link_runtime import environment
        first=client();first.execute("link(C,A,rope);link(A,B,chain);assert(S:unloadBody('A',{x=0,y=0,z=.05}));assert(S:flush())")
        second=environment(plain(first.globals().equipmentDisk))
        second.execute('''
            assert(next(S.index.byJoint) and S.index.byBody.B)
            local before=body2.x
            for i=1,100 do car.x=car.x+.05;run() end
            assert(body2.x>before+.1)
            local ids={};for id in pairs(S.graph.links) do ids[#ids+1]=id end
            for _,id in ipairs(ids) do edit(id,'remove','a') end
            assert(not next(S.graph.links) and #storage.rows==2)
        ''')

    def test_horse_tail_keeps_towing_through_empty_attachment(self):
        from test_horse_towing import install_horse
        l=install_horse(client());l.execute('''
            link(T,A,rope);link(A,B,chain)
            assert(S:unloadBody('A',{x=body.x,y=body.y,z=.05}))
            mounted=true;local x=body2.x
            for i=1,100 do horse.x=horse.x+.05;now=now+50;assert(R:tick({player},.05)) end
            assert(body2.x>x+.1 and not next(R.loads))
        ''')

    def test_mp_keeps_joint_and_remaining_body_on_both_clients(self):
        n=Network();s=n.server
        s.execute("local a=link(C,A,rope);link(A,B,chain);assert(S:unloadBody('A',{x=body.x,y=body.y,z=.05}))")
        n.publish()
        for c in n.clients.values(): c.execute("local i=assert(G.index(CVPMPClient.graph));assert(next(i.byJoint) and i.byBody.B)")

if __name__=='__main__': unittest.main()
