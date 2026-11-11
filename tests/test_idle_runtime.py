"""Idle authority keeps maintenance/recovery but wakes immediately for real work."""
import unittest
from test_link_runtime import environment


class IdleRuntimeTests(unittest.TestCase):
    def test_player_provider_is_lazy_but_wakes_for_maintenance_and_attachment(self):
        l=self.fixture();l.execute('''
            calls=0
            local function players() calls=calls+1;return {player} end
            assert(R:tick(players,.01));assert(calls==1)
            for i=1,100 do assert(R:tick(players,.01)) end
            assert(calls==1)
            now=now+1000;assert(R:tick(players,.01));assert(calls==2)
            local id=link(C,A,rope);now=now+10;assert(R:tick(players,.01))
            assert(calls==3 and Sim.records[id]);intact(body)
        ''')

    def fixture(self):
        l=environment()
        l.execute('''
            next=nil
            local tick=Sim.tick;fullTicks=0
            Sim.tick=function(self,...) fullTicks=fullTicks+1;return tick(self,...) end
            function frame() local ok,err=R:tick({player},.01);assert(ok,err) end
        ''')
        return l

    def test_empty_frames_keep_once_per_second_maintenance(self):
        l=self.fixture();l.execute('''
            local discover=H.discover;discoveries=0
            H.discover=function(...) discoveries=discoveries+1;return discover(...) end
            frame();assert(fullTicks==1 and discoveries==1)
            for i=1,100 do frame() end
            assert(fullTicks==1 and discoveries==1)
            now=now+1000;frame();assert(fullTicks==2 and discoveries==2)
        ''')

    def test_new_attachment_wakes_without_waiting_for_discovery(self):
        l=self.fixture();l.execute('''
            frame();frame();assert(fullTicks==1)
            local id=link(C,A,rope);car.x=car.x+.1;now=now+10;frame()
            assert(fullTicks==2 and Sim.records[id]);frame();assert(fullTicks==2)
            now=now+10;frame();assert(fullTicks==3)
            intact(body)
        ''')

    def test_removing_last_link_returns_to_idle_after_returning_material(self):
        l=self.fixture();l.execute('''
            local id=link(C,A,rope);frame()
            beside(C)
            assert(R:command(player,{id=id,revision=S.graph.links[id].revision,side='a',op='remove'}))
            assert(rope:getContainer()==storage);intact(body)
            -- Clock retirement is still pending: it must not be abandoned.
            frame();local pending=fullTicks;frame();assert(fullTicks==pending+1)
            CVPSkeletonNative.retire=function() return true end
            now=now+5000
            frame();local before=fullTicks
            for i=1,100 do frame() end
            assert(fullTicks==before and rope:getContainer()==storage)
        ''')

    def test_pending_commands_dirty_save_and_external_revision_are_not_skipped(self):
        l=self.fixture();l.execute('''
            frame();S.pending.test={at=now};frame();assert(fullTicks==2);S.pending.test=nil
            S.rewires={test={at=now}};frame();assert(fullTicks==3);S.rewires={}
            S.dirty=true;frame();assert(fullTicks==4);assert(S:flush())
            frame();local before=fullTicks
            local graph=require('CVP_LinkGraph').copy(S.graph);graph.revision=graph.revision+1
            assert(E.editLinks(graph,S.persistedRevision));frame()
            assert(fullTicks==before+1 and S.persistedRevision==graph.revision)
        ''')

    def test_empty_state_error_is_retried_after_backoff(self):
        l=self.fixture();l.execute('''
            frame();local discover=H.discover;H.discover=function() error('discovery failed') end
            now=now+1000;local ok=R:tick({player},.01);assert(not ok)
            H.discover=discover;now=now+5000;frame();assert(fullTicks==2 and not R.error)
        ''')

    def test_revision_failure_uses_normal_backoff_and_recovers(self):
        l=self.fixture();l.execute('''
            frame();local revision=E.linkRevision
            E.linkRevision=function() error('ledger unavailable') end
            local called,ok=pcall(R.tick,R,{player},.01)
            assert(called and not ok and R.retryAt and R.error)
            E.linkRevision=revision;now=now+5000;frame()
            assert(fullTicks==2 and not R.error)
        ''')

    def test_pending_pose_and_wear_recovery_wake_empty_authority(self):
        l=self.fixture();l.execute('''
            frame();Sim.pendingPoses={};frame()
            assert(fullTicks==2 and not Sim.pendingPoses)
            Sim.wearPending[body]=body:getSquare();frame()
            assert(fullTicks==3 and not Sim.wearPending[body])
            frame();assert(fullTicks==3)
        ''')


if __name__=='__main__':unittest.main()
