from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


def fixture(mode):
    lua=LuaRuntime()
    lua.execute('''
        now=0;handlers={};require=function() return {register=function(n,f) handlers[n]=f end,
            complete=function(id,ok,result) completed={ok=ok,result=result} end} end
        Events={OnTick={Add=function(f) ownerTick=f end},OnRenderTick={Add=function(f) tick=f end}}
        marks={};CVPBenchmarkNative={benchmarkOwnerLost=function() return ownerLost end,gameProfilerTick=function() end,milliseconds=function() return now end,heapMB=function() return 100 end,
            phase=function(id,phase) marks[#marks+1]={id=id,phase=phase,at=now} end}
        PZTDrivingInput={setTargetSpeed=function(s) speed=s end,begin=function() started=true end,stop=function() stopped=true end,release=function() end}
        getCore=function() return {setFramerate=function(_,n) fpsCap=n end} end
        Viewpoint={FrameCaps={active=function() return true end,setGameCap=function(n) viewCap=n end}}
        PZTPresentedFrames={valid=function() return not invalidDisplay end,cancel=function() captureCancelled=true end,begin=function() end,finish=function() return 'frame_ms,tick_ms,heap_mb\\n10,0,0' end}
        local fuel={setContainerContentAmount=function() end,getContainerCapacity=function() return 100 end}
        car={x=0,repair=function() end,getPartById=function() return fuel end,createVehicleKey=function() return {} end,
            setPhysicsActive=function() end,isDriver=function() return true end,isEngineRunning=function() return true end,
            getX=function(self) return self.x end,getY=function() return 0 end,getCurrentSpeedKmHour=function() return 0 end}
        player={getInventory=function() return {AddItem=function() return {getID=function() return 123 end} end} end,getVehicle=function(self) return self.car end}
        getPlayer=function() return player end
        ISVehicleMenu={processEnter=function(p,v) p.car=v end,onExit=function(p) p.car=nil end}
        ISStartVehicleEngine={new=function() return {} end};ISTimedActionQueue={add=function() end}
        getGameSpeed=function() return 1 end;MainScreen={instance={inGame=false}}
        getFileWriter=function(name) return {write=function(_,text) if name=='PZTDrive-test.txt' then csv=text end end,close=function() end} end
        body={x=0,getX=function(self) return self.x end,getY=function() return 0 end,getAngle=function() return 0 end,
            getSquare=function() return {} end,getStaticMovingObjectIndex=function() return 0 end}
        function settle()
            for i=1,20 do now=now+1000;tick();if completed then return end end
            error('driver cycle did not finish after stopping')
        end
        CVPBenchmark={vehicle=car,bodies={body},links={'link'},acceptanceVehicle={x=0,y=0},acceptancePositions={{x=0,y=0}}}
    ''')
    lua.globals().CVPBenchmark['perf']=mode
    if mode=='Tow':
        lua.execute('''CVPRuntime={authority={host={sample=function(e) return e end},simulation={groups={}},loads={},
            service={graph={links={link={a={x=0,y=0},b={x=2,y=0},length=2}}}}}}''')
    lua.execute(Path('tests/scenarios/corpse-tow/CVP_Drive.lua').read_text())
    return lua


class DrivingTests(unittest.TestCase):
    def test_express_waits_for_load_then_samples_three_seconds(self):
        lua=fixture('Tow')
        lua.execute("""
            CVPBenchmark.perfConfig={warmup=1000,sample=3000,speed=8,express=true}
            handlers['scene.drive']('fps','test');tick()
            now=1000;car.x=1;tick();assert(not captureStarted)
            body.x=.2;now=1250;tick()
            now=2250;tick()
            for i=1,12 do now=2250+i*250;car.x=1+i*.1;body.x=.2+i*.1;tick() end
            now=5500;tick();now=5750;tick()
        """)
        self.assertTrue(lua.globals().completed['ok'])
        self.assertEqual(lua.globals().completed['result']['seconds'],3)


    def test_unavailable_framebuffer_stops_and_caps_without_clearing_scene(self):
        lua=fixture('Tow')
        lua.execute("handlers['scene.drive']('fps','test');tick();now=10000;car.x=4;body.x=4;tick();invalidDisplay=true;tick()")
        self.assertFalse(lua.globals().completed['ok'])
        self.assertIn('framebuffer unavailable',lua.globals().completed['result'])
        self.assertEqual(lua.globals().fpsCap,60)
        self.assertEqual(lua.globals().viewCap,60)
        self.assertTrue(lua.globals().stopped)
        self.assertTrue(lua.globals().captureCancelled)
        self.assertEqual(len(lua.globals().CVPBenchmark['bodies']),1)

    def test_controller_exit_caps_idle_and_stops_active_trip(self):
        for active in (False,True):
            lua=fixture('Tow')
            if active: lua.execute("handlers['scene.drive']('fps','test');tick()")
            lua.execute('ownerLost=true;ownerTick();ownerTick()')
            self.assertEqual(lua.globals().fpsCap,60)
            self.assertTrue(lua.globals().stopped)
            if active: self.assertFalse(lua.globals().completed['ok'])

    def test_abort_is_repeatable_and_caps_idle_client(self):
        lua=fixture('Tow')
        lua.execute("handlers['perf.series.abort']();handlers['perf.series.abort']()")
        self.assertEqual(lua.globals().fpsCap,60)
        self.assertEqual(lua.globals().viewCap,60)


    def test_fast_zero_body_run_still_requires_vehicle_movement(self):
        for moving in (True,False):
            lua=fixture('Tow');lua.globals().moving=moving
            lua.execute('''
                CVPBenchmark.bodies={};CVPBenchmark.links={}
                CVPBenchmark.perfConfig={warmup=0,sample=10000,speed=8}
                handlers['scene.drive']('fps','test');tick()
                now=1000;car.x=3;tick()
                for i=2,13 do now=i*1000;if moving then car.x=i*2 end;tick() end
            ''')
            self.assertEqual(lua.globals().completed['ok'],moving)
            if moving:
                self.assertEqual(lua.globals().completed['result']['seconds'],10)
                self.assertEqual(lua.globals().completed['result']['movedBodies'],0)
            else:self.assertIn('vehicle did not travel',lua.globals().completed['result'])

    def test_high_fps_does_not_multiply_telemetry_or_skip_movement_acceptance(self):
        lua=fixture('Tow')
        lua.execute("handlers['scene.drive']('fps','test');tick();for i=1,6200 do now=i*5;car.x=now/1000;body.x=car.x;tick() end")
        self.assertTrue(lua.globals().completed['ok'])
        self.assertEqual(lua.globals().completed['result']['movedBodies'],1)
        self.assertEqual(len(lua.globals().csv.splitlines())-1,80)
        marks=list(lua.globals().marks.values())
        self.assertEqual(marks[3]['at']-marks[2]['at'],20000)

    def test_modes_keep_identical_drive_but_acceptance_observes_stopped_bodies(self):
        captures=[]
        for mode in ('fps','diagnostic','acceptance'):
            with self.subTest(mode=mode):
                lua=fixture('Tow');lua.globals().requested=mode
                lua.execute("handlers['scene.drive'](requested,'test');tick();for i=1,30 do now=i*1000;car.x=i;body.x=i;tick() end")
                lua.execute('now=31000;tick();now=32000;tick()')
                if mode=='acceptance':
                    self.assertIsNone(lua.globals().completed)
                    lua.execute('settle()')
                result=lua.globals().completed['result']
                self.assertTrue(lua.globals().completed['ok'])
                self.assertEqual(result['mode'],mode)
                self.assertEqual(result['seconds'],20)
                self.assertEqual(result['warmupSeconds'],10)
                self.assertEqual(result['movedBodies'],1)
                self.assertEqual(result['settling'] is not None,mode=='acceptance')
                if mode=='acceptance':
                    self.assertTrue(result['stopWindow']['complete'])
                    self.assertEqual(result['stopWindow']['maxDisplacement'],0)
                    self.assertEqual(result['stopWindow']['maxRelativeDisplacement'],0)
                    self.assertGreater(result['solverProbe']['samples'],0)
                marks=list(lua.globals().marks.values())
                self.assertEqual([m['phase'] for m in marks],
                                 ['enter','warmup','sample','brake','done'])
                if mode=='diagnostic':
                    self.assertEqual(marks[3]['at']-marks[2]['at'],20000)
                    self.assertTrue(all(m['id']=='test' for m in marks))
                captures.append(lua.globals().csv)
        self.assertEqual(captures[0],captures[1]);self.assertEqual(captures[0],captures[2])

    def test_acceptance_still_rejects_unstable_stopped_body(self):
        lua=fixture('Tow')
        lua.execute("handlers['scene.drive']('acceptance','test');tick();for i=1,32 do now=i*1000;car.x=i;body.x=i;tick() end")
        lua.execute('for i=33,49 do now=i*1000;body.x=body.x+3;tick();if completed then break end end')
        self.assertFalse(lua.globals().completed['ok'])
        self.assertIn('unstable stopped group',lua.globals().completed['result'])

    def test_all_modes_reject_unmoved_load(self):
        for mode in ('fps','diagnostic','acceptance'):
            lua=fixture('Tow');lua.globals().requested=mode
            lua.execute("handlers['scene.drive'](requested,'test');tick();body.x=3;for i=1,30 do now=i*1000;car.x=i;tick() end")
            self.assertFalse(lua.globals().completed['ok'])
            self.assertIn('did not travel',lua.globals().completed['result'])

    def test_quick_cycle_uses_short_window_but_still_requires_body_motion(self):
        lua=fixture('Tow')
        lua.execute("CVPBenchmark.perfConfig={warmup=2000,sample=5000,speed=20};handlers['scene.drive']('', 'test');tick();for i=1,9 do now=i*1000;car.x=i*2;body.x=i*2;tick() end")
        lua.execute('settle()')
        self.assertTrue(lua.globals().completed['ok'])
        self.assertEqual(lua.globals().speed,20)
        self.assertEqual(len(lua.globals().csv.splitlines())-1,5)
        self.assertEqual(lua.globals().completed['result']['movedBodies'],1)
        self.assertEqual(lua.globals().completed['result']['settling']['maxSpeed'],0)

    def test_mod_off_drives_without_runtime_and_skips_zero_interval(self):
        lua=fixture('Off')
        lua.execute("handlers['scene.drive']('', 'test');tick();for i=1,32 do now=i*1000;car.x=i;tick() end")
        lua.execute('settle()')
        self.assertTrue(lua.globals().completed['ok'])
        result=lua.globals().completed['result']
        self.assertEqual(result['movedBodies'],0)
        self.assertFalse(result['allBodiesMoving'])
        frames=lua.globals().csv.splitlines()[1:]
        self.assertEqual(len(frames),20)
        self.assertTrue(all(float(row.split(',')[0])>0 for row in frames))

    def test_towing_rejects_stationary_body_after_warmup(self):
        lua=fixture('Tow')
        lua.execute("handlers['scene.drive']('', 'test');tick();now=40000;car.x=10;tick()")
        self.assertFalse(lua.globals().completed['ok'])
        self.assertIn('load did not move after 40s',lua.globals().completed['result'])

    def test_every_body_must_move_during_sample(self):
        lua=fixture('Tow')
        lua.execute("handlers['scene.drive']('', 'test');tick();body.x=3;for i=1,30 do now=i*1000;car.x=i;tick() end")
        self.assertFalse(lua.globals().completed['ok'])
        self.assertIn('did not travel',lua.globals().completed['result'])
