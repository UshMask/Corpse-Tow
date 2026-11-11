"""Real loaded-world adapter, equipment ledger and solver; no visual game checks."""
import unittest
from lua_fixture import create_current_fixture


def environment():
    lua = create_current_fixture()
    lua.execute('''
        player.getUsername=function() return 'player' end
        car.getSqlId=function() return 71 end;car.getId=function() return 17 end
        body.md.CVPBodyKey='A';body2.md.CVPBodyKey='B'
        body.netID='101';body2.netID='102'
        for _,b in ipairs(bodies) do b.getAngle=function(s) return s.angle or 0 end end
        CVPNetwork={bodies=function() return list(bodies) end,
            find=function(id) for _,b in ipairs(bodies) do if b.netID==id then return b end end end,
            id=function(b) return b.netID end}
        E=require 'CVP_Equipment';G=require 'CVP_LinkGraph';World=require 'CVP_World'
        H=require('CVP_LinkHost').new();H.discover()
        S=require('CVP_LinkService').new(E,H);assert(S:load())
        Sim=require('CVP_LinkSimulation').new(H,E)
        A={kind='body',key='A',point='feet'};B={kind='body',key='B',point='feet'}
        C={kind='vehicle',key='sql:71',point='hitch'}
        function move(b,x,y)
            World.move(b,x,y,0,gridSquare(math.floor(x),math.floor(y),0))
        end
        function beside(e)
            local pos=assert(H.sample(e));player.x=pos.x;player.y=pos.y;return pos
        end
        function link(a,b,gear)
            beside(a);local token=assert(S:prepare(player,a,gear:getID()))
            beside(b);local ok,id=S:create(player,token,b);assert(ok,id);return id
        end
        function edit(id,op,side,target)
            local row=S.graph.links[id];beside(row[side])
            local ok,why=S:command(player,{op=op,id=id,revision=row.revision,side=side,target=target})
            assert(ok,why)
        end
        function step()
            now=now+50;local requests,loads=Sim:tick(S.graph,S.index,.05,now)
            local samples,holders=H.samples(S.graph);assert(S:tick(samples,holders))
            return requests,loads
        end
        function intact(b)
            assert(worldCount(b)==1 and b.inv:getItems():size()==1)
            assert(b.inv:getItems():get(0):getFullType()=='Base.Watch')
        end
        move(body2,-3,0)
    ''')
    return lua


class LinkSimulationTests(unittest.TestCase):
    def test_body_chain_can_exist_before_car_and_after_selected_end_release(self):
        l = environment(); l.execute('''
            local tail=link(A,B,rope);local x,y=body.x,body2.x
            for i=1,10 do step() end
            assert(body.x==x and body2.x==y and #Sim.groups==0)
            local root=link(C,A,chain)
            for i=1,40 do car.x=car.x+.04;step() end
            assert(body.x>x+.1 and body2.x>y+.1)
            assert(E.get(S.graph.links[tail].equipment)==rope)
            edit(root,'release','a');x=body.x;y=body2.x
            for i=1,10 do car.x=car.x+.2;step() end
            assert(body.x==x and body2.x==y and S.graph.links[tail].b.key=='B')
            assert(S.graph.links[root].a.kind=='ground')
            intact(body);intact(body2)
        ''')

    def test_reverse_endpoint_order_is_oriented_from_vehicle(self):
        l = environment(); l.execute('''
            local root=link(A,C,rope);local tail=link(B,A,chain)
            for i=1,30 do car.x=car.x+.05;step() end
            assert(Sim.records[root].body==body and Sim.records[root].edge.side=='b')
            assert(Sim.records[tail].body==body2 and body.x>.1 and body2.x>-2.9)
            intact(body);intact(body2)
        ''')

    def test_unloaded_tail_suspends_whole_group_then_recovers_without_identity_change(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain)
            local saved=body2.sq;body2.sq=nil;H.discover()
            local x=body.x
            for i=1,5 do car.x=car.x+.1;step() end
            assert(body.x==x and E.get(S.graph.links[tail].equipment)==chain)
            body2.sq=saved -- Recovery does not require a graph edit or discovery generation change.
            for i=1,15 do step() end
            assert(Sim.records[tail] and body.x>x+.01)
            intact(body);intact(body2)
        ''')

    def test_pending_equipment_never_allows_partial_chain_simulation(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain)
            local get=E.get;local missing=S.graph.links[tail].equipment
            E.get=function(key,...) if key~=missing then return get(key,...) end end
            local x=body.x;car.x=car.x+.7;step();assert(body.x==x)
            E.get=get
            for i=1,10 do step() end
            assert(Sim.records[tail] and body.x>x+.01)
            intact(body);intact(body2)
        ''')

    def test_external_move_uses_current_body_pose_and_original_loot(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);step();move(body,1,0)
            step();assert(body.x>.8)
            intact(body)
        ''')

    def test_disabled_towing_and_carried_end_do_not_pull_player_or_body(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);step()
            SandboxVars.CorpseProxyLab.Enabled=false
            local x=body.x;car.x=car.x+.5;step();assert(body.x==x)
            edit(root,'release','a');SandboxVars.CorpseProxyLab.Enabled=true
            edit(root,'take','a');player.x=8;step()
            assert(body.x==x and player.x==8 and S.graph.links[root].a.kind=='held')
            player.x=20;step()
            assert(body.x==x and player.x==20 and S.graph.links[root].a.kind=='ground')
            assert(E.get(S.graph.links[root].equipment)==rope)
        ''')

    def test_foreign_towing_requests_only_affected_end_release(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);local tail=link(A,B,chain)
            body2.md.CorpseTowingVehicleToken='foreign';local x=body.x
            car.x=car.x+1;local requests=step()
            assert(#requests==1 and requests[1].id==tail and requests[1].side=='b')
            assert(body.x==x and S.graph.links[root] and S.graph.links[tail])
            intact(body);intact(body2)
        ''')

    def test_duplicate_persistent_key_cannot_be_bypassed_with_native_id(self):
        l = environment(); l.execute('''
            body2.md.CVPBodyKey='A';bodies[#bodies+1]=body
            H.discover();assert(H.bodies.A==false)
            assert(not H.resolve({kind='body',key='A',native='101'},player))
            assert(not H.resolve({kind='body',native='101'},player))
            assert(rope:getContainer()==storage)
        ''')

    def test_identity_checkpoint_failure_keeps_material_and_can_retry(self):
        l = environment(); l.execute('''
            beside(A);local token=assert(S:prepare(player,A,rope:getID()));beside(B)
            equipmentCheckpointFailure=true
            assert(not S:create(player,token,B) and rope:getContainer()==storage)
            assert(next(S.graph.links)==nil)
            equipmentCheckpointFailure=false;assert(S:create(player,token,B))
            assert(rope:getContainer()~=storage)
        ''')


if __name__ == '__main__':
    unittest.main()
