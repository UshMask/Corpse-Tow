from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


class AutoloadTests(unittest.TestCase):
    def test_fresh_lab_creates_world_without_loading_an_old_save(self):
        lua = LuaRuntime()
        lua.execute('''
            require=function() end
            Events={OnLoadedMapZones={Add=function(f) mapLoaded=f end},OnGameStart={Add=function() end},
                OnMainMenuEnter={Add=function(f) enter=f end},
                OnFETick={Add=function(f) render=f end,Remove=function() render=nil end}}
            function getFileReader(name)
                local lines=name=='CVPQuickStart.txt' and {'PZT_VehicleLab','True'} or {'On'}
                local i=0
                return {readLine=function() i=i+1;return lines[i] end,close=function() end}
            end
            function getFileWriter() return {write=function() end,close=function() end} end
            SandboxVars={ZombieConfig={}}
            MainScreen={instance={setDefaultSandboxVars=function() end},
                continueLatestSave=function() error('must not load a previous save') end}
            local world={}
            for _,key in ipairs({'GameMode','World','Map','LuaPlayerDesc','LuaPosX','LuaPosY','LuaPosZ'}) do
                world['set'..key]=function(self,value) self[key]=value end
            end
            world.getLuaTraits=function() return {clear=function() end} end
            getWorld=function() return world end
            getSandboxOptions=function() return {updateFromLua=function() end} end
            SurvivorFactory={CreateSurvivor=function() return 'new survivor' end}
            createWorld=function(name) created=name end
            GameWindow={doRenderEvent=function() end}
            LoadingQueueState={new=function() return 'loading' end}
            forceChangeState=function(state) changed=state end
        ''')
        lua.execute(Path('tools/quick-test/CVP_QuickStart.lua').read_text())
        lua.execute('enter();render();render()')
        self.assertEqual(lua.globals().created, 'PZT_VehicleLab')
        self.assertEqual(lua.globals().changed, 'loading')
        self.assertEqual(lua.eval('getWorld().LuaPlayerDesc'), 'new survivor')
        self.assertEqual(lua.eval('getWorld().Map'), 'PZT_ProvingGround')
        lua.execute('getWorld().getWorld=function(s) return s.World end; getWorld().getMap=function(s) return s.Map end; mapLoaded()')
        self.assertEqual(lua.eval('SandboxVars.Zombies'), 4)
        self.assertEqual(lua.eval('SandboxVars.ZombieConfig.PopulationMultiplier'), 0)

    def test_loading_is_deferred_and_only_runs_once_in_benchmark(self):
        for mode in ('On', 'Off', 'ordinary'):
            lua = LuaRuntime()
            lua.execute("""
                require=function() end
                Events={OnLoadedMapZones={Add=function(f) mapLoaded=f end},OnGameStart={Add=function() end},
                    OnMainMenuEnter={Add=function(f) enter=f end},
                    OnFETick={Add=function(f) render=f end,Remove=function() render=nil end}}
                function getFileReader(name)
                    if name=='CVPBenchmark-mode.txt' and mode=='ordinary' then return end
                    return {readLine=function() return name=='CVPQuickStart.txt' and 'CVP_QuickTest' or mode end,close=function() end}
                end
                function getFileWriter() return {write=function() end,close=function() end} end
                MainScreen={instance={},continueLatestSave=function(m,w)
                    assert(m=='Sandbox' and w=='CVP_QuickTest');loads=(loads or 0)+1
                end}
            """)
            lua.globals().mode = mode
            lua.execute(Path('tools/quick-test/CVP_QuickStart.lua').read_text())
            lua.execute('enter();assert(loads==nil)')
            if mode == 'ordinary':
                lua.execute('assert(render==nil)')
            else:
                lua.execute('local queued=render;render();assert(loads==nil);render();assert(loads==1 and render==nil);queued();assert(loads==1)')

    def test_existing_proving_ground_disables_population_before_game_start(self):
        for world, map_name, expected in [('PZT_VehicleLab','PZT_ProvingGround',True),
                                           ('CVP_QuickTest','PZT_ProvingGround',True),
                                           ('Other','PZT_ProvingGround',False),
                                           ('PZT_VehicleLab','Muldraugh, KY',False)]:
            lua=LuaRuntime()
            lua.execute("""
                require=function() end
                Events={OnLoadedMapZones={Add=function(f) loaded=f end},
                    OnGameStart={Add=function() end},OnMainMenuEnter={Add=function() end}}
                SandboxVars={Zombies=4,ZombieConfig={PopulationMultiplier=1,RespawnHours=72}}
                getWorld=function() return {getWorld=function() return world end,getMap=function() return mapName end} end
                getSandboxOptions=function() return {updateFromLua=function() applied=true end} end
            """)
            lua.globals().world=world;lua.globals().mapName=map_name
            lua.execute(Path('tools/quick-test/CVP_QuickStart.lua').read_text())
            lua.execute('loaded()')
            self.assertEqual(bool(lua.globals().applied),expected)
            self.assertEqual(lua.eval('SandboxVars.Zombies'),6 if expected else 4)
            self.assertEqual(lua.eval('SandboxVars.ZombieConfig.PopulationMultiplier'),0 if expected else 1)
            if expected:
                self.assertEqual(lua.eval('SandboxVars.ZombieConfig.RespawnHours'),0)
                self.assertEqual(lua.eval('SandboxVars.ZombieConfig.RedistributeHours'),0)

    def test_manual_autoload_consumed_once_without_benchmark(self):
        lua=LuaRuntime()
        lua.execute("""
            require=function() end
            Events={OnLoadedMapZones={Add=function() end},OnGameStart={Add=function() end},
                OnMainMenuEnter={Add=function(f) enter=f end},
                OnFETick={Add=function(f) render=f end,Remove=function() render=nil end}}
            function getFileReader(name)
                if name~='CVPQuickStart.txt' then return end
                local rows=consumed and {'consumed'} or {'PZT_VehicleLab','False','True'}
                local i=0
                return {readLine=function() i=i+1;return rows[i] end,close=function() end}
            end
            function getFileWriter() return {write=function() consumed=true end,close=function() end} end
            MainScreen={instance={},continueLatestSave=function(mode,world)
                assert(mode=='Sandbox' and world=='PZT_VehicleLab');loads=(loads or 0)+1
            end}
        """)
        lua.execute(Path('tools/quick-test/CVP_QuickStart.lua').read_text())
        lua.execute('enter();local queued=render;render();render();queued();enter();assert(loads==1 and render==nil)')

    def test_manual_supplies_are_idempotent_and_benchmark_excluded(self):
        lua=LuaRuntime()
        lua.execute("""
            require=function() end
            Events={OnLoadedMapZones={Add=function() end},OnGameStart={Add=function() end},OnMainMenuEnter={Add=function() end}}
            world='PZT_VehicleLab';rows={};keys=0
            getWorld=function() return {getWorld=function() return world end} end
            getFileReader=function() if benchmark then return {close=function() end} end end
            local list={size=function() return #rows end,get=function(_,i) return rows[i+1] end}
            local inv={getItems=function() return list end,AddItem=function(_,kind)
                local item=type(kind)=='table' and kind or {getFullType=function() return kind end}
                rows[#rows+1]=item;return item
            end}
            getPlayer=function() return {getInventory=function() return inv end,getX=function() return 0 end,getY=function() return 0 end} end
            local car={getX=function() return 1 end,getY=function() return 0 end,getKeyId=function() return 42 end,
                createVehicleKey=function() keys=keys+1;return {getKeyId=function() return 42 end,getFullType=function() return 'Base.CarKey' end} end}
            getCell=function() return {getVehicles=function() return {iterator=function()
                local nextCar=true;return {hasNext=function() return nextCar end,
                    next=function() nextCar=false;return car end}
            end} end} end
        """)
        lua.execute(Path('tools/quick-test/CVP_QuickStart.lua').read_text())
        lua.execute("benchmark=true;CVPQuickTestSupplies();assert(#rows==0);benchmark=false;world='Other';CVPQuickTestSupplies();assert(#rows==0);world='PZT_VehicleLab';CVPQuickTestSupplies();CVPQuickTestSupplies();assert(#rows==33 and keys==1)")
