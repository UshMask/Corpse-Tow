"""Adapter contracts against a small Plow API model, no redistributed mod code."""
import unittest
from test_link_runtime import environment
from test_link_multiplayer import Network


def setup(l):
    l.execute('''
        if R then CVPRuntime={authority=R} end
        P=require 'CVP_Plow'
        PlowBlade={_squares={},_fastMoved={},_fastOrigin={},_pile={},_coast={},_spin={},
            _seenAhead={},_mpDirtyBody={},_mpLastMovedMs={},STICK_EXPIRE_MS=500}
        local p=PlowBlade
        scanSquares={body:getSquare()}
        p.collectSquares=function()
            for k in pairs(p._squares) do p._squares[k]=nil end
            for i,sq in ipairs(scanSquares) do p._squares[i]=sq end
            return #scanSquares
        end
        p.moveBody=function(b,x,y,z) b:setX(x);b:setY(y);return true end
        p.relocateRemote=function(b,x,y,z,a) b:setX(x);b:setY(y);b:setZ(z);b:setForwardDirectionAngle(a);return true end
        p.mpValidateMove=function() return true end
        p.updateCoast=function() for b in pairs(p._coast) do p.moveBody(b,b:getX()+.1,b:getY(),0) end end
        p.removeCorpseCounted=function(sq,b) sq:removeCorpse(b,true) end
        p.flushFastMoved=function()
            for b in pairs(p._fastMoved) do
                p.removeCorpseCounted(b:getSquare(),b);b:getSquare():addCorpse(b,true);p._fastMoved[b]=nil
            end
        end
        originalRemove=p.removeCorpseCounted;originalFlush=p.flushFastMoved
        P.install()
        assert(p.removeCorpseCounted==originalRemove and p.flushFastMoved==originalFlush)
    ''')


class PlowCompatibilityTests(unittest.TestCase):
    def test_linked_body_filtered_without_removing_it_from_world_and_free_body_allowed(self):
        l=environment();setup(l);l.execute('''
            local id=link(C,A,rope);move(body2,.2,.2)
            local square=body:getSquare();scanSquares={square}
            local count=PlowBlade.collectSquares();assert(count==1)
            local list=PlowBlade._squares[1]:getStaticMovingObjects()
            assert(list:size()==1 and list:get(0)==body2)
            assert(square:getStaticMovingObjects():contains(body))
            local x=body.x;assert(not PlowBlade.moveBody(body,7,0,0))
            assert(not PlowBlade.relocateRemote(body,7,0,0,1) and body.x==x)
            assert(not PlowBlade.mpValidateMove({},body,car,now))
            assert(PlowBlade.moveBody(body2,.3,.2,0))
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body);intact(body2)
        ''')

    def test_detach_allows_plow_even_when_persistent_body_key_remains(self):
        l=environment();setup(l);l.execute('''
            local id=link(C,A,rope);edit(id,'release','b')
            assert(body.md.CVPBodyKey=='A')
            assert(PlowBlade.mpValidateMove({},body,car,now))
            assert(PlowBlade.relocateRemote(body,.1,0,0,0))
            intact(body)
        ''')

    def test_busy_plow_body_does_not_consume_rope_and_can_attach_after_settling(self):
        for state in ('_pile[body]={ms=now}', '_coast[body]={vx=1}',
                      '_fastMoved[body]=true', '_mpLastMovedMs[body]=now'):
            l=environment();setup(l);l.execute('PlowBlade.'+state)
            l.execute('''
                beside(A);assert(not R:prepare(player,A,rope:getID()))
                assert(rope:getContainer()==storage and not next(S.graph.links))
                PlowBlade._pile[body]=nil;PlowBlade._coast[body]=nil
                PlowBlade._fastMoved[body]=nil;now=now+501
                assert(link(C,A,rope));intact(body)
            ''')

    def test_binding_rechecks_plow_claim_after_prepare(self):
        l=environment();setup(l);l.execute('''
            beside(C);local token=assert(R:prepare(player,C,rope:getID()))
            PlowBlade._coast[body]={vx=1};beside(A)
            assert(not R:create(player,token,A))
            assert(rope:getContainer()==storage and not next(S.graph.links))
        ''')

    def test_coast_cannot_reclaim_our_body(self):
        l=environment();setup(l);l.execute('''
            local id=link(C,A,rope);local x=body.x
            PlowBlade._coast[body]={vx=1};PlowBlade.updateCoast()
            assert(body.x==x and not PlowBlade._coast[body])
            intact(body)
        ''')

    def test_install_idempotent_and_scan_views_do_not_retain_previous_membership(self):
        l=environment();setup(l);l.execute('''
            local id=link(C,A,rope);local fn=PlowBlade.collectSquares
            P.install();assert(fn==PlowBlade.collectSquares)
            PlowBlade.collectSquares();local view=PlowBlade._squares[1]
            edit(id,'release','b');PlowBlade.collectSquares()
            assert(PlowBlade._squares[1]==body:getSquare())
            scanSquares={};PlowBlade.collectSquares();assert(view:size()==0)
            PlowBlade=nil;assert(not P.busy(body));P.install();intact(body)
        ''')

    def test_client_waits_for_local_plow_flush_then_resumes_server_position(self):
        n=Network()
        for l in n.clients.values():
            setup(l);l.execute('''
                body:setX(.5);PlowBlade._fastMoved[body]=true
                PlowBlade._pile[body]={ms=now};PlowBlade._coast[body]={vx=1}
            ''')
        n.server.execute('link(C,A,rope)');n.publish()
        for l in n.clients.values():
            l.execute('''
                now=now+100;CVPMPClient.tick()
                assert(body.x==.5 and PlowBlade._fastMoved[body])
                assert(not PlowBlade._pile[body] and not PlowBlade._coast[body])
                assert(not PlowBlade.relocateRemote(body,99,0,0,0))
                PlowBlade.flushFastMoved()
                now=now+100;CVPMPClient.tick()
                assert(body.x==0 and not PlowBlade._fastMoved[body])
                local copies=0
                for _,sq in pairs(grid) do for _,b in ipairs(sq.rows) do if b==body then copies=copies+1 end end end
                assert(copies==1 and body:getStaticMovingObjectIndex()>=0)
            ''')

    def test_server_and_two_clients_use_active_graph_and_clear_stale_remote_tracks(self):
        n=Network();n.server.execute('link(C,A,rope)');n.publish()
        for l in [n.server,*n.clients.values()]:
            setup(l);l.execute('''
                body.getObjectIDAsLong=function() return 101 end
                PlowDrag={_track={[101]={body=body,q={{x=99}}}}}
                local x=body.x;assert(not PlowBlade.relocateRemote(body,99,0,0,0))
                assert(body.x==x and not PlowDrag._track[101])
            ''')
        n.server.execute("local id=next(S.graph.links);beside(S.graph.links[id].b);assert(R:command(player,{op='release',id=id,revision=S.graph.links[id].revision,side='b'}))")
        n.publish()
        for l in [n.server,*n.clients.values()]:
            l.execute('assert(PlowBlade.relocateRemote(body,.1,0,0,0))')


if __name__=='__main__': unittest.main()
