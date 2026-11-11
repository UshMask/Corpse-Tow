"""Native candidates still pass through the original body commit/rollback contract."""
import unittest
from test_link_runtime import environment


class NativeSolverAdapterTests(unittest.TestCase):
    def fixture(self):
        l=environment();l.execute('''
            calls=0;prepares=0;releases=0
            CVPSolverNative={begin=function() return {} end,check=function() return nil end,
                prepare=function(records) prepares=prepares+1;return {records=records} end,
                release=function(state) releases=releases+1 end,
                solvePersistent=function(state,cache,group,steps,h)
                    calls=calls+1;lastSteps=steps
                    assert(steps>=1 and steps<=50 and math.abs(h-.01)<1e-10)
                    for _,r in ipairs(state.records) do r.x=r.x+.1 end
                    group.nativeGap=0;return 0
                end}
        ''');return l

    def test_one_call_for_group_and_original_body_commit(self):
        l=self.fixture();l.execute('''
            link(C,A,rope);link(A,B,chain)
            local x,y=body.x,body2.x;run()
            assert(calls==1 and lastSteps==5 and math.abs(body.x-x-.1)<1e-9 and math.abs(body2.x-y-.1)<1e-9)
            intact(body);intact(body2)
        ''')

    def test_failed_native_calculation_does_not_move_world_and_recovers(self):
        l=self.fixture();l.execute('''
            link(C,A,rope);local x=body.x;local solve=CVPSolverNative.solvePersistent
            CVPSolverNative.solvePersistent=function(state) state.records[1].x=999;error('native failed') end
            local ok=R:tick({player},.05);assert(not ok and body.x==x and Sim.calculating)
            CVPSolverNative.solvePersistent=solve;now=now+5000;run()
            assert(math.abs(body.x-x-.1)<1e-9 and not Sim.calculating);intact(body)
        ''')

    def test_native_state_is_reused_and_released_on_topology_change(self):
        l=self.fixture();l.execute('''
            link(C,A,rope);run();run();assert(prepares==1 and calls==2 and releases==0)
            link(A,B,chain);run()
            assert(prepares==2 and calls==3 and releases==1)
            intact(body);intact(body2)
        ''')

    def test_lua_reference_override_avoids_native_entry(self):
        l=self.fixture();l.execute('''
            link(C,A,rope);CVPSolverUseLua=true
            CVPSolverNative.begin=function() error('native entered') end
            run();assert(calls==0);intact(body)
        ''')


if __name__=='__main__':unittest.main()
