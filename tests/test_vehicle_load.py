"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class VehicleLoadTests(unittest.TestCase):
    def test_force_queue_and_load_ramp(self):
        """Resistance through B42's force queue, including the 100 Hz consume/clear step.

        This models the inspected Java queue contract, not a running Bullet car/engine.
        """
        from pathlib import Path
        import sys
        from lupa.lua51 import LuaRuntime

        L = LuaRuntime()
        L.globals().Load = L.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Load.lua').read_text())
        L.execute('''
        networkMode='client'
        CVPWorldNative={applyVehicleResistance=function(v,amount)
         local speed=math.sqrt(v.vx*v.vx+v.vz*v.vz)
         v:applyImpulseGeneric(v:getX(),v:getY(),v:getZ(),-v.vx/speed,-v.vz/speed,0,amount)
        end}
        function isClient() return networkMode=='client' end
        function isServer() return networkMode=='server' end
        Vector3f={new=function() return {} end}
        function vehicle(vx,vz,mass,offroad,owner)
         local v={vx=vx,vz=vz,mass=mass,queuedX=0,queuedZ=0,calls=0}
         v.isLocalPhysicSim=function() return owner~=false end
         v.isDoingOffroad=function() return offroad end
         v.getMass=function(s) return s.mass end
         v.getX=function() return 12 end;v.getY=function() return 34 end;v.getZ=function() return 0 end
         v.getLinearVelocity=function(s) return {x=function() return s.vx end,z=function() return s.vz end} end
         v.applyImpulseGeneric=function(s,x,y,z,dx,dy,dz,amount)
          assert(x==12 and y==34 and z==0 and dz==0,'resistance must stay central and horizontal')
          local length=math.sqrt(dx*dx+dy*dy)
          assert(length>0 and amount>0 and amount==amount)
          s.queuedX=s.queuedX+dx/length*amount;s.queuedZ=s.queuedZ+dy/length*amount;s.calls=s.calls+1
         end
         return v
        end
        function simulate(fps,count,offroad,vx,vz,carMass,apply)
         local v=vehicle(vx or 20,vz or 0,carMass or 1200,offroad)
         local frame,step=1,1
         while math.min(frame/fps,step/100)<=2+1e-8 do
          if frame/fps<=step/100+1e-8 then
           (apply or Load.apply)(v,75*count,1/fps);frame=frame+1
          else
           -- Native code converts the queued vector to force * 30, then consumes it
           -- for one 0.01-second step. Further substeps receive no queued force.
           v.vx=v.vx+v.queuedX*30*0.01/v.mass;v.vz=v.vz+v.queuedZ*30*0.01/v.mass
           v.queuedX=0;v.queuedZ=0;step=step+1
           assert(v.vx*(vx or 20)>=-1e-9,'resistance reversed longitudinal motion')
          end
         end
         return v
        end
        local empty=simulate(60,0);local one=simulate(60,1);local five=simulate(60,5);local ten=simulate(60,10)
        assert(empty.vx==20 and one.vx<empty.vx and five.vx<one.vx and ten.vx<five.vx and ten.vx>=0,
            'resistance must scale with load without reversing motion')
        for _,fps in ipairs({30,60,120,240}) do
         local v=simulate(fps,5)
         assert(math.abs(v.vx-five.vx)<0.02,'FPS-dependent drag at '..fps)
         local overload=simulate(fps,1000000,false,0.5)
         assert(overload.vx>=0 and overload.vx<0.03,'heavy load must stop safely at '..fps)
        end
        assert(math.abs(simulate(60,5,true).vx-five.vx)<1e-8,'force payload must not be amplified again')
        assert(simulate(60,5,false,20,0,2400).vx>five.vx,'heavy vehicle loses less speed')
        local backwards=simulate(60,5,false,-20)
        assert(math.abs(backwards.vx+five.vx)<0.001,'reverse drag must be symmetric')
        local diagonal=simulate(60,5,false,12,16)
        assert(math.abs(math.sqrt(diagonal.vx^2+diagonal.vz^2)-five.vx)<0.001,'direction must not change magnitude')
        assert(math.abs(diagonal.vx/diagonal.vz-0.75)<0.0001,'no unintended sideways push')
        local zero=vehicle(0,0,1200,false);Load.apply(zero,375,0.1);assert(zero.calls==0,'rest cannot create motion')
        local paused=vehicle(10,0,1200,false);Load.apply(paused,375,0);assert(paused.calls==0,'paused time cannot add resistance')
        local remote=vehicle(10,0,1200,false,false);Load.apply(remote,375,0.1);assert(remote.calls==0,'observer cannot apply physics')
        -- Actual B42 SP car observed with a driver: authority=Server, localPhysicSim=false.
        -- This network-authority flag must not suppress single-player resistance.
        networkMode='sp'
        local solo=vehicle(10,0,1323,false,false);Load.apply(solo,600,1/60)
        assert(solo.calls==1 and solo.queuedX<0,'SP must apply drag despite false network authority flag')
        networkMode='server'
        local serverRemote=vehicle(10,0,1323,false,false);Load.apply(serverRemote,600,1/60)
        assert(serverRemote.calls==0,'server must still reject a remotely simulated car')
        networkMode='client'
        local noMass=vehicle(10,0,0,false);Load.apply(noMass,375,0.1);assert(noMass.calls==0)

        -- Protect the native queue conversion without fixing the gameplay friction.
        local probe=vehicle(20,0,1200,false)
        local expected=Load.impulse(375,20,1200,1/60)
        Load.apply(probe,375,1/60)
        assert(expected>0 and math.abs(-probe.queuedX*.3-expected)<1e-8,'native impulse conversion')
        print(string.format('COAST MODEL, 1200 kg, 72 km/h start, 2 s: 0/1/5/10 bodies = %.2f / %.2f / %.2f / %.2f km/h',empty.vx*3.6,one.vx*3.6,five.vx*3.6,ten.vx*3.6))
        print('PASS body count, terrain, vehicle mass, 30/60/120/240 FPS, reverse/diagonal, zero speed/time, huge loads, local physics owner')
        ''')

    def test_tension_ramp_is_smooth_and_frame_rate_independent(self):
        from pathlib import Path
        from lupa.lua51 import LuaRuntime
        L = LuaRuntime()
        L.globals().Load = L.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Load.lua').read_text())
        L.execute("""
        local reference
        for _,fps in ipairs({30,60,120}) do
         local r={mass=100}
         local first=Load.tension(r,true,1/fps)
         assert(first>0 and first<20,'no full load on first frame')
         for i=2,fps do
          local before=r.loadMass;local after=Load.tension(r,true,1/fps)
          assert(after>=before and after<=100,'load ramp must approach its target without overshoot')
         end
         assert(r.loadMass>90,'load does not build within one second')
         if reference then assert(math.abs(r.loadMass-reference)<1,'load ramp depends on FPS') end
         reference=r.loadMass
         local before=r.loadMass;assert(Load.tension(r,true,0)==before,'pause changes active load')
         assert(Load.tension(r,false,1/fps)==0,'slack must stop resistance immediately')
         assert(Load.tension(r,true,0)==0,'pause must not increase load')
        end
        print('PASS gradual load at 30/60/120 FPS, immediate slack release and pause')
        """)


if __name__ == '__main__':
    unittest.main()
