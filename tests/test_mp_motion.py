"""Snapshot interpolation contracts; no game or network mutations."""
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

class MotionTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime()
        self.lua.globals().M=self.lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        self.lua.execute('''
            r={}
            function push(t,x,y,a,z,v)
                M.push(r,{x=x,y=y or 0,z=z or 0,angle=a or 0,vehicle=v or 7},t)
            end
        ''')

    def test_constant_speed_without_packet_rate_pulses(self):
        self.lua.execute('''
            for t=0,1000,100 do push(t,t/100) end
            for t=600,1200,10 do
                local p=M.pose(r,t)
                assert(math.abs(p.x-(t-M.delay)/100)<1e-8)
            end
            assert(#r.samples<=M.capacity)
        ''')

    def test_loss_holds_last_pose_without_runaway_prediction(self):
        self.lua.execute('''
            push(0,0);push(200,1);push(400,2)
            for t=650,5000,10 do assert(M.pose(r,t).x==2) end
            push(5001,3);assert(#r.samples==1 and M.pose(r,5001).x==3)
        ''')

    def test_turn_wrap_and_discontinuities(self):
        self.lua.execute('''
            push(0,0,0,math.pi-.1);push(100,1,0,-math.pi+.1)
            assert(math.abs(M.pose(r,M.delay+50).angle-math.pi)<1e-8)
            push(200,100);assert(#r.samples==1 and M.pose(r,200).x==100)
            push(300,101,0,0,1);assert(#r.samples==1 and M.pose(r,300).z==1)
            push(400,102,0,0,1,8);assert(#r.samples==1)
        ''')

    def test_batched_arrivals_and_reused_output(self):
        self.lua.execute('''
            push(0,0);push(0,1);assert(#r.samples==1)
            push(100,2)
            local p=M.pose(r,300);assert(p==M.pose(r,310))
            assert(p.x==p.x and p.angle==p.angle)
        ''')

    def test_correction_follows_sample_time_without_second_velocity_filter(self):
        self.lua.execute('''
            push(0,0);M.pose(r,250);push(133,15)
            local last=0
            for t=266,2000,16 do
                local p=M.pose(r,t)
                assert(math.abs(p.x-15*math.min(1,(t-250)/133))<1e-8)
                assert(p.x>=last and p.x<=15)
                last=p.x
            end
            assert(last==15)
        ''')

class HitchMotionTests(unittest.TestCase):
    def test_endpoint_height_uses_the_body_playback_time(self):
        lua=LuaRuntime()
        lua.globals().M=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        lua.execute('''
            local graph={links={rope={revision=1,
                a={kind='vehicle',key='car',x=0,y=0,z=.3},
                b={kind='ground',x=-2,y=0,z=.025}}}}
            local rows=M.pushEndpoints(nil,graph,100,false)
            graph.links.rope.a={kind='vehicle',key='car',x=2,y=0,z=.5}
            rows=M.pushEndpoints(rows,graph,200,false)
            local p=M.endpoints(rows,150+M.delay).rope.a
            assert(math.abs(p.x-1)<1e-9 and math.abs(p.z-.4)<1e-9,
                'moving hitch must interpolate in the same snapshot interval')
            assert(#rows.rope.a.samples==2,'height change discarded endpoint history')
            graph.links.rope.revision=2
            graph.links.rope.a={kind='ground',x=5,y=0,z=.025}
            rows=M.pushEndpoints(rows,graph,300,false)
            assert(#rows.rope.a.samples==1,'detach must reset attachment history')
            assert(M.endpoints(rows,300).rope.a.x==5)
            local display=M.endpoints(rows,300)
            assert(M.endpoints(rows,310,nil,display)==display,'frame map should be reused')
            M.endpoints({},320,nil,display)
            assert(next(display)==nil,'removed ropes survived in the reused map')
        ''')

    def test_physical_poses_use_same_world_timeline_in_all_states(self):
        lua=LuaRuntime()
        lua.globals().M=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        lua.execute("""
            function record(taut,blocked)
                local r={}
                for t=0,1000,100 do M.push(r,{x=t*.02-4,y=0,z=0,angle=0,vehicle=7,
                    anchorX=t*.02,anchorY=0,anchorZ=0,taut=taut,blocked=blocked},t) end
                return r
            end
            local r=record(true,false)
            local p=M.pose(r,1000)
            assert(math.abs(p.x-11)<1e-6,'taut body must use the same timeline as the rest')
            assert(r.samples[#r.samples].x==16,'authoritative sample was mutated')
            for _,mode in ipairs({{false,false},{true,true}}) do
                local p=M.pose(record(mode[1],mode[2]),1000)
                assert(math.abs(p.x-11)<1e-6,'slack or blocked body must remain in world space')
            end
            assert(M.pose(record(true,false),1400).x==16,'packet loss must not keep towing the body')
            assert(M.pose(record(true,false),1000,0).x==16,'explicit zero delay must select latest pose')
        """)

    def test_live_hitch_never_translates_confirmed_body_playback(self):
        lua=LuaRuntime()
        lua.globals().M=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        lua.execute("""
            CVPBodyPresentation={stockSupported=function() return true end}
            local liveX=20
            local host={enabled=function() return true end,
                sample=function() return {x=liveX,y=0,z=0} end}
            local root={target={anchor={kind='vehicle',key='car'}}}
            local child={target={source='root'}}
            local rows={root=root,child=child}
            for t=0,1000,100 do
                M.push(root,{x=t*.02-4,y=0,z=0,angle=0,vehicle=7,
                    anchorX=t*.02,anchorY=0,anchorZ=0,sourceSampledAt=t},t)
                M.push(child,{x=t*.02-7,y=0,z=0,angle=0,vehicle=7},t)
            end
            local p=M.pose(root,1000);local q=M.pose(child,1000)
            assert(p.x==11 and q.x==8 and p.anchorX==15)
            M.begin(host,750);M.present(root,p,rows,host);M.present(child,q,rows,host)
            assert(root.drawDX==0 and child.drawDX==0,'live hitch must not translate delayed bodies')
            assert((p.x+root.drawDX)-(q.x+child.drawDX)==3,'alignment changed body spacing')
            liveX=22
            M.begin(host,750);M.present(root,p,rows,host);M.present(child,q,rows,host)
            assert(root.drawDX==0 and child.drawDX==0)
            assert(p.x==11 and q.x==8 and root.samples[#root.samples].x==16,
                'render alignment changed physical pose or authoritative history')
            M.begin(host,1000,true);M.present(root,p,rows,host);M.present(child,q,rows,host)
            assert(root.drawDX==0 and child.drawDX==0,'SP must not chase an unsolved live hitch')
            M.begin(host,2000);M.present(root,p,rows,host);M.present(child,q,rows,host)
            assert(not root.visualRecovery and not child.visualRecovery,'network recovery owns stale state, not draw offsets')
            assert(root.drawDX==0 and child.drawDX==0 and p.x==11 and q.x==8)
        """)

if __name__=='__main__': unittest.main()
