"""Actual 0.4 SP entry point, menus and native-style queues, not the legacy UI fixture."""
from pathlib import Path
import json
import unittest
from test_link_actions import scene

SOURCE = Path('CorpseProxyLab/42/media/lua/client/CVP_Client.lua')


def client(start=True):
    l = scene()
    for name, directory in (('CVP_LinkMenu', 'client'), ('CVP_LinkPresentation', 'shared')):
        l.execute("package.preload[...]=assert(loadstring(select(2,...)))", name,
                  Path(f'CorpseProxyLab/42/media/lua/{directory}/{name}.lua').read_text(encoding='utf-8-sig'))
    l.execute('''
        function getNumActivePlayers() return 1 end
        player.getPlayerNum=function() return 0 end
        drawn={};tracked={};drawCalls=0
        CVPFreeRopeScene={version=function() return '1-free-endpoints' end,
            update=function(id,points) drawn[id]=equipmentCopy(points);drawCalls=drawCalls+1 end,
            vehicle=function() end,remove=function(id) drawn[id]=nil end}
        installNativeRopeScene(CVPFreeRopeScene)
        CVPViewpoint={track=function(b) tracked[b]=true end,untrack=function(b) tracked[b]=nil end,
            clear=function() tracked={} end}
        function choose(key,...) local label=getText(key,...)
            for _,opt in ipairs(options) do if opt.label==label then assert(not opt.notAvailable,opt.toolTip and opt.toolTip.description);opt.run();return opt end end
            error('option missing: '..label)
        end
        function activeJob() return assert(CVPRuntime.actions.jobs[player]) end
        function completeJob() local job=activeJob();assert(finishJob(job));return job end
    ''')
    l.execute(SOURCE.read_text(encoding='utf-8-sig'))
    if start:
        l.execute('callbacks.OnGameStart();assert(not CVPRuntime.error);R=CVPRuntime.authority;S=R.service;H=R.host;Sim=R.simulation')
    return l


class LinkClientTests(unittest.TestCase):
    def test_fixed_endpoint_samples_reused_only_in_current_tick(self):
        l=client();l.execute('''
            local id=link(C,A,rope)
            local original=H.samples;local calls=0
            H.samples=function(...) calls=calls+1;return original(...) end
            local presentation=CVPRuntime.presentation;local update=presentation.update
            local previous
            presentation.update=function(self,graph,points,dt)
                assert(points and points[id] and points~=previous)
                local expected=original(graph)
                for _,side in ipairs({'a','b'}) do
                    local a,b=points[id][side],expected[id][side]
                    assert(a.x==b.x and a.y==b.y and a.z==b.z and a.kind==b.kind)
                end
                previous=points
                return update(self,graph,points,dt)
            end
            for i=1,5 do car.x=car.x+.05;tick() end
            assert(calls==5 and drawn[id]);intact(body)
        ''')

    def test_native_versions_cached_but_replacement_and_missing_bridge_recover(self):
        l=client();l.execute('''
            calls=0
            CVPFreeRopeScene.version=function() calls=calls+1;return '1-free-endpoints' end
            for i=1,5 do tick() end
            assert(calls==1 and not CVPRuntime.error)
            local bridge=CVPFreeRopeScene;CVPFreeRopeScene=nil;tick()
            assert(CVPRuntime.error)
            CVPFreeRopeScene=bridge;tick();assert(not CVPRuntime.error)
            bridge.version=function() return 'wrong' end;tick();assert(CVPRuntime.error)
            bridge.version=function() calls=calls+1;return '1-free-endpoints' end
            tick();tick();assert(calls==2 and not CVPRuntime.error)
        ''')

    def test_tracking_registry_reused_and_released(self):
        l=client();l.execute('''
            trackCalls=0
            CVPViewpoint.track=function(b) tracked[b]=true;trackCalls=trackCalls+1 end
            link(A,B,rope);tick();local registry=CVPRuntime.tracked
            for i=1,5 do tick() end
            assert(trackCalls==2 and CVPRuntime.tracked==registry)
            menu(body2);choose('IGUI_CVP_DetachBody');completeJob()
            menu(body);choose('IGUI_CVP_LinkRemoveRope');completeJob();tick()
            assert(not next(tracked));intact(body);intact(body2)
        ''')

    def test_read_only_bridge_reports_current_graph_and_rejects_retired_commands(self):
        l = client(); l.execute('''
            link(A,B,rope);files={}
            function getFileWriter(name) return {write=function(_,s) files[name]=s end,close=function() end} end
            function getFileReader(name)
                if not files[name] then return end;local rows={}
                for line in files[name]:gmatch('([^\\n]+)') do rows[#rows+1]=line end
                local i=0;return {readLine=function() i=i+1;return rows[i] end,close=function() end}
            end
            CVPRopeScene=nil
            CVPFreeRopeScene.error=function() return '' end
            CVPFreeRopeScene.count=function() return 1 end
            CVPFreeRopeScene.captures=function() return 2 end
            CVPFreeRopeScene.segments=function() return 3 end
        ''')
        l.execute("package.preload['PZT_Control']=assert(loadstring(...))", Path('tools/pz-test/mod/42/media/lua/shared/PZT_Control.lua').read_text())
        l.execute(Path('CVPAgent/42/media/lua/client/CVPA_Bridge.lua').read_text(encoding='utf-8-sig'))
        for i, command in enumerate(('corpse.status', 'corpse.scene-status', 'attach', 'scene-reset', 'scene-render', 'corpse.status'), 1):
            l.globals().files['PZTest/request.txt'] = f'{i}\n{l.globals().CVPAgent.session}\n{command}\nunused\nEND\n'
            l.execute('now=now+250;CVPAgent.poll()')
            response = json.loads(l.globals().files['PZTest/response.txt'])
            if command == 'corpse.status':
                self.assertTrue(response['ok']); self.assertTrue(response['result']['ready'])
                self.assertEqual(response['result']['schema'], 4)
                self.assertEqual(response['result']['linkCount'], 1)
                self.assertTrue(response['result']['links'][0]['gearStored'])
            elif command == 'corpse.scene-status':
                self.assertTrue(response['ok']); self.assertEqual(response['result']['links'], 1)
                self.assertEqual(response['result']['captures'], 2)
                self.assertEqual(response['result']['segments'], 3)
            else:
                self.assertFalse(response['ok']); self.assertEqual(response['error'], 'unknown command')
        l.execute('intact(body);intact(body2);assert(rope:getContainer()~=storage)')
        l.globals().files['PZTest/request.txt'] = 'stale\nold-session\ncorpse.scene-status\nunused\nEND\n'
        l.execute('now=now+250;CVPAgent.poll()')
        response = json.loads(l.globals().files['PZTest/response.txt'])
        self.assertFalse(response['ok']); self.assertIn('stale session', response['error'])
        l.execute('''
            CVPAgent.lastWriteFailed=true;files['PZTest/response.txt']=nil
            now=now+250;CVPAgent.poll()
        ''')
        self.assertEqual(json.loads(l.globals().files['PZTest/response.txt']), response)
        l.execute('CVPTest=nil;CVPRuntime=nil')
        l.globals().files['PZTest/request.txt'] = f'unloaded\n{l.globals().CVPAgent.session}\ncorpse.status\nunused\nEND\n'
        l.execute('now=now+250;CVPAgent.poll()')
        response = json.loads(l.globals().files['PZTest/response.txt'])
        self.assertTrue(response['ok']); self.assertFalse(response['result']['ready'])

    def test_batch_menu_uses_selected_material_and_explicit_mixed_option(self):
        l = client(); l.execute('''
            carMenu();choose('IGUI_CVP_QuickNearby',getText('IGUI_CVP_Rope'),'1');completeJob()
            local count=0;for _,row in pairs(S.graph.links) do count=count+1;assert(row.material=='Base.Rope') end
            assert(count==1 and chain:getContainer()==storage)
        ''')
        l = client(); l.execute('''
            carMenu();choose('IGUI_CVP_AutoMaterial');completeJob()
            local count=0;for _,row in pairs(S.graph.links) do count=count+1;assert(row.a.kind=='vehicle') end
            assert(count==2 and rope:getContainer()~=storage and chain:getContainer()~=storage)
        ''')

    def test_sequential_menu_respects_limit_before_consuming_equipment(self):
        l = client(); l.execute('''
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1
            carMenu();choose('IGUI_CVP_AutoSequence');completeJob()
            local count=0;for _ in pairs(S.graph.links) do count=count+1 end
            assert(count==1 and chain:getContainer()==storage)
        ''')

    def test_full_connection_preview_highlights_both_bodies(self):
        l = client(); l.execute('''
            link(A,B,rope);menu(body)
            for _,opt in ipairs(options) do if opt.label==getText('IGUI_CVP_LinkRemoveRope') then
                opt.onHighlight(opt,{player=0},true)
                local preview=require('CVP_Feedback').previews[0]
                assert(#preview.bodies==2 and #preview.endpoints==2)
            end end
        ''')

    def test_rewire_menu_visits_every_end_and_commits_atomically(self):
        l = client(); l.execute('''
            local a=link(C,A,rope);local b=link(C,B,chain);carMenu();choose('IGUI_CVP_Rewire')
            local job=activeJob();local animations=0
            while not job.finished do
                if not queued.isPath then animations=animations+1 end
                assert(S.graph.links[b].a.kind=='vehicle');finishStage()
            end
            assert(animations==4 and S.graph.links[b].a.kind=='body')
            assert(E.get(S.graph.links[a].equipment)==rope and E.get(S.graph.links[b].equipment)==chain)
            intact(body);intact(body2)
        ''')

    def test_rewire_cancel_after_preparing_bodies_keeps_original_layout(self):
        l = client(); l.execute('''
            local a=link(C,A,rope);local b=link(C,B,chain);carMenu();choose('IGUI_CVP_Rewire')
            for i=1,4 do finishStage() end
            require('CVP_Feedback').cancel(player);tick()
            assert(S.graph.links[a].a.kind=='vehicle' and S.graph.links[b].a.kind=='vehicle')
            assert(E.get(S.graph.links[a].equipment)==rope and E.get(S.graph.links[b].equipment)==chain)
        ''')

    def test_menu_carry_bind_release_and_return_original_equipment(self):
        l = client(); l.execute('''
            menu(body);choose('IGUI_CVP_LinkStartCarry');assert(queued.endpoint=='body')
            completeJob();local id,row=next(S.graph.links)
            assert(row.b.kind=='held' and E.get(row.equipment)==rope and body.md.CVPTether==nil)
            menu(body2);choose('IGUI_CVP_LinkBindBody');completeJob()
            row=S.graph.links[id];assert(row.a.key=='A' and row.b.key=='B')
            tick();assert(drawn[id] and tracked[body] and tracked[body2])
            menu(body2);choose('IGUI_CVP_DetachBody');completeJob()
            assert(S.graph.links[id].b.kind=='ground' and E.get(row.equipment)==rope)
            menu(body);choose('IGUI_CVP_LinkRemoveRope');completeJob();tick()
            assert(not next(S.graph.links) and rope:getContainer()==storage and not drawn[id] and not tracked[body])
            intact(body);intact(body2)
        ''')

    def test_car_menu_releases_only_roots_and_keeps_body_chain(self):
        l = client(); l.execute('''
            local tail=link(A,B,rope);local root=link(C,A,chain)
            carMenu();choose('IGUI_CVP_DetachFromCar');completeJob()
            assert(S.graph.links[root].a.kind=='ground' and S.graph.links[tail].a.key=='A')
            assert(E.get(S.graph.links[root].equipment)==chain and E.get(S.graph.links[tail].equipment)==rope)
            local x,y=body.x,body2.x;for i=1,5 do car.x=car.x+1;tick() end
            assert(body.x==x and body2.x==y);intact(body);intact(body2)
        ''')

    def test_unkeyed_native_body_can_be_selected_and_identity_persists(self):
        l = client(); l.execute('''
            body.md.CVPBodyKey=nil;H.discover();menu(body)
            choose('IGUI_CVP_LinkStartCarry');completeJob()
            local _,row=next(S.graph.links);assert(row.a.key==body.md.CVPBodyKey and row.a.key)
            assert(equipmentCheckpoints>0 and E.get(row.equipment)==rope)
        ''')

    def test_ground_end_menu_pickup_then_seating_drops_without_refund(self):
        l = client(); l.execute('''
            local id=link(A,B,rope);edit(id,'release','b');beside(S.graph.links[id].b)
            options={};context.children={};callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return player:getSquare() end}},false)
            choose('IGUI_CVP_LinkTakeRope');completeJob();assert(S.graph.links[id].b.kind=='held')
            driving=true;tick();assert(S.graph.links[id].b.kind=='ground' and E.get(S.graph.links[id].equipment)==rope)
            callbacks.OnSave();assert(equipmentDisk.graph.links[id].b.kind=='ground')
        ''')

    def test_disabled_towing_keeps_dismantle_available(self):
        l = client(); l.execute('''
            local id=link(A,B,rope);SandboxVars.CorpseProxyLab.Enabled=false
            menu(body);choose('IGUI_CVP_LinkRemoveRope');completeJob()
            assert(not S.graph.links[id] and rope:getContainer()==storage)
        ''')

    def test_old_java_prevents_migration_and_mutation(self):
        l = client(False); l.execute('''
            local writes=equipmentWrites;CVPSkeletonNative.version=function() return '1' end
            callbacks.OnGameStart();assert(not CVPRuntime.authority.started and equipmentWrites==writes)
            menu();assert(#options==0 and context.children[1].notAvailable)
            CVPRuntime.api.request(player,'prepare',{target=A,gear=rope:getID()},function(ok) assert(not ok) end)
            assert(rope:getContainer()==storage and equipmentWrites==writes)
        ''')

    def test_reloading_does_not_duplicate_events_or_lose_pending_queue(self):
        l = client(); l.globals().reloadSource = SOURCE.read_text(encoding='utf-8-sig')
        l.execute('''
            menu();choose('IGUI_CVP_LinkStartCarry');local job=activeJob()
            local handler=callbacks.OnTick;local authority=R;local gen=CVPRuntime.generation
            assert(loadstring(reloadSource))()
            assert(callbacks.OnTick==handler and CVPRuntime.authority==authority and activeJob()==job)
            assert(CVPRuntime.generation==gen+1);completeJob();assert(next(S.graph.links))
        ''')

    def test_missing_modules_preserve_existing_handlers(self):
        for name in ('CVP_LinkActions', 'CVP_LinkMenu', 'CVP_LinkRuntime', 'CVP_LinkPresentation'):
            with self.subTest(name=name):
                l = client(); l.globals().reloadSource = SOURCE.read_text(encoding='utf-8-sig'); l.globals().missing = name
                l.execute('''
                    local previous=CVPRuntime.handlers;local original=require
                    local chunk=assert(loadstring(reloadSource));setfenv(chunk,setmetatable({require=function(n)
                        if n==missing then return {} end;return original(n)
                    end},{__index=_G}))
                    assert(not pcall(chunk));assert(CVPRuntime.handlers==previous)
                    menu();choose('IGUI_CVP_LinkStartCarry');completeJob();assert(next(S.graph.links))
                ''')

    def test_render_failure_does_not_stop_authority_or_return_gear(self):
        l = client(); l.execute('''
            local id=link(C,A,rope);CVPFreeRopeScene.update=function() error('render failure') end
            for i=1,10 do car.x=car.x+.05;tick() end
            assert(CVPRuntime.visualError and not CVPRuntime.error and S.graph.links[id])
            assert(body.x>0 and E.get(S.graph.links[id].equipment)==rope);intact(body)
        ''')


if __name__ == '__main__':
    unittest.main()
