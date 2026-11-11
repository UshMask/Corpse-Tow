from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


def fixture():
    lua = LuaRuntime()
    lua.execute(Path('tests/fixtures/benchmark_fixture.lua').read_text())
    lua.execute("package.preload['PZT_Control']=assert(loadstring(...))", Path('tools/pz-test/mod/42/media/lua/shared/PZT_Control.lua').read_text())
    lua.execute(Path('tests/scenarios/corpse-tow/CVP_Benchmark.lua').read_text())
    return lua


class BenchmarkLifecycleTests(unittest.TestCase):
    def test_clean_start_does_not_wrap_authority_tick(self):
        l=fixture()
        l.execute('''
            isDebugEnabled=function() return false end
            local original=function() return true end
            CVPRuntime={authority={tick=original}}
            start()
            assert(CVPRuntime.authority.tick==original)
        ''')

    def test_lab_cleanup_does_not_remove_tagged_player_body(self):
        l=fixture()
        l.execute('''
            getWorld=function() return {getWorld=function() return 'PZT_VehicleLab' end} end
            local b=getCell():getGridSquare(100,100,0):createCorpse(false)
            b.isZombie=function() return false end;b.isPlayer=function() return true end
            b:getModData().PZTFixture=true
            assert(send('reset','reset'):find('false'));assert(removed==0)
        ''')

    def test_empty_lab_uses_explicit_corpse_factory(self):
        l = fixture()
        l.execute('''
            getWorld=function() return {getWorld=function() return 'PZT_VehicleLab' end} end
            local factoryCalls=0
            addZombiesInOutfit=function(x,y,z,count,outfit,chance)
                assert(count==1 and z==0);factoryCalls=factoryCalls+1
                return {size=function() return 1 end,get=function() return {} end}
            end
            createRandomDeadBody=function(square)
                factoryCalls=factoryCalls+1
                local b=square:createCorpse(false);b.isZombie=function() return false end;return b
            end
            assert(send('reset','reset'):find('true'))
            assert(send('scene','scene',4):find('true'))
            assert(factoryCalls==4 and #CVPBenchmark.bodies==4)
            local before=removed
            assert(send('reset2','reset'):find('true'))
            assert(removed-before==4)
        ''')

    def test_seal_saves_clean_scene_before_closing(self):
        l = fixture()
        l.execute("saved=false;closed=false;function save(force) assert(force);assert(#CVPBenchmark.bodies==0);saved=true end;function MainScreen.instance:quitToDesktop() assert(saved);closed=true end;assert(send('s','seal'):find('true'));assert(closed);assert(outputs['CVPBenchmark-seed.txt']:find('bodies=0'))")

    def test_unwritable_output_rejects_before_sampling(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',1);failOutput=true;send('m','measure');assert(PZTest.lastResponse.ok==false);assert(not CVPBenchmark.sample);assert(PZTest.lastResponse.error:find('cannot open'))")

    def test_output_failure_at_finish_reports_failure_without_throwing(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',1);send('m','measure');failOutput=true;now=now+30000;render();assert(not CVPBenchmark.sample);assert(PZTest.lastResponse.ok==false);assert(PZTest.lastResponse.error:find('cannot open'))")

    def test_reset_refuses_unresolvable_old_links_before_any_mutation(self):
        l = fixture()
        l.execute("CVPRuntime={authority={service={graph={links={old={}}}}}};assert(send('r','reset'):find('false'));assert(not CVPBenchmark.seedReady);assert(removed==0)")

    def test_reset_recovers_saved_rope_before_removing_bodies(self):
        l = fixture()
        l.execute("""
            SandboxVars={CorpseProxyLab={}}
            local returned=false
            package.preload['CVP_Equipment']=function() return {get=function() return {getID=function() return 123 end} end} end
            function player:getInventory() return {getItemWithID=function(_,id) assert(id==123);return returned end} end
            local graph={links={old={a={x=100,y=100,z=0},equipment='rope',revision=1}}}
            CVPRuntime={authority={host={sample=function(e) return e end},service={graph=graph,
                command=function(_,p,cmd) assert(removed==0);assert(cmd.op=='remove');graph.links[cmd.id]=nil;returned=true;return true end}}}
            getCell():getGridSquare(100,100,0):createCorpse(false)
            assert(send('r','reset'):find('true'));assert(returned);assert(removed==1)
            assert(send('r2','reset'):find('true'))
        """)

    def test_reset_recovers_from_ground_when_body_is_unloaded(self):
        l = fixture()
        l.execute("""
            SandboxVars={CorpseProxyLab={}}
            package.preload['CVP_Equipment']=function() return {get=function() return {getID=function() return 123 end} end} end
            function player:getInventory() return {getItemWithID=function() return true end} end
            local graph={links={old={a={kind='body'},b={kind='ground',x=100,y=100,z=0},equipment='rope',revision=1}}}
            CVPRuntime={authority={host={sample=function(e) if e.kind=='ground' then return e end end},service={graph=graph,
                command=function(_,p,cmd) assert(cmd.side=='b');graph.links[cmd.id]=nil;return true end}}}
            assert(send('r','reset'):find('true'));assert(CVPBenchmark.seedReady)
        """)

    def test_reset_refuses_player_corpse_before_removing_other_bodies(self):
        l = fixture()
        l.execute("local sq=getCell():getGridSquare(99,99,0);sq:createCorpse(false);local b=sq:createCorpse(false);b.isZombie=function() return false end;assert(send('r','reset'):find('false'));assert(removed==0);assert(#sq.bodies==2)")

    def test_zero_one_many_and_repeated_cleanup_without_next(self):
        l = fixture()
        l.execute("assert(send('reset','reset'):find('true'));assert(CVPBenchmark.seedReady)")
        for i, n in enumerate((0, 1, 8, 32, 128, 0)):
            l.execute(f"assert(send('scene{i}','scene',{n}):find('true'));assert(#CVPBenchmark.bodies=={n});assert(CVPBenchmark.count=={n})")

    def test_invalid_requests_do_not_mutate_scene(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',1)")
        for i, (n, topology) in enumerate(((-1, 'loose'), (1.5, 'loose'), (129, 'loose'), (1, 'bad'), (1, 'chain'))):
            l.execute(f"assert(send('bad{i}','scene',{n},'{topology}'):find('false'));assert(CVPBenchmark.count==1);assert(created==1)")

    def test_menu_request_is_rejected_without_throwing(self):
        l = fixture()
        l.execute("worldReady=false;assert(send('reset','reset'):find('false'));assert(created==0)")

    def test_failed_setup_invalidates_previous_measurement_scene(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',1);obstructed=true;assert(send('fail','scene',2):find('false'));assert(CVPBenchmark.count==nil);assert(send('m','measure'):find('false'))")

    def test_sampling_finishes_and_writes_raw_frames_and_metadata(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',1);assert(send('m','measure'):find('warming'));now=now+10000;render();for i=1,2000 do now=now+10;render() end;assert(PZTest.lastResponse.result:find('done'));assert(outputs['CVPBenchmark-m-frames.txt']);assert(outputs['CVPBenchmark-m-meta.txt']:find('count=1'))")

    def test_pause_invalidates_sample_without_success_output(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',0);send('m','measure');visible=true;now=now+1000;render();assert(not CVPBenchmark.sample);assert(PZTest.lastResponse.ok==false);assert(not outputs['CVPBenchmark-m-frames.txt'])")

    def test_native_motion_error_returns_failure_and_stops(self):
        l = fixture()
        l.execute("send('reset','reset');send('scene','scene',0);send('m','measure',0,'loose','moving');failMotion=true;tick();assert(not CVPBenchmark.sample);assert(PZTest.lastResponse.error:find('native motion failure'))")
