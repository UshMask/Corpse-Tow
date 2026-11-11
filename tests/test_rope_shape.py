"""Curve behavior, independent of tessellation and solver implementation."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


class RopeShapeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.globals().Rope = self.lua.execute(Path(
            'CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua').read_text())
        self.lua.execute('''
            function distance(a,b)
                return math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+(a.z-b.z)^2)
            end
            function arc(points)
                local length=0
                for i=2,#points do length=length+distance(points[i-1],points[i]) end
                return length
            end
            function check(r,ax,ay)
                assert(#r.ropePoints>=2)
                local a,b=r.ropePoints[1],r.ropePoints[#r.ropePoints]
                local fx,fy,fz=Rope.feet(r)
                assert(distance(a,{x=ax,y=ay,z=Rope.anchorHeight*3})<1e-5,'car endpoint drift')
                assert(distance(b,{x=fx,y=fy,z=fz*3})<1e-5,'foot endpoint drift')
                for _,p in ipairs(r.ropePoints) do
                    for _,axis in ipairs({'x','y','z'}) do
                        assert(p[axis]==p[axis] and math.abs(p[axis])<math.huge,'non-finite rope')
                    end
                    assert(p.z>=Rope.floorHeight*3-1e-6,'rope below ground')
                end
            end
            function snapshot(r)
                local out={}
                for i,p in ipairs(r.ropePoints) do out[i]={x=p.x,y=p.y,z=p.z} end
                return out
            end
            -- Compare geometry along arc length, not matching node indices.
            function sample(points,t)
                local target=arc(points)*t;local walked=0
                for i=2,#points do
                    local a,b=points[i-1],points[i];local d=distance(a,b)
                    if d>0 and walked+d>=target then
                        local f=(target-walked)/d
                        return {x=a.x+(b.x-a.x)*f,y=a.y+(b.y-a.y)*f,z=a.z+(b.z-a.z)*f}
                    end
                    walked=walked+d
                end
                return points[#points]
            end
            function curveDrift(a,b)
                local drift=0
                for i=0,32 do drift=math.max(drift,distance(sample(a,i/32),sample(b,i/32))) end
                return drift
            end
            function settled(kind)
                local r={x=1.5,y=0,z=0,angle=0,length=4,slot=1,
                    gear={getFullType=function() return kind end}}
                for i=1,600 do Rope.shape(r,0,0,0,1/60);check(r,0,0) end
                return r
            end
        ''')

    def test_stationary_curve_sleeps_and_wakes_for_motion_or_length(self):
        self.lua.execute("""
            local r=settled('Base.Rope')
            assert(r.ropeSleeping,'stationary rope did not sleep')
            local before=snapshot(r)
            for i=1,120 do Rope.shape(r,0,0,0,1/60) end
            for i,p in ipairs(r.ropePoints) do assert(distance(p,before[i])==0) end
            Rope.shape(r,.02,0,0,1/60)
            assert(not r.ropeSleeping);check(r,.02,0)
            for i=1,600 do Rope.shape(r,.02,0,0,1/60) end
            assert(r.ropeSleeping)
            r.length=r.length+.5;Rope.shape(r,.02,0,0,1/60)
            assert(not r.ropeSleeping)
        """)

    def test_slack_retains_length_and_settles_on_ground(self):
        for kind in ('Base.Rope', 'Base.HeavyChain'):
            with self.subTest(material=kind):
                self.lua.globals().kind = kind
                self.lua.execute('''
                    local r=settled(kind)
                    assert(math.abs(arc(r.ropePoints)-r.length)<.04,'slack lost paid-out length')
                    local grounded=0
                    for i=1,31 do
                        if sample(r.ropePoints,i/32).z<Rope.floorHeight*3+.01 then grounded=grounded+1 end
                    end
                    assert(grounded/31>=.6,'slack does not rest on ground')
                    local before=snapshot(r)
                    for i=1,60 do Rope.shape(r,0,0,0,1/60);check(r,0,0) end
                    assert(curveDrift(before,r.ropePoints)<.01,'settled rope keeps drifting')
                    Rope.shape(r,.1,0,0,1/60);check(r,.1,0)
                ''')

    def test_pause_preserves_curve(self):
        self.lua.execute('''
            local r=settled('Base.Rope');local before=snapshot(r)
            Rope.shape(r,0,0,0,0)
            assert(curveDrift(before,r.ropePoints)<1e-8,'pause changes curve')
        ''')

    def test_slow_frame_keeps_curve_finite_and_recovers(self):
        self.lua.execute('''
            local r=settled('Base.Rope')
            Rope.shape(r,.1,0,0,.1);check(r,.1,0)
            for i=1,600 do Rope.shape(r,.1,0,0,1/60);check(r,.1,0) end
            assert(math.abs(arc(r.ropePoints)-r.length)<.04,'slow frame lost rope length')
        ''')

    def test_turn_reverse_and_frame_rate_agreement(self):
        self.lua.execute('''
            function drive(fps)
                local r={x=0,y=0,z=0,angle=math.pi,length=3.6,slot=1,ax=4,ay=0,vx=0,vy=0}
                local maxStretch=0
                for i=1,12*fps do
                    local time=i/fps
                    local ax=4+math.min(time,6)*5;local ay=2*math.sin(math.min(time,6)*.8)
                    if time>8 then ax=ax-(time-8)*2 end
                    r.x,r.y=Rope.step(r,r.x,r.y,ax,ay,1/fps,0)
                    Rope.shape(r,ax,ay,0,1/fps);check(r,ax,ay)
                    local fx,fy,fz=Rope.feet(r)
                    local d=math.sqrt((ax-fx)^2+(ay-fy)^2+((Rope.anchorHeight-fz)*3)^2)
                    if time>2 then maxStretch=math.max(maxStretch,d-r.length) end
                end
                assert(maxStretch<.0001,'rubber-band stretch under towing')
                assert(math.abs(arc(r.ropePoints)-r.length)<.12,'curve length drift under turns/reversal')
                return r
            end
            local a,b=drive(30),drive(120)
            assert(math.abs(a.x-b.x)+math.abs(a.y-b.y)<.03,'body dynamics depend on FPS')
            assert(curveDrift(a.ropePoints,b.ropePoints)<.3,'rope shape depends excessively on FPS')
        ''')

    def test_overstretched_save_takes_up_without_teleport(self):
        self.lua.execute('''
            local r={x=0,y=0,z=0,angle=math.pi,length=3.6,ax=7,ay=0,vx=0,vy=0}
            local x,y=Rope.step(r,0,0,7,0,1/60,0)
            assert(math.sqrt(x*x+y*y)<.1,'initial slack takeup snapped the body')
        ''')


if __name__ == '__main__':
    unittest.main()
