from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


def fixture():
    l=LuaRuntime()
    l.execute('''
        handlers={};require=function() return {register=function(n,f) handlers[n]=f end,move=function(b,x,y) b.x=x;b.y=y end} end
        local positions={};worldBodies={};nextID=0;inventory={};clock={day=4,month=6,year=1993}
        function newBody(i)
            return {x=i,y=0,getModData=function() return {PZTPerfIndex=i} end,isZombie=function() return i%2==1 end,
                isPlayer=function() return false end,getStaticMovingObjectIndex=function() return 0 end,
                getX=function(s) return s.x end,getY=function(s) return s.y end}
        end
        for i=1,32 do positions[i]={x=i,y=0,z=0,zombie=i%2==1};worldBodies[i]=newBody(i) end
        metadata={PZTPerformance={count=32,positions=positions,origin={x=0,y=0,z=0}}}
        local inv={getItemWithID=function(_,id) return inventory[id] end,Remove=function(_,v) inventory[v.id]=nil end,
            AddItem=function() nextID=nextID+1;local g={id=nextID,getID=function(s) return s.id end};inventory[nextID]=g;return g end}
        player={getModData=function() return metadata end,getX=function() return 0 end,getY=function() return 0 end,getZ=function() return 0 end,
            teleportTo=function() teleported=true end,
            getVehicle=function() return inCar end,getInventory=function() return inv end,
            setGodMod=function() end,setGhostMode=function() end,
            getBodyDamage=function() return {RestoreToFullHealth=function() healed=true end} end,
            getStats=function() return {resetStats=function() statsReset=true end} end}
        getPlayer=function() return player end
        function car() return {getX=function() return 0 end,getY=function() return 0 end,setForceBrake=function() end,
            setPhysicsActive=function() end,setCharacterPosition=function() end} end
        vehicle=car()
        getCell=function() return {getGridSquare=function(_,x) if x==0 and originUnloaded then return nil end;return {getDeadBodys=function() return {
            size=function() return worldBodies[x] and 1 or 0 end,get=function() return worldBodies[x] end} end,
            getWorldObjects=function() return {size=function() return dropped and 1 or 0 end,get=function() return dropped end} end} end,
            getVehicles=function() return {iterator=function() local done=false;return {hasNext=function() return not pendingVehicle and not done and vehicle~=nil end,
                next=function() done=true;return vehicle end} end} end} end
        getGameTime=function() return {getDay=function() return clock.day end,getMonth=function() return clock.month end,
            getYear=function() return clock.year end,setDay=function(_,v) clock.day=v end,setMonth=function(_,v) clock.month=v end,
            setYear=function(_,v) clock.year=v end,setTimeOfDay=function(_,v) clock.hour=v end} end
        setGameSpeed=function() end;save=function() saved=true end
        getCore=function() return {setFramerate=function() end,getZoom=function() return 1 end,
            getScreenWidth=function() return 1280 end,getScreenHeight=function() return 720 end} end
        getPerformance=function() return {isFramerateUncapped=function() return true end,getFramerate=function() return 0 end} end
        getSandboxOptions=function() return {updateFromLua=function() assert(SandboxVars.Zombies==6);ambientDisabled=true end} end
        SandboxVars={CorpseProxyLab={}};CVPNetwork={id=function(b) return b end}
        links={};preparedSources={};CVPRuntime={authority={host={discover=function() end,vehicleKey=function() return 'car' end,
            resolve=function(ref) return ref end,sample=function() return {} end,
            bodyPoint=function(b) return {x=b:getX(),y=b:getY()} end},service={graph={links=links},
            prepare=function(_,p,source,id) preparedSources[id]=source;return id end,
            create=function(_,p,id,target) links[id]={a=preparedSources[id],b=target,length=1};return true,id end},
            simulation={build=function(s) s.groups={};for _,link in pairs(links) do if link.a.kind=='vehicle' then s.groups[#s.groups+1]={} end end end}}}
        CVPBenchmark={bodies={},gear={},links={},beside=function() end,clear=function()
            if lostRope then error('fixture tether not returned') end
            for id in pairs(links) do links[id]=nil end
            CVPBenchmark.bodies={};CVPBenchmark.gear={};CVPBenchmark.links={}
        end}
        captures=0;clears=0;CVPBenchmarkNative={captureSeriesVehicle=function() return true end,captureSeriesBody=function() captures=captures+1;return captures end,
            clearSeriesObjects=function() clears=clears+1;vehicle=nil;worldBodies={};return 800 end,
            restoreSeriesVehicle=function() vehicle=car();return vehicle end,
            restoreSeriesBody=function(i) worldBodies[i]=newBody(i);return worldBodies[i] end}
    ''')
    l.execute(Path('tests/scenarios/corpse-tow/CVP_Performance.lua').read_text())
    l.execute('''function prepare(n) handlers['perf.series.scene'](n);return handlers['perf.series.adopt']() end;next=nil''')  # Game Kahlua exposes pairs, but not the standard next global.
    return l


class SeriesTests(unittest.TestCase):
    def test_warm_preset_keeps_thirty_second_warmup_on_every_trip(self):
        l=fixture();l.execute('''
            handlers['perf.series.begin']()
            for _,warmed in ipairs({'0','1'}) do
                handlers['perf.series.config']('Tow warm '..warmed)
                prepare('0')
                assert(CVPBenchmark.perfConfig.warmup==30000 and CVPBenchmark.perfConfig.sample==20000)
                assert(handlers['perf.series.clear']().returned==0)
            end
        ''')

    def test_series_disables_ambient_generation_before_restoring(self):
        l=fixture()
        l.execute("handlers['perf.series.begin']();assert(ambientDisabled and SandboxVars.Zombies==6)")

    def test_uncapped_background_keeps_cap_zero_and_disables_focus_pause(self):
        l=fixture();l.execute('''
            local core=getCore();core.setOptionPauseOnFocusloss=function(_,value) pause=value end
            getCore=function() return core end
            PZTPresentedFrames={backgroundMode=function() return true end}
            handlers['perf.series.begin']();local row=prepare('32')
            assert(row.background and row.uncapped and pause==false)
        ''')

    def test_fast_counts_config_and_materials(self):
        l=fixture();l.execute('''
            handlers['perf.series.begin']()
            for i,n in ipairs({32,8,1,0}) do
                handlers['perf.series.config']('Tow fast '..(i==1 and '0' or '1'))
                local row=prepare(tostring(n))
                assert(row.count==n and row.links==n and row.groups==n)
                assert(CVPBenchmark.perfConfig.sample==10000)
                assert(CVPBenchmark.perfConfig.warmup==(i==1 and 10000 or 0))
                local result=handlers['perf.series.clear']();assert(result.returned==n)
            end
        ''')

    def test_loose_on_and_off_counts_have_no_materials(self):
        for variant in ('On','Off'):
            l=fixture()
            if variant=='Off': l.execute('CVPRuntime=nil')
            l.globals().variant=variant
            l.execute('''
                handlers['perf.series.begin']()
                for _,n in ipairs({0,1,2,8,32}) do
                    handlers['perf.series.config'](variant..' full 0')
                    local row=prepare(tostring(n))
                    assert(row.count==n and row.links==0 and row.mode==variant)
                    assert(CVPBenchmark.perfConfig.sample==20000 and CVPBenchmark.perfConfig.warmup==10000)
                    assert(handlers['perf.series.clear']().returned==0)
                end
            ''')

    def test_disable_supported_module_records_actual_setting(self):
        l=fixture();l.execute('''
            SandboxVars.CorpseProxyLab.BodySpread=true
            handlers['perf.series.begin']()
            handlers['perf.series.config']('Tow fast 0 BodySpread')
            assert(prepare('8').sandbox.BodySpread==false)
        ''')
        with self.assertRaisesRegex(Exception,'configure before'):
            l.execute("handlers['perf.series.config']('Tow fast 1')")

    def test_disable_rope_render_keeps_links_and_records_setting(self):
        l=fixture();l.execute('''
            local option={value=true,setValue=function(s,v) s.value=v end,getValue=function(s) return s.value end}
            PZAPI={ModOptions={getOptions=function() return {getOption=function() return option end} end}}
            handlers['perf.series.begin']()
            handlers['perf.series.config']('Tow fast 0 ShowRopes')
            local row=prepare('1')
            assert(row.showRopes==false and row.links==1 and row.groups==1)
            assert(handlers['perf.series.clear']().returned==1)
        ''')

    def test_background_profile_caps_frames_without_requiring_focus(self):
        l=fixture();l.execute('''
            local core=getCore()
            core.setOptionPauseOnFocusloss=function(_,value) pauseOnFocusLoss=value end
            getCore=function() return core end
            Viewpoint={FrameCaps={active=function() return true end,
                setGameCap=function(value) gameCap=value end,gameCap=function() return gameCap end}}
            local result=handlers['perf.adopt']('Tow background')
            assert(gameCap==60 and pauseOnFocusLoss==false)
            assert(result.preset=='background' and result.fpsCap==60 and not result.uncapped)
            assert(result.count==32 and result.links==32)
        ''')

    def test_initial_seed_drops_are_recorded_and_cleaned_before_verification(self):
        l=fixture();l.execute('''
                dropped={getItem=function() return {getID=function() return 901 end,
                    getFullType=function() return 'Base.Hat_BaseballCap' end,setWorldItem=function() end} end,
                    removeFromWorld=function() end,removeFromSquare=function() dropped=nil end}
            local clear=CVPBenchmarkNative.clearSeriesObjects
            CVPBenchmarkNative.clearSeriesObjects=function() assert(not dropped);return clear() end
            local result=handlers['perf.series.begin']()
            assert(#result.drops==1 and result.drops[1].id==901)
        ''')

    def test_chain_fixture_has_one_root_and_restores_all_materials(self):
        l=fixture();l.execute('''
            handlers['perf.series.begin']('chain-track');local result=prepare('32 chain')
            assert(result.groups==1 and result.topology=='chain' and result.links==32)
            local x,y=CVPBenchmark.bodies[32]:getX(),CVPBenchmark.bodies[32]:getY()
            assert(math.abs(x-.1)<.0001 and math.abs(y-40.2)<.0001 and result.layout=='chain-feet-120')
            local cleared=handlers['perf.series.clear']();assert(cleared.returned==32)
            local individual=prepare('32 individual');assert(individual.groups==32)
            assert(CVPBenchmark.bodies[32]:getX()==32 and CVPBenchmark.bodies[32]:getY()==0 and individual.layout=='seed')
        ''')

    def test_packed_independent_fixture_retains_separate_tethers(self):
        l=fixture();l.execute('''
            handlers['perf.series.begin']('packed-individual')
            local result=prepare('32 individual')
            assert(result.groups==32 and result.links==32 and result.layout=='packed-individual')
            local a,b=CVPBenchmark.bodies[1],CVPBenchmark.bodies[32]
            assert(math.abs(a:getX()+.315)<.0001 and math.abs(a:getY()-3)<.0001)
            assert(math.abs(b:getX()-.315)<.0001 and math.abs(b:getY()-3.27)<.0001)
            assert(handlers['perf.series.clear']().returned==32)
        ''')

    def test_alternating_counts_reset_calendar_and_keep_full_warmup(self):
        l=fixture()
        l.execute('''
            handlers['perf.series.begin']();assert(captures==32 and saved)
            for _,n in ipairs({1,32,1,32}) do
                clock.day=8;clock.month=11;clock.year=2000
                local row=prepare(tostring(n))
                assert(row.count==n and row.links==n and row.series)
                assert(clock.day==4 and clock.month==6 and clock.year==1993 and clock.hour==12)
                assert(CVPBenchmark.perfConfig.warmup==10000 and CVPBenchmark.perfConfig.sample==20000)
                local result=handlers['perf.series.clear']();assert(result.returned==n and result.count==n)
            end
            assert(clears==5 and healed and statsReset)
        ''')

    def test_lost_rope_stops_before_objects_are_removed(self):
        l=fixture()
        l.execute("handlers['perf.series.begin']();prepare('32');lostRope=true")
        with self.assertRaisesRegex(Exception,'tether not returned'):
            l.execute("handlers['perf.series.clear']()")
        self.assertEqual(l.globals().clears,1)

    def test_scene_drops_are_recorded_but_tethers_are_not_silently_deleted(self):
        l=fixture()
        l.execute('''
            handlers['perf.series.begin']();prepare('1')
            kind='Base.Rope';local item={getID=function() return 900 end,getFullType=function() return kind end,
                setWorldItem=function(_,v) assert(v==nil);unlinked=true end}
            dropped={getItem=function() return item end,removeFromWorld=function() removed=true end,
                removeFromSquare=function() dropped=nil end}
        ''')
        with self.assertRaisesRegex(Exception,'unexpected tether'):
            l.execute("handlers['perf.series.clear']()")
        self.assertIsNone(l.globals().removed)
        l.execute("kind='Base.Hat_BaseballCap';local row=handlers['perf.series.clear']();assert(#row.drops==1 and row.drops[1].id==900 and unlinked)")

    def test_rejects_reset_with_driver_inside_and_scene_overwrite(self):
        l=fixture()
        l.execute("handlers['perf.series.begin']();prepare('1')")
        with self.assertRaisesRegex(Exception,'clear previous'):
            l.execute("prepare('32')")
        l.execute('inCar=vehicle')
        with self.assertRaisesRegex(Exception,'driver must exit'):
            l.execute("handlers['perf.series.clear']()")
        self.assertEqual(l.globals().clears,1)

    def test_native_failure_cannot_be_reported_as_a_clean_scene(self):
        l=fixture()
        l.execute("handlers['perf.series.begin']();prepare('1');CVPBenchmarkNative.clearSeriesObjects=function() return nil end")
        with self.assertRaisesRegex(Exception,'native scene cleanup failed'):
            l.execute("handlers['perf.series.clear']()")
        with self.assertRaisesRegex(Exception,'clear previous'):
            l.execute("prepare('32')")

    def test_native_capture_failure_stops_before_cleanup(self):
        l=fixture()
        l.execute('CVPBenchmarkNative.captureSeriesBody=function() return nil end')
        with self.assertRaisesRegex(Exception,'body capture failed'):
            l.execute("handlers['perf.series.begin']()")
        self.assertEqual(l.globals().clears,0)
        self.assertIsNone(l.globals().saved)

    def test_streamed_start_must_reload_and_be_cleaned_before_next_scene(self):
        l=fixture()
        l.execute("handlers['perf.series.begin']();prepare('1');originUnloaded=true")
        l.execute("assert(handlers['perf.series.clear']().stage=='returning');assert(teleported);assert(not handlers['perf.series.ready']().ready)")
        with self.assertRaisesRegex(Exception,'clear previous'):
            l.execute("prepare('32')")
        l.execute("originUnloaded=false;assert(handlers['perf.series.ready']().ready);assert(clears==3);prepare('32')")

    def test_weather_is_restored_to_captured_values(self):
        l=fixture()
        l.execute('''
            ClimateManager={FLOAT_FOG_INTENSITY=0,FLOAT_PRECIPITATION_INTENSITY=1,FLOAT_WIND_INTENSITY=2,FLOAT_CLOUD_INTENSITY=3,FLOAT_TEMPERATURE=4}
            values={};for i=0,4 do values[i]={value=i,getFinalValue=function(s) return s.value end,
                setAdminValue=function(s,v) s.admin=v end,setEnableAdmin=function(s,v) s.enabled=v end} end
            getClimateManager=function() return {getClimateFloat=function(_,id) return values[id] end} end
            handlers['perf.series.begin']()
            for i=0,4 do values[i].value=99 end
            prepare('1')
            for i=0,4 do assert(values[i].admin==i and values[i].enabled) end
        ''')

    def test_does_not_attach_until_vehicle_registration_finishes(self):
        l=fixture()
        l.execute('''
            handlers['perf.series.begin']();handlers['perf.series.scene']('32')
            pendingVehicle=true
            assert(not handlers['perf.series.adopt']().ready and #CVPBenchmark.links==0)
            pendingVehicle=false
            local row=handlers['perf.series.adopt']();assert(row.ready and row.links==32)
        ''')


if __name__=='__main__': unittest.main()
