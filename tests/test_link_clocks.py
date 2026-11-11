"""Pause transitions share the graph commit and survive unloaded-body edits."""
import unittest
from test_link_runtime import migration_environment
from test_link_runtime import environment
from test_link_graph import plain


class LinkClockTests(unittest.TestCase):
    def test_old_native_backend_rejects_start_before_graph_migration(self):
        l = migration_environment(); l.execute('''
            local root=legacy(3);CVPSkeletonNative.version=nil
            local replacement=require('CVP_LinkRuntime').new(H)
            local ok,err=replacement:start();assert(not ok and err=='skeleton graph backend unavailable')
            assert(body.md.CVPTether and next(E.links().links)==nil)
        ''')

    def test_post_commit_clock_notification_failure_does_not_undo_success(self):
        l = environment(); l.execute('''
            local calls=0;CVPSkeletonNative.sync=function() calls=calls+1;error('native notification failed') end
            beside(C);local token=assert(R:prepare(player,C,rope:getID()));beside(A)
            local ok,id=R:create(player,token,A)
            assert(ok and S.graph.links[id] and R.clockError and calls==1)
            for i=1,30 do run() end;assert(calls==1 and S.graph.links[id])
            CVPSkeletonNative.sync=function() calls=calls+1 end;now=6000;run()
            assert(calls==2 and not R.clockError and equipmentDisk.bodyClocks.A.paused)
        ''')

    def test_car_disconnect_resumes_unloaded_tail_without_breaking_chain(self):
        l = environment(); l.execute('''
            worldHours=90;local tail=link(A,B,rope)
            assert(not equipmentDisk.bodyClocks.A.paused and not equipmentDisk.bodyClocks.B.paused)
            worldHours=100;local root=link(C,A,chain)
            assert(equipmentDisk.bodyClocks.B.paused and equipmentDisk.bodyClocks.B.elapsed==10)
            body2.sq=nil;worldHours=110;edit(root,'release','a')
            local clock=equipmentDisk.bodyClocks.B
            assert(not clock.paused and clock.at==110 and clock.elapsed==10)
            assert(S.graph.links[tail].a.key=='A' and S.graph.links[tail].b.key=='B')
            worldHours=125;edit(root,'bind','a',C)
            clock=equipmentDisk.bodyClocks.B
            assert(clock.paused and clock.elapsed==25 and clock.at==125)
        ''')

    def test_rejected_graph_write_keeps_pause_until_actual_commit(self):
        l = environment(); l.execute('''
            worldHours=90;local root=link(C,A,rope);local epoch=equipmentDisk.bodyClocks.A.epoch
            worldHours=100;equipmentWriteFailure=true;beside(S.graph.links[root].a)
            local ok=S:command(player,{op='release',id=root,revision=S.graph.links[root].revision,side='a'})
            assert(not ok and equipmentDisk.bodyClocks.A.paused and equipmentDisk.bodyClocks.A.epoch==epoch)
            equipmentWriteFailure=false;worldHours=105;edit(root,'release','a')
            assert(not equipmentDisk.bodyClocks.A.paused and equipmentDisk.bodyClocks.A.at==105)
            assert(E.get(S.graph.links[root].equipment)==rope)
        ''')

    def test_restart_preserves_elapsed_counter_and_enrollment(self):
        first = environment(); first.execute('''
            worldHours=90;root=link(C,A,rope);link(A,B,chain)
            worldHours=100;edit(root,'release','a')
            worldHours=115;edit(root,'bind','a',C)
        ''')
        saved = plain(first.globals().equipmentDisk)
        second = environment(saved)
        self.assertEqual(saved['bodyClocks'], plain(second.globals().CVPEquipmentRuntime['data']['bodyClocks']))

    def test_clock_cleanup_waits_for_body_checkpoint_and_retries_without_spam(self):
        l = environment(); l.execute('''
            worldHours=90;local root=link(C,A,rope)
            worldHours=100;edit(root,'remove','a')
            assert(equipmentDisk.bodyClocks.A and next(equipmentDisk.graph.links)==nil)
            local calls=0;CVPSkeletonNative={retire=function(b,epoch)
                calls=calls+1;assert(b==body and epoch==equipmentDisk.bodyClocks.A.epoch);return true
            end}
            equipmentCheckpointFailure=true;assert(not E.observeClock(body))
            for i=1,30 do now=now+50;assert(not E.observeClock(body)) end
            assert(calls==1 and equipmentDisk.bodyClocks.A and rope:getContainer()==storage)
            equipmentCheckpointFailure=false;now=now+5000;assert(E.observeClock(body))
            assert(calls==2 and not equipmentDisk.bodyClocks.A and next(equipmentDisk.rows)==nil)
            assert(E.observeClock(body) and calls==2);intact(body)
        ''')

    def test_failed_clock_cleanup_write_preserves_counter_for_retry(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);edit(root,'remove','a')
            CVPSkeletonNative={retire=function() return true end}
            equipmentWriteFailure=true;assert(not E.observeClock(body));assert(equipmentDisk.bodyClocks.A)
            equipmentWriteFailure=false;now=6000;assert(E.observeClock(body));assert(not equipmentDisk.bodyClocks.A)
        ''')

    def test_runtime_syncs_loaded_graph_bodies_and_retires_confirmed_deletion(self):
        l = environment(); l.execute('''
            local observed={};CVPSkeletonNative={sync=function(b)
                observed[b.md.CVPBodyKey]=equipmentDisk.bodyClocks[b.md.CVPBodyKey].paused
            end,retire=function() return true end}
            local root=link(C,A,rope);link(A,B,chain);run()
            assert(observed.A and observed.B)
            body.sq:removeCorpse(body);run();run()
            assert(not equipmentDisk.bodyClocks.A and equipmentDisk.bodyClocks.B and observed.B==true)
            assert(not body.world);intact(body2)
        ''')

    def test_unloaded_fully_unlinked_body_keeps_pending_clock(self):
        l = environment(); l.execute('''
            local root=link(C,A,rope);run();body.sq=nil
            edit(root,'remove','a');run()
            assert(equipmentDisk.bodyClocks.A and not equipmentDisk.bodyClocks.A.paused)
            assert(rope:getContainer()==storage and next(S.graph.links)==nil)
        ''')

    def test_corrupt_clock_is_rejected_before_any_transfer(self):
        first = environment(); first.execute('link(C,A,rope)')
        saved = plain(first.globals().equipmentDisk); saved['bodyClocks']['A']['elapsed'] = -1
        second = environment()
        second.globals().saved = second.table_from(saved, recursive=True)
        second.execute('''
            loadEquipment(saved);E=require 'CVP_Equipment'
            local graph,err=E.links();assert(not graph and err=='invalid body clock')
            assert(body.inv:getItems():size()==1 and storage:getItems():contains(rope))
        ''')


if __name__ == '__main__':
    unittest.main()
