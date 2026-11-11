"""Distance-based floor blood and commit/authority boundaries."""
import unittest
from test_link_runtime import environment


def setup():
    l = environment()
    l.execute('''
        Blood=require 'CVP_Blood';splats={}
        function addBloodSplat(sq,count,x,y)
            splats[#splats+1]={x=sq:getX()+x,y=sq:getY()+y,count=count}
        end
        body.isSkeleton=function() return skeleton==true end
        r={body=body,before={x=0,y=0,z=0}}
        function drag(x,y,z)
            r.before={x=body:getX(),y=body:getY(),z=body:getZ()}
            World.move(body,x,y,z or 0,gridSquare(math.floor(x),math.floor(y),z or 0))
            Blood.trail(r)
        end
        move(body,0,0)
    ''')
    return l


class BloodTrailTests(unittest.TestCase):
    def test_density_live_change_cap_and_client_authority(self):
        l=setup();l.execute('''
            for density=1,3 do
                SandboxVars.CorpseProxyLab.BloodTrailDensity=density
                r.effectDistance=2;splats={};Blood.trail(r)
                assert(#splats==1 and splats[1].count==2^(density-1))
                intact(body)
            end
            SandboxVars.CorpseProxyLab.BloodTrailDensity=1
            r.effectDistance=1.5;Blood.trail(r)
            SandboxVars.CorpseProxyLab.BloodTrailDensity=3
            r.effectDistance=0;splats={};Blood.trail(r);assert(#splats==0)
            r.effectDistance=100;Blood.trail(r);assert(#splats==1 and splats[1].count==4)
            isClient=function() return true end;splats={};Blood.trail(r);assert(#splats==0)
            intact(body)
        ''')

    def test_slow_motion_accumulates_distance_and_each_commit_is_bounded(self):
        l = setup(); l.execute('''
            for i=1,2500 do drag(i*.0005,0) end
            assert(#splats==1 and math.abs(splats[1].x-1)<1e-6)
            -- A carried fraction must not produce a fifth splat in a 4 m step.
            drag(1.75,0);splats={};drag(5.75,0)
            assert(#splats==4)
            for i,p in ipairs(splats) do assert(math.abs(p.x-(i+1))<1e-6) end
            intact(body)
        ''')

    def test_distance_not_ticks_and_stationary_has_no_blood(self):
        for step in (.1, .25, 1):
            l = setup(); l.globals().step = step
            l.execute('''
                for i=1,math.floor(3/step) do drag(i*step,0) end
                assert(#splats==3)
                for i,p in ipairs(splats) do assert(math.abs(p.x-i)<1e-6 and p.count==1) end
                for i=1,100 do drag(3,0) end
                assert(#splats==3);intact(body)
            ''')

    def test_skeleton_disabled_client_and_teleports_leave_no_trail(self):
        l = setup(); l.execute('''
            skeleton=true;drag(2,0);skeleton=false
            SandboxVars.CorpseProxyLab.BloodTrails=false;drag(4,0)
            SandboxVars.CorpseProxyLab.BloodTrails=true
            local client=isClient;isClient=function() return true end;drag(6,0);isClient=client
            drag(30,0);drag(31,0,1);assert(#splats==0)
            drag(32,0,1);assert(#splats==1)
        ''')

    def test_commit_failure_creates_no_blood_and_visual_error_keeps_bodies(self):
        l = setup(); l.execute('''
            link(C,A,rope);link(A,B,chain)
            local native=CVPWorldNative.move;local calls=0;local effects=0
            Blood.trail=function() effects=effects+1;error('visual failure') end
            CVPWorldNative.move=function(...)
                calls=calls+1;if calls==2 then error('commit failure') end
                return native(...)
            end
            car.x=car.x+.4
            assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now));assert(effects==0)
            CVPWorldNative.move=native
            Sim:tick(S.graph,S.index,.05,now);now=now+1000;Sim:tick(S.graph,S.index,.05,now)
            assert(effects==2 and not Sim.pendingPoses);intact(body);intact(body2)
        ''')


if __name__ == '__main__':
    unittest.main()
