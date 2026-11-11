"""Shared rope budget, real SP/MP queues and exact original item returns."""
import unittest
from test_link_client import client
from test_link_graph import environment, plain
from test_link_multiplayer import Network


class SharedRopeTests(unittest.TestCase):
    def test_menu_one_rope_ties_two_bodies_and_returns_only_after_last_section(self):
        l=client();l.execute('''
            carMenu();choose('IGUI_CVP_TieNearestBodies');completeJob()
            local ids={};local key
            for id,row in pairs(S.graph.links) do
                ids[#ids+1]=id;assert(row.allocation and row.material=='Base.Rope')
                assert(not key or key==row.equipment);key=row.equipment
            end
            assert(#ids==2 and G.index(S.graph).spools[key].used<=12)
            assert(E.get(key)==rope and chain:getContainer()==storage)
            edit(ids[1],'remove','a');assert(rope:getContainer()~=storage and S.graph.links[ids[2]])
            edit(ids[2],'remove','a');assert(rope:getContainer()==storage and not next(S.graph.links))
            intact(body);intact(body2)
        ''')

    def test_cancel_after_first_body_keeps_original_and_does_not_take_next_rope(self):
        l=client();l.execute('''
            extra=item('Base.Rope');storage:AddItem(extra)
            carMenu();choose('IGUI_CVP_TieNearestBodies')
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end
            assert(count==1 and extra:getContainer()==storage and chain:getContainer()==storage)
            local id,row=next(S.graph.links);assert(E.get(row.equipment)==rope)
            edit(id,'remove','a');assert(rope:getContainer()==storage)
        ''')

    def test_next_rope_automatic_when_remaining_length_is_insufficient(self):
        l=client();l.execute('''
            local anchor=H.sample(C);move(body,anchor.x+8,anchor.y);move(body2,anchor.x+14,anchor.y)
            extra=item('Base.Rope');storage:AddItem(extra)
            CVPRuntime.actions:ropeBatch(player,C,{A,B});completeJob()
            local keys={};local count=0
            for _,row in pairs(S.graph.links) do keys[row.equipment]=true;count=count+1 end
            local n=0;for _ in pairs(keys) do n=n+1 end
            assert(count==2 and n==2 and extra:getContainer()~=storage and rope:getContainer()~=storage)
            assert(chain:getContainer()==storage);intact(body);intact(body2)
        ''')

    def test_no_second_rope_stops_with_completed_first_link(self):
        l=client();l.execute('''
            local anchor=H.sample(C);move(body,anchor.x+8,anchor.y);move(body2,anchor.x+14,anchor.y)
            CVPRuntime.actions:ropeBatch(player,C,{A,B});completeJob()
            local n=0;for _ in pairs(S.graph.links) do n=n+1 end
            assert(n==1 and chain:getContainer()==storage and rope:getContainer()~=storage)
        ''')

    def test_budget_rejects_overallocation_and_mixed_claims(self):
        l=environment();l.execute('''
            graph=assert(G.create(graph,'a',carEnd('car'),bodyEnd('A',7),'rope','Base.Rope','alice',32,true))
            graph=assert(G.create(graph,'b',bodyEnd('A',7),bodyEnd('B',12),'rope','Base.Rope','alice',32,true))
            assert(not G.create(graph,'c',bodyEnd('B',12),bodyEnd('C',13),'rope','Base.Rope','alice',32,true))
            local forged=G.copy(graph);forged.links.b.allocation=6;assert(not G.index(forged))
            forged=G.copy(graph);forged.links.b.owner='bob';assert(not G.index(forged))
            forged=G.copy(graph);forged.links.b.allocation=nil;assert(not G.index(forged))
            assert(not G.extend(graph,'a',1,'second','alice'))
        ''')

    def test_reload_partial_remove_write_failure_and_exact_item_return(self):
        l=environment(storage=True);l.execute('''
            key=assert(E.hold(original,transfer,{link={id='a',a=carEnd('car'),b=bodyEnd('A',4),owner=player.key,shared=true}}))
            local old=E.links()
            local graph=assert(G.create(old,'b',bodyEnd('A',4),bodyEnd('B',8),key,'Base.Rope',player.key,32,true))
            assert(E.editLinks(graph,old.revision));assert(#source.rows==0)
            failWrite=true;assert(not E.releaseLink('a',1,destination,transfer));failWrite=false
            assert(E.links().links.a and E.links().links.b and #destination.rows==0)
            assert(not E.release(key,destination,transfer,{link={id='a',revision=1}}))
        ''')
        l=environment(plain(l.globals().persisted),storage=True);l.execute('''
            local graph=E.links();local key=graph.links.a.equipment
            assert(E.get(key):getID()==42)
            assert(E.releaseLink('a',1,destination,transfer));assert(#destination.rows==0)
            assert(E.releaseLink('b',1,destination,transfer));assert(#destination.rows==1)
            assert(destination.rows[1]:getID()==42 and destination.rows[1].state.condition==63)
            assert(not next(E.links().links))
        ''')

    def test_multiplayer_main_action_and_return_replicate_single_original(self):
        n=Network();s=n.server;c=n.clients['owner']
        c.execute("carMenu();choose('IGUI_CVP_TieNearestBodies')");n.finish();n.publish()
        s.execute('''
            local count=0;local key
            for _,row in pairs(S.graph.links) do count=count+1;assert(not key or key==row.equipment);key=row.equipment end
            assert(count==2 and require('CVP_Equipment').get(key)==rope and chain:getContainer()==storage)
        ''')
        for vm in n.clients.values():
            vm.execute("local n=0;for _,r in pairs(CVPMPClient.graph.links) do n=n+1;assert(r.allocation) end;assert(n==2)")
        for _ in range(2):
            c.execute('''
                local id,row=next(CVPMPClient.graph.links)
                CVPMPClient.actions:command(localPlayer,id,row.revision,'a','remove')
            ''');n.finish();n.publish()
        s.execute('assert(rope:getContainer()==storage and not next(S.graph.links))')
        c.execute('assert(storage:getItems():size()==2 and storage:getItemWithID(rope.id))')


    def test_server_rejects_foreign_and_stale_shared_rope_prepare(self):
        from test_link_runtime import environment as runtime
        l=runtime();l.execute('''
            beside(C);local token=assert(S:prepare(player,C,rope:getID(),true));beside(A)
            local ok,id=S:create(player,token,A);assert(ok,id)
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            player.getUsername=function() return 'intruder' end
            assert(not S:prepare(player,A,nil,true,id,S.graph.links[id].revision))
            player.getUsername=function() return 'player' end
            assert(not S:prepare(player,A,nil,true,id,99))
            local t=assert(S:prepare(player,A,nil,true,id,S.graph.links[id].revision))
            edit(id,'release','b');beside(B)
            local done,why=S:create(player,t,B);assert(not done and why=='stale connection')
            assert(E.get(S.graph.links[id].equipment)==rope)
        ''')

    def test_failed_last_checkpoint_retry_does_not_duplicate_original(self):
        l=environment(storage=True);l.execute('''
            local key=assert(E.hold(original,transfer,{link={id='a',a=carEnd('car'),b=bodyEnd('A',4),owner=player.key,shared=true}}))
            local old=E.links();assert(E.editLinks(assert(G.create(old,'b',bodyEnd('A',4),bodyEnd('B',8),key,'Base.Rope',player.key,32,true)),old.revision))
            assert(E.releaseLink('a',1,destination,transfer))
            failCheckpoint=true;assert(not E.releaseLink('b',1,destination,transfer))
            assert(#destination.rows==1 and destination.rows[1]==original and E.links().links.b)
            failCheckpoint=false;assert(E.recover(target));assert(not E.links().links.b)
            assert(#destination.rows==1 and destination.rows[1]==original)
            assert(not E.releaseLink('b',1,destination,transfer));assert(#destination.rows==1)
        ''')

    def test_multiplayer_cancel_keeps_completed_section_and_spare_rope(self):
        n=Network();s=n.server;c=n.clients['owner']
        for vm in (s,*n.clients.values()): vm.execute("extra=item('Base.Rope');storage:AddItem(extra)")
        c.execute("carMenu();choose('IGUI_CVP_TieNearestBodies')")
        for _ in range(20):
            if s.eval('next(S.graph.links)~=nil'):break
            c.execute('finishStage()');n.pump()
        self.assertTrue(s.eval('next(S.graph.links)~=nil'))
        c.execute("require('CVP_Feedback').cancel(localPlayer);CVPMPClient.actions:update()")
        n.pump();n.publish()
        s.execute('''
            local n=0;for _ in pairs(S.graph.links) do n=n+1 end
            assert(n==1 and extra:getContainer()==storage and chain:getContainer()==storage)
        ''')

    def test_removing_middle_section_keeps_both_sides_and_original(self):
        l=environment(storage=True);l.execute('''
            local key=assert(E.hold(original,transfer,{link={id='a',a=carEnd('car'),b=bodyEnd('A',3),owner=player.key,shared=true}}))
            for _,spec in ipairs({{'b','A',3,'B',6},{'c','B',6,'C',9}}) do
                local old=E.links()
                assert(E.editLinks(assert(G.create(old,spec[1],bodyEnd(spec[2],spec[3]),bodyEnd(spec[4],spec[5]),key,'Base.Rope',player.key,32,true)),old.revision))
            end
            assert(E.releaseLink('b',1,destination,transfer))
            local graph=E.links();assert(graph.links.a and graph.links.c and not graph.links.b)
            assert(G.index(graph).spools[key].used==6 and #destination.rows==0)
            assert(E.releaseLink('c',1,destination,transfer));assert(#destination.rows==0)
            assert(E.releaseLink('a',1,destination,transfer));assert(#destination.rows==1 and destination.rows[1]==original)
        ''')

    def test_detached_shared_sections_remain_in_same_network_snapshot(self):
        l=environment();l.execute('''
            graph=assert(G.create(graph,'a',carEnd('car'),bodyEnd('A',3),'rope','Base.Rope','alice',32,true))
            graph=assert(G.create(graph,'b',bodyEnd('A',3),bodyEnd('B',6),'rope','Base.Rope','alice',32,true))
            graph=assert(G.releaseEnd(graph,'b',1,'a',ground(3),'alice'))
            graph.links.b.a.x=1000;graph.links.b.b.x=1003
        ''')
        # Transport closure must retain both claims after they cease to share a body.
        from pathlib import Path
        l.execute("package.preload['CVP_Connection']=assert(loadstring(...))",Path('CorpseProxyLab/42/media/lua/shared/CVP_Connection.lua').read_text(encoding='utf-8-sig'))
        l.execute("package.preload['CVP_Protocol']=assert(loadstring(...))",Path('CorpseProxyLab/42/media/lua/shared/CVP_Protocol.lua').read_text(encoding='utf-8-sig'))
        l.globals().wire=l.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkWire.lua').read_text(encoding='utf-8-sig'))
        l.execute('''
            local p={getX=function() return 0 end,getY=function() return 0 end,getZ=function() return 0 end}
            local index=assert(G.index(graph));local spool=index.spools.rope.ids
            local real=ipairs;local scans=0
            ipairs=function(t) if t==spool then scans=scans+1 end;return real(t) end
            local ids=wire.visible(graph,index,p);ipairs=real
            assert(ids.a and ids.b and scans==1)
        ''')


    def test_thirty_two_sections_share_one_original_and_respect_chain_limit(self):
        for limit,expected in ((32,32),(8,8)):
            l=client();l.globals().limit=limit;l.globals().expected=expected;l.execute('''
                SandboxVars.CorpseProxyLab.MaxBodiesPerChain=limit
                local anchor=H.sample(C);local targets={}
                for i=1,32 do
                    local b=bodies[i]
                    if not b then
                        b=corpse();b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
                        b.getSquare=body.getSquare;b.setSquare=body.setSquare
                        b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
                        b.world=false;sq:addCorpse(b)
                    end
                    b.md.CVPBodyKey='batch-'..i;b.netID=tostring(1000+i)
                    move(b,anchor.x+i*.1,anchor.y)
                    targets[#targets+1]={kind='body',key=b.md.CVPBodyKey,point='feet'}
                end
                H.discover();CVPRuntime.actions:ropeBatch(player,C,targets);completeJob()
                local n=0;local key
                for _,r in pairs(S.graph.links) do n=n+1;assert(not key or key==r.equipment);key=r.equipment end
                assert(n==expected,'count '..n..' expected '..expected);assert(G.index(S.graph).spools[key].used<=12 and E.get(key)==rope)
                for _,b in ipairs(bodies) do intact(b) end
            ''')

    def test_multiplayer_automatically_uses_second_original(self):
        n=Network();s=n.server;c=n.clients['owner']
        for vm in (s,*n.clients.values()):
            vm.execute('''
                extra=item('Base.Rope');storage:AddItem(extra)
                local host=serverMode and H or CVPMPClient.host
                C={kind='vehicle',native=17,point='hitch'};local anchor=host.sample(C)
                World.move(body,anchor.x+8,anchor.y,0,gridSquare(math.floor(anchor.x+8),math.floor(anchor.y),0))
                World.move(body2,anchor.x+14,anchor.y,0,gridSquare(math.floor(anchor.x+14),math.floor(anchor.y),0))
                host.discover()
            ''')
        c.execute('CVPMPClient.actions:ropeBatch(localPlayer,C,{A,B})');n.finish();n.publish()
        s.execute('''
            local keys={};local n=0;for _,r in pairs(S.graph.links) do keys[r.equipment]=true end
            for _ in pairs(keys) do n=n+1 end
            assert(n==2 and rope:getContainer()~=storage and extra:getContainer()~=storage and chain:getContainer()==storage)
        ''')


if __name__=='__main__':unittest.main()
