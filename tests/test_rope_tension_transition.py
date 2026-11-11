"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class RopeTensionTransitionTests(unittest.TestCase):
    def test_tension_transition_has_no_snap(self):
        from pathlib import Path
        import sys
        from lupa.lua51 import LuaRuntime
        lua=LuaRuntime()
        lua.globals().Rope=lua.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua').read_text())
        lua.execute('''
        for _,fps in ipairs({30,60,120}) do
         local r={x=0,y=0,z=0,angle=math.pi,length=4,gear={getFullType=function() return 'Base.Rope' end}}
         local height=(Rope.anchorHeight-Rope.floorHeight)*3
         local before=Rope.footOffset+math.sqrt(3.989^2-height^2)
         local after=Rope.footOffset+math.sqrt(3.991^2-height^2)
         for i=1,600 do Rope.shape(r,before,0,0,1/60) end
         local p=r.ropePoints[math.max(2,math.floor(#r.ropePoints*.4))];local x,y,z=p.x,p.y,p.z
         Rope.shape(r,after,0,0,1/fps)
         local jump=math.sqrt((p.x-x)^2+(p.y-y)^2+(p.z-z)^2)
         print('threshold fps/jump',fps,jump)
         assert(jump<0.04,'interior node snapped across tension threshold')
         for i=1,fps do Rope.shape(r,after+0.1,0,0,1/fps) end
         local a,b=r.ropePoints[1],r.ropePoints[#r.ropePoints]
         local length=0
         for i=1,#r.ropePoints-1 do local p,q=r.ropePoints[i],r.ropePoints[i+1]
          length=length+math.sqrt((p.x-q.x)^2+(p.y-q.y)^2+(p.z-q.z)^2)
         end
         local direct=math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+(a.z-b.z)^2)
         assert(math.abs(length-direct)<0.0001,'taut rope never straightens')
         local fx,fy=Rope.feet(r)
         assert(math.abs(a.x-after-0.1)<0.000001 and math.abs(b.x-fx)<0.000001,'attachment lag')
        end
        ''')


if __name__ == '__main__':
    unittest.main()
