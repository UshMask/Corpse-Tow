"""Native-style path/action queue drives the real authority, with delayed replies."""
from pathlib import Path
import unittest
from test_link_runtime import environment


def scene(client=False):
    l = environment(); l.globals().clientMode = client
    l.execute("package.preload['CVP_LinkMessages']=assert(loadstring(...))",
              Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkMessages.lua').read_text(encoding='utf-8-sig'))
    l.execute("package.preload['CVP_LinkActions']=assert(loadstring(...))",
              Path('CorpseProxyLab/42/media/lua/client/CVP_LinkActions.lua').read_text(encoding='utf-8-sig'))
    l.execute('''
        function isClient() return clientMode end
        deferAction=true;deferPath=true;requests={}
        api={host=H,graph=function() return S.graph end,ready=function() return connectionReason end}
        function api.request(p,name,args,callback)
            local request={name=name,args=args,callback=callback};requests[#requests+1]=request
            function request:execute()
                if self.executed then return end;self.executed=true
                local previous=clientMode;clientMode=false
                self.ok,self.result,self.reason=R:request(p,name,args)
                clientMode=previous
            end
            function request:reply() self:execute();self.callback(self.ok,self.result,self.reason) end
            if not deferReply then request:reply() end
        end
        Actions=require('CVP_LinkActions').new(api)
        function finishStage()
            local a=assert(queued);a:start()
            if a.complete and not isClient() then a:complete() end
            a:perform();return a
        end
        function finishJob(job)
            local steps=0
            while not job.finished and not job.waiting and steps<100 do finishStage();steps=steps+1 end
            assert(steps<100,'queue did not finish');return job.finished
        end
    ''')
    return l


class LinkActionTests(unittest.TestCase):
    def test_settling_guard_uses_original_position_in_sp_and_mp(self):
        for mp in (False,True):
            l=scene(mp);l.execute("""
                local job=Actions:begin(player,1,'attach');assert(job:watch(A))
                local x,y=body.x,body.y
                move(body,x,y+.5);assert(not job:valid())
                move(body,x,y+.9);assert(not job:valid())
                move(body,x,y+1.1);assert(job:valid()=='IGUI_CVP_BodyMoved')
                move(body,x,y);body.z=1;assert(job:valid()=='IGUI_CVP_BodyMoved')
                intact(body);assert(rope:getContainer()==storage)
            """)

    def test_body_reloaded_during_stage_uses_same_identity_sp_mp(self):
        for mp in (False, True):
            l=scene(mp);l.execute("""
                A.native=body.netID;beside(A)
                local job=Actions:begin(player,1,'attach');assert(job:watch(A))
                job:stage(A,nil,false,function() completed=true end)
                while queued.isPath do finishStage() end
                move(body2,body.x,body.y);body2.angle=body.angle
                body.world=false;body2.md.CVPBodyKey='A';body2.netID=body.netID
                bodies={body2};H.discover()
                assert(queued:isValid());finishStage()
                assert(completed and queued.body==body2 and #requests==0)
            """)

    def test_slow_confirmation_is_visible_and_restores_phase_sp_mp(self):
        for mp in (False, True):
            l=scene(mp);l.execute("""
                deferReply=true
                local job=Actions:begin(player,1,'attach')
                job.feedback.phase='previous';local completed=0
                job:request('prepare',{target=A,gear=rope:getID()},function() completed=completed+1 end)
                local started=job.waiting
                now=started+749;Actions:update();assert(job.feedback.phase=='previous')
                now=started+750;Actions:update();assert(job.feedback.phase=='IGUI_CVP_SaveWaiting')
                requests[1]:reply();assert(completed==1 and job.feedback.phase=='previous')
                local message=require 'CVP_LinkMessages'
                assert(message('equipment operation pending')=='IGUI_CVP_SaveBusy')
            """)

    def test_invalid_release_keeps_specific_reason_and_original_items(self):
        for mp in (False, True):
            for change, reason in (
                ('player.x=body2:getX()+10', 'IGUI_CVP_ActionTooFar'),
                ('player.z=body2:getZ()+1', 'IGUI_CVP_BodyFloor'),
                ('player:getSquare().canReachTo=function() return false end', 'IGUI_CVP_NoPath'),
            ):
                l=scene(mp)
                l.execute('''
                    local mode=clientMode;clientMode=false;id=link(A,B,rope);clientMode=mode
                    job=Actions:command(player,id,S.graph.links[id].revision,'b','release',nil,
                        function(ok,result,reason) assert(not ok);failure=reason end)
                    while queued.isPath do finishStage() end
                ''')
                l.execute(change)
                l.execute('''
                    assert(not queued:isValid());queued:stop()
                    assert(job.finished and #requests==0)
                    clientMode=false -- Inspect the authoritative ledger, never a client inventory copy.
                    assert(S.graph.links[id].b.kind=='body' and E.get(S.graph.links[id].equipment)==rope)
                    intact(body);intact(body2)
                ''')
                self.assertEqual(l.globals().failure,reason)

    def test_release_survives_validity_check_after_sp_complete(self):
        l = scene(); l.execute('''
            local id=link(A,B,rope);local revision=S.graph.links[id].revision
            local job=Actions:command(player,id,revision,'b','release')
            while queued.isPath do finishStage() end
            local a=queued;a:start();assert(a:isValid());a:complete()
            assert(a:isValid(),'SP completion invalidated its own action')
            a:complete();a:perform();a:perform()
            assert(job.finished and #requests==1 and S.graph.links[id].b.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body);intact(body2)
        ''')

    def test_cancel_release_reports_reason_without_changing_link(self):
        for mp in (False, True):
            l = scene(mp); l.execute('''
                local mode=clientMode;clientMode=false;local id=link(A,B,rope);clientMode=mode;local why
                local job=Actions:command(player,id,S.graph.links[id].revision,'b','release',nil,
                    function(ok,result,reason) assert(not ok);why=reason end)
                while queued.isPath do finishStage() end
                queued:stop()
                assert(job.finished and why=='IGUI_CVP_CancelledQueue' and #requests==0)
                clientMode=false;assert(S.graph.links[id].b.kind=='body' and E.get(S.graph.links[id].equipment)==rope)
            ''')

    def test_body_then_hitch_walks_animates_and_commits_once_in_both_modes(self):
        for client in (False, True):
            with self.subTest(client=client):
                l = scene(client); l.execute('''
                    car.x=6;local job=Actions:create(player,A,C,rope)
                    assert(queued.endpoint=='body');queued:start();assert(queued.anim=='Loot')
                    finishStage();assert(#requests==1 and requests[1].name=='prepare')
                    assert(queued.isPath and rope:getContainer()==storage and next(S.graph.links)==nil)
                    finishStage();assert(queued.endpoint=='vehicle');queued:start();assert(queued.anim=='VehicleTrailer')
                    local action=finishStage();action:perform()
                    assert(job.finished and #requests==2 and rope:getContainer()~=storage)
                    local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1)
                    if isClient() then assert(action.complete==nil) else assert(type(action.complete)=='function') end
                    intact(body)
                ''')

    def test_body_to_body_does_not_require_a_vehicle(self):
        l = scene(); l.execute('''
            car.getSquare=function() return nil end
            local job=Actions:create(player,A,B,rope);assert(finishJob(job))
            assert(rope:getContainer()~=storage and #requests==2)
            local row=S.graph.links[requests[2].result.id]
            assert(row.a.key=='A' and row.b.key=='B');intact(body);intact(body2)
        ''')

    def test_batch_prepares_all_gear_at_hitch_before_visiting_any_body(self):
        l = scene(); l.execute('''
            car.x=6;local job=Actions:batch(player,C,{A,B},{rope,chain},false)
            assert(queued.isPath);finishStage();finishStage()
            assert(queued.endpoint=='vehicle' and #requests==1)
            finishStage();assert(#requests==2 and requests[1].name=='prepare' and requests[2].name=='prepare')
            assert(rope:getContainer()==storage and chain:getContainer()==storage and next(S.graph.links)==nil)
            assert(finishJob(job));assert(#requests==4 and requests[3].name=='create' and requests[4].name=='create')
            for _,row in pairs(S.graph.links) do assert(row.a.kind=='vehicle') end
            intact(body);intact(body2)
        ''')

    def test_sequential_batch_uses_previous_body_and_keeps_completed_links_on_cancel(self):
        l = scene(); l.execute('''
            local job=Actions:batch(player,C,{A,B},{rope,chain},true)
            while #requests<2 do finishStage() end
            local id=requests[2].result.id;assert(S.graph.links[id] and chain:getContainer()==storage)
            require('CVP_Feedback').cancel(player);Actions:update()
            assert(job.finished and S.graph.links[id] and chain:getContainer()==storage)
            intact(body);intact(body2)
        ''')
        l = scene(); l.execute('''
            local job=Actions:batch(player,C,{A,B},{rope,chain},true);assert(finishJob(job))
            local first,second=S.graph.links[requests[2].result.id],S.graph.links[requests[4].result.id]
            assert(first.a.kind=='vehicle' and second.a.key=='A' and second.b.key=='B')
        ''')

    def test_batch_preparations_survive_continuous_work_but_expire_when_idle(self):
        l = scene(); l.execute('''
            beside(C);local first=assert(R:prepare(player,C,rope:getID()))
            now=110000;local second=assert(R:prepare(player,C,chain:getID()))
            now=220000;beside(A);assert(R:create(player,first,A))
            now=330000;beside(B);assert(R:create(player,second,B))
            assert(rope:getContainer()~=storage and chain:getContainer()~=storage)
        ''')
        l = scene(); l.execute('''
            beside(C);local first=assert(R:prepare(player,C,rope:getID()))
            now=120001;beside(A);assert(not R:create(player,first,A))
            assert(rope:getContainer()==storage and next(S.graph.links)==nil)
        ''')

    def test_carry_creates_only_one_link_and_does_not_refund_if_take_fails(self):
        l = scene(); l.execute('''
            local job=Actions:carry(player,A,rope);assert(finishJob(job))
            assert(#requests==3 and S.graph.links[requests[2].result.id].b.kind=='held')
            assert(rope:getContainer()~=storage);intact(body)
        ''')
        l = scene(); l.execute('''
            local existing=link(C,B,chain);edit(existing,'release','a');edit(existing,'take','a')
            local job=Actions:carry(player,A,rope);assert(finishJob(job))
            assert(requests[3].ok==false)
            local created=S.graph.links[requests[2].result.id]
            assert(created and created.b.kind=='ground' and E.get(created.equipment)==rope)
            assert(S.graph.links[existing].a.kind=='held');intact(body)
        ''')

    def test_cancel_each_path_or_action_keeps_original_item(self):
        for stage in range(4):
            with self.subTest(stage=stage):
                l = scene(); l.globals().stage = stage
                l.execute('''
                    player.x=-5;car.x=6;local job=Actions:create(player,A,C,rope)
                    for i=1,stage do finishStage() end
                    local action=queued;action:stop();action:perform()
                    assert(job.finished and next(S.graph.links)==nil and rope:getContainer()==storage)
                    intact(body)
                ''')

    def test_changes_between_ends_abort_without_transfer(self):
        for mutation in ('car.x=9', 'body.x=2', 'speed=2', 'storage:Remove(rope)',
                         'driving=true', 'player.isDead=function() return true end'):
            with self.subTest(mutation=mutation):
                l = scene(); l.execute('car.x=6;job=Actions:create(player,A,C,rope);finishStage();' + mutation + '''
                    finishStage();assert(job.finished and next(S.graph.links)==nil)
                    assert(rope:getContainer()~=CVPEquipmentRuntime.container);intact(body)
                ''')

    def test_failed_path_preserves_equipment(self):
        l = scene(); l.execute('''
            player.x=-5;local job=Actions:create(player,A,C,rope);noPath=true;finishStage()
            assert(job.finished and #requests==0 and rope:getContainer()==storage)
        ''')

    def test_free_end_can_be_released_carried_dropped_and_removed_through_actions(self):
        l = scene(); l.execute('''
            local id=link(C,A,rope)
            local function command(op)
                local job=Actions:command(player,id,S.graph.links[id].revision,'a',op)
                assert(finishJob(job));return job
            end
            command('release');assert(S.graph.links[id].a.kind=='ground')
            local job=Actions:command(player,id,S.graph.links[id].revision,'a','take')
            assert(queued.endpoint=='ground');queued:start();assert(queued.anim=='Loot')
            assert(finishJob(job));assert(S.graph.links[id].a.kind=='held')
            player.x=player.x+2;run();command('drop');assert(S.graph.links[id].a.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==rope);command('remove')
            assert(not S.graph.links[id] and rope:getContainer()==storage);intact(body)
        ''')

    def test_failed_bind_does_not_restore_manually_released_end(self):
        l = scene(); l.execute('''
            local id=link(C,A,rope);edit(id,'release','a');edit(id,'take','a');car.x=6
            local job=Actions:command(player,id,S.graph.links[id].revision,'a','bind',C)
            assert(queued.isPath);speed=2;finishStage()
            assert(job.finished and S.graph.links[id].a.kind=='held' and #requests==0)
        ''')

    def test_prepare_reply_gates_second_end_and_duplicate_reply_cannot_repeat_it(self):
        l = scene(True); l.execute('''
            car.x=6;deferReply=true;local job=Actions:create(player,A,C,rope)
            local action=finishStage();assert(job.waiting and queued==action and #requests==1)
            requests[1]:reply();local path=queued;assert(path.isPath)
            requests[1]:reply();assert(queued==path)
            finishStage();finishStage();assert(#requests==2 and job.waiting and rope:getContainer()==storage)
            requests[2]:reply();requests[2]:reply();assert(job.finished and rope:getContainer()~=storage)
        ''')

    def test_cancel_or_timeout_waiting_for_prepare_never_issues_create(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                l = scene(True); l.globals().cancel = cancel
                l.execute('''
                    deferReply=true;local job=Actions:create(player,A,C,rope);finishStage()
                    if cancel then require('CVP_Feedback').cancel(player) else now=11001 end
                    Actions:update();assert(job.finished)
                    requests[1]:reply();assert(#requests==1 and rope:getContainer()==storage and next(S.graph.links)==nil)
                ''')

    def test_lost_create_ack_does_not_rollback_or_duplicate_committed_equipment(self):
        l = scene(True); l.execute('''
            car.x=6;deferReply=true;local job=Actions:create(player,A,C,rope);finishStage();requests[1]:reply()
            finishStage();finishStage();requests[2]:execute()
            assert(rope:getContainer()~=storage);now=11001;Actions:update();assert(job.finished and job.feedback.reason=='IGUI_CVP_ResultUnknown')
            requests[2]:reply();assert(#requests==2)
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==1);intact(body)
        ''')

    def test_stale_connection_is_rejected_before_queued_action_commits(self):
        l = scene(); l.execute('''
            local id=link(C,A,rope);edit(id,'release','a')
            local job=Actions:command(player,id,S.graph.links[id].revision,'a','take')
            edit(id,'take','a');finishStage()
            assert(job.finished and #requests==0 and S.graph.links[id].a.kind=='held')
        ''')


if __name__ == '__main__':
    unittest.main()
