"""Bound expensive reads to a snapshot while retaining fresh motion and topology."""
import unittest
from test_link_multiplayer import Network, vm


class SnapshotWorkTests(unittest.TestCase):
    def test_capture_reuses_only_immutable_structure_and_keeps_old_poses(self):
        l=vm(True);l.execute('''
            local id=link(C,A,rope);local server=CVPMPServer
            local a=server.capture();local b=server.capture()
            assert(a.graph.links[id]==b.graph.links[id])
            assert(a.bodies.A.connections==b.bodies.A.connections)
            local x=a.graph.links[id].a.x
            S.graph.links[id].a.x=x+.25
            local c=server.capture()
            assert(a.graph.links[id].a.x==x and c.graph.links[id].a.x==x+.25)
            assert(c.graph.links[id].b==b.graph.links[id].b)
            assert(c.graph.links[id]~=b.graph.links[id])
            local length=c.graph.links[id].length
            S.graph.links[id].length=length+.1;S.dirty=true;assert(S:flush())
            local d=server.capture()
            assert(d.graph.links[id].length==length+.1 and c.graph.links[id].length==length)
            assert(d.graph.revision==S.graph.revision and c.graph.revision~=d.graph.revision)
            local row=S.graph.links[id];beside(row.a)
            assert(R:command(player,{op='release',id=id,revision=row.revision,side='a'}))
            local e=server.capture()
            assert(e.graph.links[id].a.kind=='ground' and d.graph.links[id].a.kind=='vehicle')
            assert(e.bodies.A.token~=d.bodies.A.token)
            -- Wire metadata/appearance omission must not mutate reusable snapshots.
            server.publish(player,e);assert(not e.bodies.A.appearanceOmitted and not e.graph.links[id].protocol)
            assert(require('CVP_Equipment').get(S.graph.links[id].equipment)==rope)
        ''')

    def test_vehicle_anchor_capture_uses_committed_frame_until_simulation_updates(self):
        l=vm(True);l.execute('''
            link(C,A,rope);link(C,B,chain)
            now=now+50;assert(R:tick({player},.05))
            local calls=0;local sample=H.sample
            H.sample=function(e) if e.kind=='vehicle' then calls=calls+1 end;return sample(e) end
            local a=CVPMPServer.capture();assert(calls==0)
            local old=a.bodies.A.source.x
            a.bodies.A.source.x=999;assert(a.bodies.B.source.x~=999)
            car.x=car.x+.25;local b=CVPMPServer.capture()
            assert(calls==0 and b.bodies.B.source.x==old)
            for i=1,8 do car.x=car.x+.1;now=now+50;assert(R:tick({player},.05)) end
            calls=0;local c=CVPMPServer.capture()
            assert(calls==0 and c.bodies.A.source.x~=old)
        ''')

    def test_client_order_reused_between_snapshots_without_freezing_body_motion(self):
        n=Network();n.server.execute('link(C,A,rope);link(A,B,chain)');n.publish()
        c=n.clients['friend'];c.execute('''
            local M=require 'CVP_Motion';local order=M.ordered;orderCalls=0
            M.ordered=function(...) orderCalls=orderCalls+1;return order(...) end
            CVPMPClient.orderedRows=nil
            for i=1,60 do now=now+16;CVPMPClient.tick() end
            assert(orderCalls==1)
        ''')
        n.server.execute('car.x=car.x+.8;for i=1,10 do now=now+50;CVPMPServer.tick() end')
        n.publish()
        c.execute('''
            local x=body.x;now=now+200;CVPMPClient.tick()
            assert(orderCalls==1 and body.x~=x)
        ''')
        n.server.execute('''
            local tail;for id,row in pairs(S.graph.links) do if row.b.key=='B' then tail=row end end
            beside(tail.b);assert(R:command(player,{op='release',id=tail.id,revision=tail.revision,side='b'}))
        ''')
        n.publish()
        c.execute('''
            now=now+16;CVPMPClient.tick();assert(orderCalls==2)
            for _,row in ipairs(CVPMPClient.orderedRows) do assert(row.descriptor.key~='B') end
        ''')

    def test_parent_change_without_new_tokens_rebuilds_order(self):
        n=Network();n.server.execute('link(C,A,rope);link(A,B,chain)');n.publish()
        n.clients['friend'].execute('''
            local C=CVPMPClient;now=now+16;C.tick()
            local old=C.orderedRows;local a,b=C.rows.A,C.rows.B
            local snapshot={graph=C.graph,loads=C.loads,obstacles=C.obstacles,
                bodies={A=G.copy(a.descriptor),B=G.copy(b.descriptor)}}
            snapshot.bodies.A.parent='B';snapshot.bodies.B.parent=nil
            C.apply(snapshot,{epoch=C.epoch,sequence=C.sequence+1,ready=true})
            assert(not C.orderedRows and C.rows.A==a and C.rows.B==b)
            now=now+16;C.tick()
            assert(C.orderedRows~=old and C.orderedRows[1]==b and C.orderedRows[2]==a)
            snapshot=G.copy(snapshot);snapshot.bodies.A.token=snapshot.bodies.A.token..':new'
            C.apply(snapshot,{epoch=C.epoch,sequence=C.sequence+1,ready=true})
            assert(not C.orderedRows and C.rows.A~=a)
            now=now+16;C.tick();assert(C.orderedRows[2]==C.rows.A)
        ''')


if __name__=='__main__': unittest.main()
