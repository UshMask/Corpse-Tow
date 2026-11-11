import unittest
from test_link_runtime import environment
from test_link_multiplayer import Network, take


def visuals(l):
    l.execute('''
        Wear=require 'CVP_Abrasion';BloodBodyPartType={Torso_Upper=1}
        body.isSkeleton=function() return skeleton==true end
        skin={blood=.2,dirt=.1}
        skin.getBlood=function(s) return s.blood end
        skin.getDirt=function(s) return s.dirt end
        skin.setBlood=function(s,part,n) s.blood=math.floor(n*255)/255 end
        skin.setDirt=function(s,part,n) s.dirt=math.floor(n*255)/255 end
        body.getHumanVisual=function() return skin end
        r={body=body}
        function wearStep(distance)
            r.before={x=body:getX()-distance,y=body:getY(),z=body:getZ()}
            Wear.trail(r)
        end
    ''')


class CosmeticWearTests(unittest.TestCase):
    def test_distance_guards_limits_and_items(self):
        l=environment();visuals(l)
        l.execute('''
            for i=1,10 do wearStep(.5) end
            assert(skin.blood>.24 and skin.dirt>.19);intact(body)
            local before=Wear.snapshot(body)
            for i=1,50 do wearStep(0) end
            wearStep(10);skeleton=true;wearStep(3);skeleton=false
            SandboxVars.CorpseProxyLab.CosmeticWear=false;wearStep(3)
            SandboxVars.CorpseProxyLab.CosmeticWear=true
            local client=isClient;isClient=function() return true end;wearStep(3);isClient=client
            assert(skin.blood==before.blood and skin.dirt==before.dirt)
            for i=1,100 do wearStep(4) end
            assert(skin.blood==1 and skin.dirt==1);intact(body)
        ''')

    def test_commit_failure_and_cosmetic_exception_preserve_bodies(self):
        l=environment();visuals(l)
        l.execute('''
            link(C,A,rope);link(A,B,chain)
            local native=CVPWorldNative.move;local calls=0;local effects=0
            Wear.trail=function() effects=effects+1;error('cosmetic failure') end
            CVPWorldNative.move=function(...)
                calls=calls+1;if calls==2 then error('commit failure') end
                return native(...)
            end
            car.x=car.x+.4
            assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now));assert(effects==0)
            CVPWorldNative.move=native;Sim:tick(S.graph,S.index,.05,now);now=now+1000;Sim:tick(S.graph,S.index,.05,now)
            assert(effects==2 and not Sim.pendingPoses);intact(body);intact(body2)
        ''')

    def test_server_snapshot_two_clients_replay_and_invalid_values(self):
        n=Network();s=n.server
        for l in [s,*n.clients.values()]: visuals(l)
        s.execute('root=link(C,A,rope);for i=1,10 do wearStep(.5) end;publish()')
        packets=take(s,'packets')
        for packet in packets: n.receive(packet)
        for c in n.clients.values():
            self.assertEqual(c.globals().skin.blood,s.globals().skin.blood)
            self.assertEqual(c.globals().skin.dirt,s.globals().skin.dirt)
        for packet in packets: n.receive(packet)
        for c in n.clients.values():
            self.assertEqual(c.globals().skin.blood,s.globals().skin.blood)
            c.execute('''
                local row=CVPMPClient.rows.A.descriptor
                local W=require 'CVP_LinkWire'
                row.cosmetic={blood=0/0,dirt=0};assert(not W.body(row))
                row.cosmetic={blood=0,dirt=2};assert(not W.body(row))
                row.cosmetic=nil;assert(W.body(row))
                assert(body:getContainer():getItems():size()>0)
            ''')
        # A client which missed previous cosmetic updates catches up from the
        # full state, without replaying travelled distance or consuming items.
        n.clients['friend'].execute('skin.blood=0;skin.dirt=0;CVPMPClient.appearanceApplied[body]=nil')
        n.publish()
        self.assertEqual(n.clients['friend'].globals().skin.blood,s.globals().skin.blood)


if __name__=='__main__': unittest.main()
