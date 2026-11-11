"""Physics-time anchors must not turn steady sliding into repeated load resets."""
import unittest
from test_link_simulation import environment


class LoadSamplingTests(unittest.TestCase):
    def test_acceleration_retains_load_at_different_fps_and_releases_slack(self):
        for fps in (30, 60, 144, 300):
            for spread in (False, True):
                for server in (False, True):
                    with self.subTest(fps=fps, spread=spread, server=server):
                        l=environment()
                        l.globals().fps=fps
                        l.globals().spread=spread
                        l.globals().server=server
                        l.execute('''
                            local Geometry=require 'CVP_Geometry'
                            Geometry.anchor=function(v) return v.x,v.y,0 end
                            SandboxVars.CorpseProxyLab.BodySpread=spread
                            SandboxVars.CorpseProxyLab.BodySpreadWidth=2
                            SandboxVars.CorpseProxyLab.BodySpreadStrength=2
                            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=0
                            ids={};gears={}
                            for i=3,32 do
                                local b=corpse();b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
                                b.getSquare=body.getSquare;b.setSquare=body.setSquare
                                b.getAngle=function(s) return s.angle or 0 end
                                b.world=false;sq:addCorpse(b)
                            end
                            H.discover()
                            for i,b in ipairs(bodies) do
                                local gear=item(i%2==0 and 'Base.Rope' or 'Base.HeavyChain')
                                storage:AddItem(gear);gears[i]=gear
                                ids[i]=link(C,{kind='body',key=b.md.CVPBodyKey,point='feet'},gear)
                            end
                            isServer=function() return server end
                            car.getNetPlayerId=function() return 1 end
                            car.getCurrentSpeedKmHour=function() return speed*3.6 end
                            local packet,lastClock
                            CVPVehicleMotion={localTime=function() return clock end,
                                sample=function() return packet end}
                            local total=0;local count=0
                            for i=1,fps*8 do
                                now=i/fps*1000;clock=math.floor(now/10+1e-8)*10
                                local t=clock/1000
                                speed=math.min(25,t*12.5)
                                car.x=t<2 and 6.25*t*t or 25*(t-1)
                                if server and (not lastClock or clock-lastClock>=50) then
                                    packet={time=clock,owner=1,speed=speed,z=0,
                                        hitchX=car.x,hitchY=0,frontX=car.x+4,frontY=0}
                                    lastClock=clock
                                end
                                local requests,loads=Sim:tick(S.graph,S.index,1/fps,now)
                                assert(#requests==0,'unexpected detach')
                                if i>fps*5 then total=total+(loads[car] or 0);count=count+1 end
                            end
                            local mass=0
                            for _,r in pairs(Sim.records) do mass=mass+r.mass end
                            assert(total/count>mass*.95,'sliding load collapsed: '..total/count..' / '..mass)
                            -- A stationary, genuinely slack configuration, not a coasting
                            -- body which can cross the car and tension the opposite side.
                            speed=0
                            for _,r in pairs(Sim.records) do
                                move(r.body,car.x-1,0);r.vx=0;r.vy=0
                            end
                            for i=1,fps*3 do
                                now=now+1000/fps;clock=clock+1000/fps
                                packet={time=clock,owner=1,speed=0,z=0,hitchX=car.x,hitchY=0}
                                local requests,loads=Sim:tick(S.graph,S.index,1/fps,now)
                                if i>fps*2 then assert(not loads[car] or loads[car]==0,'slack still loads car') end
                            end
                            for i,b in ipairs(bodies) do
                                assert(worldCount(b)==1 and b.inv:getItems():size()==1)
                                assert(E.get(S.graph.links[ids[i]].equipment)==gears[i])
                            end
                        ''')

