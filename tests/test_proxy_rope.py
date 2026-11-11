"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class ProxyRopeTests(unittest.TestCase):
    def test_towing_contacts_and_frame_rate_agreement(self):
        from pathlib import Path
        import sys
        from lupa.lua51 import LuaRuntime
        L=LuaRuntime()
        L.globals().Rope=L.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua').read_text())
        L.execute('''
        local r={vx=0,vy=0,ax=2,ay=0,angle=1}
        local x,y,taut=Rope.step(r,0,0,2,0,0.1)
        assert(x==0 and y==0 and not taut and r.angle==1,'slack must not pull or turn')
        x,y,taut=Rope.step(r,0,0,5,0,0.1)
        assert(x>0 and x<3 and taut,'body displacement must stay below the anchor travel')
        local fx,fy,fz=Rope.feet(r,x,y)
        assert(math.sqrt((5-fx)^2+fy^2+((Rope.anchorHeight-fz)*3)^2)<=4.00001,'actual foot tether stretched')
        assert(math.abs(r.angle-1)<=0.30001,'rotation rate limited')
        local a=r.angle
        r.ax=x;r.ay=y
        Rope.step(r,x,y,x,y,0.1)
        assert(r.angle==a,'slack must retain heading')
        function run(fps)
         local r={vx=0,vy=0,ax=4,ay=0,angle=0};local x,y=0,0
         for i=1,5*fps do x,y=Rope.step(r,x,y,4+6*i/fps,0,1/fps) end
         assert(x==x and x>25 and x<34,'finite stable towing')
         return x
        end
        local x30,x60,x120=run(30),run(60),run(120)
        assert(math.abs(x30-x120)<0.03 and math.abs(x60-x120)<0.03,'frame rate dependence')
        print('PASS slack, foot constraint, bounded turn, slack heading, 30/60/120 FPS agreement')
        local function pack(fps)
         local links={}
         for i=1,5 do links[i]={id=i,x=0,y=0,z=0,angle=math.pi,vx=0,vy=0,ax=4,ay=0,length=3.6+0.65*((i-1)%4)} end
         for frame=1,20*fps do
          local ax=4+frame/fps*3;local ay=math.sin(frame/fps*0.4)*3
          Rope.separate(links)
          for _,r in ipairs(links) do
           local oldX,oldY=r.x,r.y
           r.x,r.y=Rope.step(r,r.x,r.y,ax,ay,1/fps)
           assert((r.x-oldX)^2+(r.y-oldY)^2<1,'no separation teleport')
           assert((r.x-ax)^2+(r.y-ay)^2<18^2,'pack remains within tether break distance')
          end
         end
         local nearest=100
         for i=1,#links-1 do for j=i+1,#links do
          local a,b=links[i],links[j];local d=math.sqrt((a.x-b.x)^2+(a.y-b.y)^2)
          nearest=math.min(nearest,d)
         end end
         assert(nearest>0.65,'bodies converged: '..nearest)
         return links
        end
        local a,b=pack(30),pack(120)
        for i=1,#a do assert(math.abs(a[i].x-b[i].x)<0.25 and math.abs(a[i].y-b[i].y)<0.25,'contact frame-rate drift') end
        local a={x=0,y=0,z=0,angle=0};local b={x=0,y=0,z=1,angle=0}
        Rope.separate({a,b});assert(a.pushX==0 and a.pushY==0,'different floors do not collide')
        print('PASS five initially overlapping bodies separate under towing and turns; bounded movement; 30/120 FPS; floors isolated')
        ''')


if __name__ == '__main__':
    unittest.main()
