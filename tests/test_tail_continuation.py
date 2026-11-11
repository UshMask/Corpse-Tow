import unittest
from test_link_client import client
from test_link_multiplayer import Network
from test_link_graph import environment, plain

SETUP='''
extra=item('Base.Rope');storage:AddItem(extra)
local at=H.sample(C)
move(body,at.x+1,at.y);move(body2,at.x+3,at.y)
id=link(C,A,rope)
edit(id,'release','b')
'''
class TailTests(unittest.TestCase):
    def test_new_rope_and_return(self):
        l=client();l.execute(SETUP.replace("id=link(C,A,rope)","beside(C);local t=assert(S:prepare(player,C,rope:getID(),true));beside(A);local ok;ok,id=S:create(player,t,A);assert(ok)")+'''
            -- Exhaust the original spool elsewhere, as after unloading a shared train.
            local g=G.copy(S.graph);assert(g.links[id].allocation)
            local old=g.links[id].allocation
            g=assert(G.create(g,'other',{kind='body',key='A',point='feet',x=body.x,y=body.y,z=0},{kind='ground',x=body.x+12-old,y=body.y,z=0},g.links[id].equipment,'Base.Rope','player',32,true))
            assert(E.editLinks(g,S.persistedRevision));S.graph=nil;assert(S:refresh())
            menu(body2);choose('IGUI_CVP_ReconnectBody');local job=activeJob()
            assert(finishJob(job));assert(job.feedback.reason==nil,tostring(job.feedback.reason))
            local index=assert(G.index(S.graph));assert(#index.byBody.B==1 and #index.byBody.A==1)
            assert(extra:getContainer()~=storage and rope:getContainer()~=storage)
            local new=index.byBody.B[1].id;edit(new,'remove','b');assert(extra:getContainer()==storage)
            edit(id,'remove','a');edit('other','remove','a');assert(rope:getContainer()==storage)
            intact(body);intact(body2)
        ''')
    def test_remaining_length_does_not_consume_spare(self):
        for shared in (False, True):
            l=client()
            setup=SETUP
            if shared:
                setup=setup.replace('id=link(C,A,rope)', 'beside(C);local t=assert(S:prepare(player,C,rope:getID(),true));beside(A);local ok;ok,id=S:create(player,t,A);assert(ok)')
            l.execute(setup+'''
                local job=CVPRuntime.actions:reconnect(player,id,S.graph.links[id].revision,'b',B,nil,extra)
                assert(finishJob(job) and not job.feedback.reason)
                assert(S.graph.links[id].b.key=='B' and extra:getContainer()==storage)
                assert(G.index(S.graph));intact(body2)
            ''')
    def test_cancel_keeps_spare(self):
        l=client();l.execute(SETUP+'''
            local job=CVPRuntime.actions:reconnect(player,id,S.graph.links[id].revision,'b',B,nil,extra)
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            assert(extra:getContainer()==storage and rope:getContainer()~=storage)
        ''')
    def test_mp_new_tail_cancel_then_bind(self):
        n=Network();s=n.server;c=n.clients['owner']
        for vm in (s,*n.clients.values()):
            vm.execute("extra=item('Base.Rope');storage:AddItem(extra)")
        s.execute("""
            E=require 'CVP_Equipment';G=require 'CVP_LinkGraph';C={kind='vehicle',native=17,point='hitch'};A={kind='body',key='A',point='feet'};B={kind='body',key='B',point='feet'}
            local at=H.sample(C)
            World.move(body,at.x+1,at.y,0,gridSquare(math.floor(at.x+1),math.floor(at.y),0))
            World.move(body2,at.x+3,at.y,0,gridSquare(math.floor(at.x+3),math.floor(at.y),0));H.discover()
            beside(C);local t=assert(S:prepare(player,C,rope:getID(),true));beside(A);local ok;ok,id=S:create(player,t,A);assert(ok)
            local row=S.graph.links[id];beside(A);assert(S:command(player,{op='release',id=id,revision=row.revision,side='b'}))
            local g=G.copy(S.graph);local old=g.links[id].allocation
            g=assert(G.create(g,'other',{kind='body',key='A',point='feet',x=body.x,y=body.y,z=0},
                {kind='ground',x=body.x+12-old,y=body.y,z=0},g.links[id].equipment,'Base.Rope','owner',32,true))
            assert(E.editLinks(g,S.persistedRevision));S.graph=nil;assert(S:refresh())
        """)
        for vm in n.clients.values():
            vm.execute("""
                local h=CVPMPClient.host;local at=h.sample({kind='vehicle',native=17,point='hitch'})
                World.move(body,at.x+1,at.y,0,gridSquare(math.floor(at.x+1),math.floor(at.y),0))
                World.move(body2,at.x+3,at.y,0,gridSquare(math.floor(at.x+3),math.floor(at.y),0));h.discover()
            """)
        n.publish()
        c.globals().tail_id=s.globals().id
        c.execute("""
            local row=CVPMPClient.graph.links[tail_id]
            job=CVPMPClient.actions:reconnect(localPlayer,tail_id,row.revision,'b',{kind='body',key='B',point='feet'},nil,extra)
            finishStage();require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()
        """)
        n.pump()
        s.execute("assert(extra:getContainer()==storage and S.graph.links[id].b.kind=='ground')")
        c.execute("""
            local row=CVPMPClient.graph.links[tail_id]
            job=CVPMPClient.actions:reconnect(localPlayer,tail_id,row.revision,'b',{kind='body',key='B',point='feet'},nil,extra)
        """)
        n.finish();n.publish()
        s.execute("assert(extra:getContainer()~=storage);local idx=assert(G.index(S.graph));assert(#idx.byBody.B==1 and #idx.byBody.A==1)")
        c.execute("assert(job.finished and not job.feedback.reason)")

    def test_tail_survives_reload_and_returns_each_original_once(self):
        l=environment(storage=True)
        l.execute("""
            key=assert(E.hold(original,transfer,{link={id='a',a=carEnd('car'),b={kind='ground',x=1,y=0,z=0},owner=player.key,shared=true}}))
            local old=E.links()
            assert(E.editLinks(assert(G.create(old,'other',bodyEnd('A',20),bodyEnd('B',31),key,'Base.Rope',player.key,32,true)),old.revision))
            spare=item({id=43,type='Base.Rope',condition=51});source:AddItem(spare)
            extraKey=assert(E.hold(spare,transfer,{tail={id='a',revision=1,side='b',target=bodyEnd('C',3),owner=player.key,maxBodies=32}}))
            assert(not CVPEquipmentRuntime.data.rows[extraKey].tailOriginal)
        """)
        restored=environment(plain(l.globals().persisted),storage=True)
        restored.execute("""
            local graph=E.links();assert(G.index(graph));local key=graph.links.a.equipment
            local tail;for id,row in pairs(graph.links) do if row.equipment~=key then tail=id end end
            assert(tail and E.releaseLink(tail,graph.links[tail].revision,destination,transfer))
            assert(#destination.rows==1 and destination.rows[1]:getID()==43 and destination.rows[1].state.condition==51)
            graph=E.links();assert(E.releaseLink('a',graph.links.a.revision,destination,transfer));assert(#destination.rows==1)
            graph=E.links();assert(E.releaseLink('other',graph.links.other.revision,destination,transfer))
            assert(#destination.rows==2 and not next(E.links().links))
        """)

    def test_ledger_write_and_transfer_failure_restore_tail(self):
        for failure in ('write', 'transfer'):
            l=environment(storage=True);l.globals().failure=failure
            l.execute("""
                key=assert(E.hold(original,transfer,{link={id='a',a=carEnd('car'),b={kind='ground',x=1,y=0,z=0},owner=player.key,shared=true}}))
                local old=E.links()
                local g=assert(G.create(old,'other',bodyEnd('A',20),bodyEnd('B',31),key,'Base.Rope',player.key,32,true))
                assert(E.editLinks(g,old.revision));before=E.links()
                spare=item({id=43,type='Base.Rope',condition=51});source:AddItem(spare)
                if failure=='write' then failWrite=true end
                local transferFn=failure=='transfer' and function() return false,'refused' end or transfer
                local k,why=E.hold(spare,transferFn,{tail={id='a',revision=1,side='b',target=bodyEnd('C',3),owner=player.key,maxBodies=32}})
                failWrite=false
                assert(why and spare:getContainer()==source)
                local graph=E.links();assert(G.index(graph))
                assert(graph.links.a.b.kind=='ground' and graph.links.a.allocation==before.links.a.allocation)
                local count=0;for _ in pairs(graph.links) do count=count+1 end;assert(count==2)
                assert(E.get(key):getID()==42)
            """)

if __name__=='__main__':unittest.main()



