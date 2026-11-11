import unittest
from test_tie_sequence import setup
from test_stock_visuals import single_player
from test_multiplayer import vm, copy_packet, deliver

class RewireTests(unittest.TestCase):
    def test_rewire_preserves_world_items_and_restores_train(self):
        l=single_player()
        l.execute("""
            body2.x=1
            CVPTest.attach(player,body,car,rope);CVPTest.attach(player,body2,car,chain)
            local old=body.md.CVPTether.connection.id
            local R=require 'CVP_Rewire';local core=require 'CVP_Core'
            local reg=CVPRuntime.registry
            local order=assert(R.plan(car,reg.links))
            assert(R.apply(reg,car,order,player))
            assert(#reg.links==2 and reg.links[2].parent==reg.links[1])
            assert(rope.owner==CVPEquipmentRuntime.container and chain.owner==CVPEquipmentRuntime.container and worldCount(body)==1 and worldCount(body2)==1)
            assert(body.md.CVPTether.connection.id~=old and core.memberCount(car)==2)
            local empty=core.registry({})
            local first=reg.links[1];local status,gear,v=core.restore(first.body,first.md,core.loadedVehicles(),empty)
            assert(status=='ready');core.register(empty,core.link(first.body,v,gear,first.md))
            local second=reg.links[2];assert(core.restore(second.body,second.md,core.loadedVehicles(),empty)=='ready')
            local again,why=R.plan(car,reg.links);assert(not again and why=='IGUI_CVP_RewireOptimal')
        """)

    def test_cancel_preparation_keeps_original_parallel_layout(self):
        for stage in range(8):
            l=setup(single_player())
            l.execute(f"""
                body2.x=1;CVPTest.attach(player,body,car,rope);CVPTest.attach(player,body2,car,chain)
                local a,b=body.md.CVPTether,body2.md.CVPTether
                local R=require 'CVP_Rewire';local reg=CVPRuntime.registry
                local order=assert(R.plan(car,reg.links));local committed=false
                require('CVP_RewireAction').start(player,car,order,function() return R.validate(reg,car,order,player) end,function(done) committed=true;done(R.apply(reg,car,order,player)) end)
                for i=1,{stage} do finishStage() end
                require('CVP_Feedback').cancel(player);queued:perform()
                assert(not committed and body.md.CVPTether==a and body2.md.CVPTether==b)
                assert(not reg.links[1].parent and not reg.links[2].parent)
                assert(rope.owner==CVPEquipmentRuntime.container and chain.owner==CVPEquipmentRuntime.container)
            """)

    def test_complete_preparation_commits_once_after_all_endpoints(self):
        l=setup(single_player())
        l.execute("""
            body2.x=1;CVPTest.attach(player,body,car,rope);CVPTest.attach(player,body2,car,chain)
            local old=body.md.CVPTether
            local R=require 'CVP_Rewire';local reg=CVPRuntime.registry;local commits=0
            local order=assert(R.plan(car,reg.links))
            require('CVP_RewireAction').start(player,car,order,function() return R.validate(reg,car,order,player) end,function(done)
                commits=commits+1;done(R.apply(reg,car,order,player))
            end)
            local steps=0
            while require('CVP_Feedback').active[player] and steps<20 do
                assert(commits==0 and body.md.CVPTether==old)
                steps=steps+1;finishStage()
            end
            assert(steps==8 and commits==1 and reg.links[2].parent==reg.links[1])
            queued:perform();assert(commits==1)
        """)

    def test_server_rejects_stale_or_incomplete_selection(self):
        l=vm(True)
        l.execute("""
            body2.x=1
            assert(CVPMPServer.attach(player,body,car,rope))
            assert(CVPMPServer.attach(player,body2,car,chain))
            local s=CVPMPServer;local R=require 'CVP_Rewire'
            local rows=assert(R.plan(car,s.links));local selection={}
            for _,r in ipairs(rows) do selection[#selection+1]={id=r.id,connection=r.connection.id} end
            assert(not s.rewire(player,car,{selection[1]}))
            local before=body.md.CVPTether;selection[1].connection='stale'
            assert(not s.rewire(player,car,selection));assert(body.md.CVPTether==before)
            selection[1].connection=rows[1].connection.id
            assert(s.rewire(player,car,selection))
            assert(s.links[2].parent==s.links[1] and s.byID[body.netID]==s.registry.byBody[body])
            assert(not s.rewire(player,car,selection),'replayed command must be stale')
        """)

    def test_two_client_snapshots_agree_after_rewire_and_detach(self):
        server=vm(True)
        server.execute("""
            body2.x=1
            assert(CVPMPServer.attach(player,body,car,rope))
            assert(CVPMPServer.attach(player,body2,car,chain))
            local s=CVPMPServer;local rows=assert(require('CVP_Rewire').plan(car,s.links));local selection={}
            for _,r in ipairs(rows) do selection[#selection+1]={id=r.id,connection=r.connection.id} end
            assert(s.rewire(player,car,selection))
            now=1000;s.tick()
        """)
        clients=[vm(False),vm(False)]
        packet=copy_packet(server.globals().packets[1])
        for client in clients:
            deliver(client,packet)
            client.execute("""
                now=1000;CVPMPClient.tick()
                local a,b=CVPMPClient.links[body.netID],CVPMPClient.links[body2.netID]
                assert(a and b and CVPMPClient.rewire)
                assert((a.target.parentConnection~=nil)~=(b.target.parentConnection~=nil))
                assert(worldCount(body)==1 and worldCount(body2)==1)
            """)
        server.execute("""
            local root=CVPMPServer.links[1];player.x=root.body:getX();player.y=root.body:getY()
            assert(CVPMPServer.detach(player,root.body))
            assert(#CVPMPServer.links==0 and rope.owner==storage and chain.owner==storage)
            packets={};now=2000;CVPMPServer.tick()
        """)
        packet=copy_packet(server.globals().packets[1])
        positions=[]
        for client in clients:
            deliver(client,packet);client.execute('now=2000;CVPMPClient.tick();assert(next(CVPMPClient.links)==nil)')
            positions.append(client.execute('return body.x,body.y,body2.x,body2.y'))
        self.assertEqual(positions[0],positions[1])

    def test_mp_menu_rewire_completes_pending_on_current_epoch_ack(self):
        server,client=vm(True),setup(vm(False))
        server.execute('''
            require('CVP_World').move(body2,1,0,0,gridSquare(1,0,0))
            assert(CVPMPServer.attach(player,body,car,rope))
            assert(CVPMPServer.attach(player,body2,car,chain))
            now=1000;CVPMPServer.tick()
        ''')
        deliver(client,copy_packet(server.globals().packets[1]))
        client.execute('''
            now=1000;CVPMPClient.tick()
            -- Native inventory replication, separate from CVP state messages.
            storage:Remove(rope)
            storage:Remove(chain)
            local epoch=CVPMPClient.epoch;CVPMPClient.epoch=nil
            carMenu();assert(menuBranch(context,getText('IGUI_CVP_Rewire')).notAvailable)
            CVPMPClient.epoch=epoch
            carMenu();local option=assert(menuBranch(context,getText('IGUI_CVP_Rewire')))
            assert(not option.notAvailable);option.run()
            for i=1,20 do if #clientPackets>0 then break end;finishStage() end
            assert(#clientPackets==1 and clientPackets[1].name=='rewire')
            assert(require('CVP_Feedback').active[player] and CVPMPClient.pending[1])
        ''')
        request=copy_packet(client.globals().clientPackets[1])
        server.globals().requestArgs=server.table_from(request['args'],recursive=True)
        server.execute("command('rewire',player,requestArgs)")
        deliver(client,copy_packet(server.globals().packets[len(server.globals().packets)]))
        client.execute('''
            assert(not next(CVPMPClient.pending) and not require('CVP_Feedback').active[player])
            assert(not require('CVP_Feedback').last[player].reason)
        ''')
        server.execute('assert(CVPMPServer.links[2].parent==CVPMPServer.links[1])')

if __name__=='__main__': unittest.main()
