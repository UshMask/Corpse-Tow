"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class RopeGroundDragTests(unittest.TestCase):
    def test_ground_drag_and_finite_curve(self):
        from pathlib import Path
        from lupa.lua51 import LuaRuntime
        L=LuaRuntime();L.globals().Rope=L.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua').read_text())
        L.execute('''
        for _,kind in ipairs({'Base.Rope','Base.HeavyChain'}) do
        local r={x=4,y=0,z=0,angle=0,length=4,slot=1,gear={getFullType=function() return kind end}}
        for i=1,600 do Rope.shape(r,0,0,0,1/60) end
        local before={};for i,p in ipairs(r.ropePoints) do before[i]={x=p.x,y=p.y} end
        Rope.shape(r,.05,0,0,1/60)
        -- Inspect the far half of the interior, regardless of solver resolution.
        local max=0;for i=math.floor(#r.ropePoints/2)+2,#r.ropePoints-1 do local p=r.ropePoints[i];max=math.max(max,math.sqrt((p.x-before[i].x)^2+(p.y-before[i].y)^2)) end
        assert(max<0.001,'one endpoint moved the whole rope')
        for i=1,120 do Rope.shape(r,2*i/120,0,0,1/60) end
        local length=0
        for i=1,#r.ropePoints-1 do local a,b=r.ropePoints[i],r.ropePoints[i+1]
         length=length+math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+(a.z-b.z)^2)
        end
        assert(math.abs(length-r.length)<0.02,'compression changed length')
        local v=r.ropePoints
        assert(#v>=2)
        -- Rendered endpoints are checked against host samples in test_link_presentation.
        for _,p in ipairs(v) do
         for _,axis in ipairs({'x','y','z'}) do assert(p[axis]==p[axis] and math.abs(p[axis])<math.huge) end
         assert(p.z>=Rope.floorHeight*3)
        end
        print('PASS ground drag and finite curve',kind)
        end
        ''')


if __name__ == '__main__':
    unittest.main()
