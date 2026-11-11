"""Unified world-space timeline across tension, blockage and packet loss."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

class MotionTransitionTests(unittest.TestCase):
    def runtime(self):
        lua=LuaRuntime()
        lua.globals().M=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        lua.execute('''
            r={}
            function packet(t,taut,blocked)
                M.push(r,{x=t*.02-4,y=0,z=0,angle=0,vehicle=7,
                    anchorX=t*.02,anchorY=0,anchorZ=0,taut=taut,blocked=blocked},t)
            end
            for t=0,1000,100 do packet(t,true,false) end
        ''')
        return lua

    def test_taut_slack_taut_does_not_throw_forward_moving_body_back(self):
        for fps in (30,60,120,240):
            lua=self.runtime();lua.globals().fps=fps
            lua.execute('''
                local previous=M.pose(r,1000).x
                local nextPacket=1100
                for frame=1,fps*2 do
                    local t=1000+frame*1000/fps
                    if t>=nextPacket then packet(t,t>=1500,false);nextPacket=nextPacket+100 end
                    local x=M.pose(r,t).x
                    assert(x>=previous-1e-8,'forward towing reversed on mode transition')
                    assert(x-previous<=26/fps+1e-8,'mode transition jumped forward')
                    previous=x
                end
            ''')

    def test_stale_and_blocked_snapshots_have_bounded_transitions(self):
        for mode in ('stale','blocked'):
            lua=self.runtime();lua.globals().mode=mode
            lua.execute('''
                local previous=M.pose(r,1000).x
                for t=1010,3000,10 do
                    if mode=='blocked' and t%100==0 then packet(t,false,true) end
                    local x=M.pose(r,t).x
                    assert(math.abs(x-previous)<=.27+1e-8,'frame switch caused a jump')
                    previous=x
                end
                if mode=='stale' then assert(math.abs(previous-16)<1e-8,'stale offset never settled') end
                if mode=='blocked' then assert(math.abs(previous-(3000-250)*.02+4)<1e-8,'blocked body still follows live hitch') end
            ''')

    def test_chain_order_uses_updated_parent_for_arbitrary_ids(self):
        lua=self.runtime()
        lua.execute('''
            local links={}
            for _,id in ipairs({91,2,77,1}) do links[id]={id=id,target={}} end
            links[2].target.source=91;links[77].target.source=2;links[1].target.source=77
            local seen={};local rows=M.ordered(links)
            assert(#rows==4)
            for _,r in ipairs(rows) do
                assert(not r.target.source or seen[r.target.source],'child used previous-frame parent')
                seen[r.id]=true
            end
            links[91].target.source=1
            assert(#M.ordered(links)==0,'cyclic chain must not hang or partially update')
            links[91].target.source=999
            assert(#M.ordered(links)==4,'missing parent must not hide entire loaded tail')
        ''')

    def test_client_tick_places_parent_before_child_even_with_child_first_hash_order(self):
        from test_multiplayer import vm, copy_packet, deliver
        server=vm(True)
        server.execute("""
            assert(CVPMPServer.attach(player,body,car,rope))
            local root=CVPMPServer.links[1]
            assert(CVPMPServer.attach(player,body2,car,chain,'feet','body',body,root.connection.id))
            now=now+100;CVPMPServer.tick()
        """)
        packet=[copy_packet(p) for _,p in server.globals().packets.items() if p['name']=='state'][-1]
        client=vm(False);deliver(client,packet)
        client.execute("""
            CVPRopeScene.updateBody=function() end
            local originalPairs=pairs
            function pairs(t)
                if t~=CVPMPClient.links then return originalPairs(t) end
                local ids={body2.netID,body.netID};local i=0
                return function() i=i+1;local id=ids[i];if id then return id,t[id] end end
            end
            local seen=false
            require('CVP_Motion').pose=function(r,t,ax,ay,az)
                if r.id==body.netID then
                    seen=true;return {x=.5,y=0,z=0,angle=0}
                end
                assert(seen and body:getX()==.5,'child sampled parent before its movement')
                assert(math.abs(ax-(.5+r.target.sourceX))<1e-8,'child anchor used stale parent')
                return {x=0,y=0,z=0,angle=0}
            end
            now=now+100;CVPMPClient.tick()
            assert(seen)
        """)

if __name__=='__main__': unittest.main()
