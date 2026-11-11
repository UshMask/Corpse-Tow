from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


class ProfilerTests(unittest.TestCase):
    def test_nested_time_and_restoration_preserve_return_values(self):
        lua=LuaRuntime()
        lua.execute('''
            now=0; handlers={}; modules={}
            CVPBenchmark={perf='Tow'}
            CVPBenchmarkNative={milliseconds=function() return now end,cpuNanos=function() return now*400000 end}
            CVPRuntime={authority={tick=function() now=now+10 end,host={sample=function() return nil,'missing' end}}}
            nativeCalls=0;points={{x=1},{x=2}}
            CVPFreeRopeScene={update=function(id,p,chain)
                assert(p==points and chain==false);nativeCalls=nativeCalls+1
                if id=='bad' then error('injected') end
            end,version=function() return 'native' end}
            originalNative=CVPFreeRopeScene
            CVPRuntime.handlers={OnTick=function() end}
            CVPRuntime.presentation={update=function() end};CVPRuntime.actions={update=function() end}
            for _,key in ipairs({'players','discover','skeletons'}) do CVPRuntime.authority[key]=function() end end
            modules.CVP_Feedback={draw=function() end}
            local keys={CVP_LinkSimulation={'tick','apply','build'},CVP_Core={'advance'},
                CVP_Geometry={'resolve','anchor'},CVP_LinkObstacles={'check'},CVP_Rope={'step','separate'},
                CVP_Load={'refresh','connect','tension'},CVP_World={'move'},CVP_Effects={'committed'},
                CVP_LinkJoints={'place','length'},CVP_LinkRuntime={'removedEnds','samples'},CVP_LinkService={'tick','refresh'}}
            for name,list in pairs(keys) do modules[name]={}
                for _,key in ipairs(list) do modules[name][key]=function() now=now+2;return nil,'second',3 end end
            end
            modules.CVP_Core.advance=function()
                now=now+3
                return modules.CVP_LinkObstacles.check()
            end
            original=modules.CVP_Core.advance
            require=function(name)
                if name=='PZT_Control' then return {register=function(n,f) handlers[n]=f end} end
                return modules[name]
            end
        ''')
        lua.execute(Path('tests/scenarios/corpse-tow/CVP_Performance.lua').read_text())
        lua.execute('''
            CVPFreeRopeScene.update('outside',points,false)
            handlers['perf.profile.begin']()
            assert(CVPFreeRopeScene.version()=='native')
            CVPFreeRopeScene.update('good',points,false)
            assert(not pcall(CVPFreeRopeScene.update,'bad',points,false))
            CVPRuntime.authority:tick()
            local a,b,c=modules.CVP_Core.advance();assert(a==nil and b=='second' and c==3)
            result=handlers['perf.profile.end']()
            assert(modules.CVP_Core.advance==original)
            assert(CVPFreeRopeScene==originalNative)
            CVPFreeRopeScene.update('outside',points,false)
            assert(nativeCalls==4 and result.ropeUploads.calls==2 and result.ropeUploads.completed==1)
            assert(result.ropeUploads.points==4)
            CVPBenchmarkNative.cpuNanos=function() return -1 end
            handlers['perf.profile.begin']();CVPRuntime.authority:tick()
            local second=handlers['perf.profile.end']()
            assert(second.ropeUploads.calls==0 and CVPFreeRopeScene==originalNative)
            for _,row in ipairs(second.rows) do if row.name=='authority.tick' then
                assert(row.cpuAvailable==false and row.cpuMS==nil and row.cpuSamples==nil)
            end end
        ''')
        rows={r['name']:r for r in lua.globals().result['rows'].values()}
        self.assertEqual(rows['CVP_Core.advance']['inclusiveMS'],5)
        self.assertEqual(rows['CVP_Core.advance']['selfMS'],3)
        self.assertEqual(rows['CVP_LinkObstacles.check']['selfMS'],2)
        self.assertEqual(rows['authority.tick']['cpuMS'],4)
        self.assertEqual(rows['authority.tick']['cpuSamples'],1)
        self.assertIsNone(rows['CVP_Core.advance']['cpuMS'])
