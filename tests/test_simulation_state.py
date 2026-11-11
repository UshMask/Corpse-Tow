"""Topology publication and derived caches; no game launch or timing checks."""
import unittest
from test_link_runtime import environment


class SimulationStateTests(unittest.TestCase):
    def test_failed_rebuild_is_retried_with_same_index_and_generation(self):
        lua = environment()
        lua.execute('''
            link(C,A,rope);link(A,B,chain)
            local original=Sim.store.linkReady;local calls=0
            Sim.store.linkReady=function(...)
                calls=calls+1
                if calls==2 then error('injected topology failure') end
                return original(...)
            end
            assert(not pcall(Sim.build,Sim,S.graph,S.index))
            assert(Sim.index==nil,'failed build was marked current')
            Sim.store.linkReady=original
            Sim:build(S.graph,S.index)
            assert(Sim.index==S.index and #Sim.groups==1 and #Sim.groups[1].records==2)
            local groups=Sim.groups;Sim:build(S.graph,S.index)
            assert(Sim.groups==groups,'completed build must remain cached')
            intact(body);intact(body2)
        ''')

    def test_spread_cache_follows_groups_even_with_unchanged_index(self):
        lua = environment()
        lua.execute('''
            link(C,A,rope);link(C,B,chain);Sim:build(S.graph,S.index)
            local spread=require 'CVP_BodySpread';local original=spread.layout;local calls=0
            spread.layout=function(groups) calls=calls+1;return original(groups) end
            spread.update(Sim,false);spread.update(Sim,false);assert(calls==1)
            local index,generation=Sim.index,Sim.generation
            local groups={};for i,g in ipairs(Sim.groups) do groups[i]=g end
            Sim.groups=groups;spread.update(Sim,false)
            assert(calls==2 and Sim.spreadGroups==groups)
            assert(Sim.index==index and Sim.generation==generation)
            SandboxVars.CorpseProxyLab.BodySpread=false;spread.update(Sim,false)
            SandboxVars.CorpseProxyLab.BodySpread=true;spread.update(Sim,false)
            assert(calls==3)
        ''')

    def test_explicit_lua_mode_overrides_available_native_helpers(self):
        lua = environment()
        lua.execute('''
            link(C,A,rope);Sim:build(S.graph,S.index)
            CVPSolverNative={begin=function() error('unexpected native environment') end,
                spread=function() error('unexpected native spread') end}
            CVPSolverUseLua=false
            require('CVP_BodySpread').update(Sim,false)
            assert(not require('CVP_LinkObstacles').new(false).native)
        ''')
