"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class RopeElasticityTests(unittest.TestCase):
    def test_rope_compliance_and_rigid_chain(self):
        from pathlib import Path
        import sys
        from lupa.lua51 import LuaRuntime
        lua=LuaRuntime()
        lua.globals().Rope=lua.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua').read_text())
        lua.execute('''
        local function run(kind,fps)
         local length=4;local height=(Rope.anchorHeight-Rope.floorHeight)*3
         local start=Rope.footOffset+math.sqrt(length*length-height*height)
         local r={x=0,y=0,z=0,angle=math.pi,vx=0,vy=0,ax=start,ay=0,length=length,
           gear=kind and {getFullType=function() return kind end}}
         local stretch,first,peakVelocity=0,0,0
         for i=1,8*fps do
          local t=i/fps;local travel=math.min(t,3)*3
          local ax=start+travel
          r.x,r.y=Rope.step(r,r.x,r.y,ax,0,1/fps,0)
          local fx,fy,fz=Rope.feet(r)
          local extension=math.sqrt((ax-fx)^2+fy*fy+height*height)-length
          stretch=math.max(stretch,extension)
          if i==1 then first=r.x end
          peakVelocity=math.max(peakVelocity,math.abs(r.vx))
          assert(extension<=0.200001,'excessive rubber-band stretch')
          if i>5*fps then assert(math.abs(r.vx)<0.01,'recoil does not settle') end
         end
         return r,stretch,first,peakVelocity
        end
        local previous
        for _,fps in ipairs({30,60,120}) do
         local r,stretch,first,peak=run('Base.Rope',fps)
         local c,cs,cf=run('Base.HeavyChain',fps)
         local hook,hs,hf=run('Base.HeavyChain_Hook',fps)
         local legacy,ls,lf=run(nil,fps)
         print('fps/rope stretch/initial pull vs chain',fps,stretch,first,cf)
         assert(stretch>0.025 and cs<0.000001,'rope and chain must differ under load')
         assert(first<cf*0.7,'take-up was not softened')
         assert(c.x==legacy.x and hook.x==legacy.x and cf==lf and hf==lf,'chain behavior changed')
         assert(peak<4,'excessive recoil velocity')
         if previous then assert(math.abs(previous.x-r.x)<0.04,'elasticity depends on FPS') end
         previous=r
        end
        ''')


if __name__ == '__main__':
    unittest.main()
