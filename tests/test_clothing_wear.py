import unittest
from test_link_runtime import environment
from test_link_multiplayer import Network, take
from lua_fixture import copy_packet


def setup(l):
    l.execute('''
        CW=require 'CVP_ClothingWear'
        BloodBodyPartType={MAX={index=function() return 18 end},FromIndex=function(n) return n end}
        local native=instanceof
        instanceof=function(o,c) return c=='Clothing' and o.clothing==true or native(o,c) end
        shirt=item('Base.Shirt');shirt.id=600;shirt.clothing=true;shirt.condition=10;shirt.holes={}
        shirt.getCondition=function(s) return s.condition end
        shirt.setCondition=function(s,n) assert(n>=0);s.condition=n end
        shirt.getCanHaveHoles=function() return true end
        shirt.getCoveredParts=function() return list({6,7,17}) end
        shirt.getPatchType=function(s,p) return p==7 and 'patch' or nil end
        shirt.getVisual=function(s) return {
            getHole=function(_,p) return s.holes[p] or 0 end,
            setHole=function(_,p) s.holes[p]=1 end} end
        shirt.getModData=function(s) return s.md end
        body:getContainer():AddItem(shirt)
        bag=item('Base.Bag');bag.inv=container();coin=item('Base.Coin');bag.inv:AddItem(coin)
        body:getContainer():AddItem(bag)
        body.getWornItems=function() return {
            size=function() return shirt.unworn and 1 or 2 end,
            remove=function(_,item) if item==shirt then shirt.unworn=true end end,
            getItemByIndex=function(_,n) return not shirt.unworn and n==0 and shirt or bag end,
            getItemById=function(_,id) if id==shirt.id and not shirt.unworn then return shirt end end} end
        body.isPlayer=function() return playerBody==true end
        body.isSkeleton=function() return skeleton==true end
        r={body=body}
        function step(d)
            r.before={x=body:getX()-d,y=body:getY(),z=body:getZ()};CW.trail(r)
        end
        function contents()
            assert(body:getContainer():getItemWithID(600)==shirt)
            assert(bag.inv:getItems():get(0)==coin and bag:getContainer()==body:getContainer())
        end
    ''')


class ClothingWearTests(unittest.TestCase):
    def test_saved_broken_state_reapplies_after_missing_inventory(self):
        old=environment();setup(old)
        old.execute('for i=1,50 do step(4) end')
        saved=copy_packet(old.globals().body.md)
        fresh=environment();setup(fresh)
        fresh.globals().saved=fresh.table_from(saved,recursive=True)
        fresh.execute('''
            body.md=saved;shirt.condition=0;shirt.unworn=true
            local rows=CW.snapshot(body);assert(rows[1].condition==0)
            local inv=body:getContainer();local original=inv.getItemWithID
            inv.getItemWithID=function() return nil end
            assert(CW.apply(body,rows)==false)
            inv.getItemWithID=original;shirt.condition=10;shirt.unworn=false
            assert(CW.apply(body,rows));assert(CW.apply(body,rows))
            assert(shirt.condition==0 and shirt.unworn);contents()
        ''')

    def test_clothing_without_holes_can_still_break(self):
        l=environment();setup(l)
        l.execute('''
            shirt.getCanHaveHoles=function() return false end
            shirt.getCoveredParts=function() return nil end
            for i=1,50 do step(4) end
            assert(shirt.condition==0 and shirt.unworn and not shirt.holes[6]);contents()
        ''')

    def test_clean_dirty_torn_and_unworn_transitions(self):
        from test_cosmetic_wear import visuals
        l=environment();visuals(l);setup(l)
        l.execute('''
            BloodBodyPartType.Torso_Upper=1;skin.blood=0;skin.dirt=0
            assert(shirt.condition==10 and not shirt.unworn and skin.dirt==0)
            for i=1,5 do wearStep(1);step(1) end
            assert(skin.dirt>0 and shirt.condition==10)
            for i=1,15 do wearStep(1);step(1) end
            assert(shirt.condition==9 and shirt.holes[6]==1 and not shirt.unworn)
            for i=1,45 do wearStep(4);step(4) end
            assert(shirt.condition==0 and shirt.unworn and skin.dirt>0);contents()
        ''')

    def test_batched_wear_retains_distance_and_unwears_at_zero(self):
        l=environment();setup(l)
        l.execute('''
            function batch(d,t)
                r.before={x=body.x,y=body.y,z=body.z};r.effectDistance=d
                CW.trail(r,t);r.effectDistance=nil
            end
            batch(20,0);assert(shirt.condition==9)
            batch(20,500);batch(20,1000);assert(shirt.condition==9)
            batch(0,2000);assert(shirt.condition==7)
            batch(140,4000);assert(shirt.condition==0 and shirt.unworn);contents()
            local saved=CW.snapshot(body)
            assert(#saved==1 and saved[1].condition==0)
            shirt.condition=10;shirt.unworn=false;CW.apply(body,saved);CW.apply(body,saved)
            assert(shirt.condition==0 and shirt.unworn);contents()
        ''')

    def test_zero_condition_reaches_both_mp_clients_and_replays(self):
        n=Network()
        for l in [n.server,*n.clients.values()]: setup(l)
        n.server.execute('root=link(C,A,rope);for i=1,50 do step(4) end;publish()')
        packets=take(n.server,'packets')
        for p in packets: n.receive(p)
        for p in packets: n.receive(p)
        for c in n.clients.values():
            c.execute('assert(shirt.condition==0 and shirt.unworn);contents()')

    def test_failed_pose_commit_and_wear_failure_do_not_lose_items(self):
        l=environment();setup(l)
        l.execute('''
            link(C,A,rope);link(A,B,chain)
            local native=CVPWorldNative.move;local calls=0;local effects=0
            CW.trail=function() effects=effects+1;error('wear failure') end
            CVPWorldNative.move=function(...)
                calls=calls+1;if calls==2 then error('commit failure') end
                return native(...)
            end
            car.x=car.x+.4
            assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now));assert(effects==0)
            CVPWorldNative.move=native;Sim:tick(S.graph,S.index,.05,now);now=now+1000;Sim:tick(S.graph,S.index,.05,now)
            assert(effects==2 and not Sim.pendingPoses);contents()
        ''')

    def test_distance_protection_and_original_contents(self):
        l=environment();setup(l)
        l.execute('''
            for i=1,19 do step(1) end;assert(shirt.condition==10)
            step(1);assert(shirt.condition==9 and shirt.holes[6]==1);contents()
            for i=1,100 do step(4) end
            assert(shirt.condition==0 and shirt.unworn and not shirt.holes[7]);contents()
            shirt.condition=10;playerBody=true
            for i=1,20 do step(4) end;assert(shirt.condition==10)
            playerBody=false;skeleton=true;step(4);skeleton=false
            SandboxVars.CorpseProxyLab.ClothingWear=false
            for i=1,20 do step(4) end
            SandboxVars.CorpseProxyLab.ClothingWear=true
            for i=1,20 do step(0);step(100) end
            assert(shirt.condition==10);contents()
        ''')

    def test_saved_progress_resumes_and_client_never_simulates(self):
        l=environment();setup(l);l.execute('for i=1,19 do step(1) end')
        saved=copy_packet(l.globals().body.md)
        fresh=environment();setup(fresh)
        fresh.globals().saved=fresh.table_from(saved,recursive=True)
        fresh.execute('body.md=saved;step(1);assert(shirt.condition==9);contents()')
        fresh.execute('isClient=function() return true end;for i=1,100 do step(4) end;assert(shirt.condition==9)')

    def test_mp_current_handlers_two_clients_duplicates_and_player_guard(self):
        n=Network();s=n.server
        for l in [s,*n.clients.values()]: setup(l)
        s.execute('root=link(C,A,rope);for i=1,20 do step(1) end;publish()')
        packets=take(s,'packets')
        for p in packets: n.receive(p)
        for p in packets: n.receive(p)
        for c in n.clients.values():
            c.execute('assert(shirt.condition==9 and shirt.holes[6]==1);contents()')
            c.execute('''
                local W=require 'CVP_LinkWire';local row=CVPMPClient.rows.A.descriptor
                row.clothing[1].holes={99};assert(not W.body(row))
                playerBody=true;CW.apply(body,{{id=600,condition=1,holes={17}}})
                assert(shirt.condition==9 and not shirt.holes[17]);playerBody=false
            ''')
        n.clients['friend'].execute('shirt.condition=10;shirt.holes={};CVPMPClient.appearanceApplied[body]=nil')
        n.publish()
        n.clients['friend'].execute('assert(shirt.condition==9 and shirt.holes[6]==1);contents()')


if __name__=='__main__': unittest.main()
