"""Simple chain actions: routing, cancellation, limits, authoritative ACK/state ordering."""
import unittest
from test_nearby_neck import sp
from test_multiplayer import vm, copy_packet, deliver


class ChainMenuTests(unittest.TestCase):
    def test_vehicle_builds_one_chain_with_automatic_equipment(self):
        lua = sp()
        lua.execute("""
            body.x=1;body2.x=-2
            batchMenu(true)
            for i=1,4 do finishAction() end
            local links=CVPTest.links()
            assert(#links==2 and links[1].body==body and links[2].body==body2)
            assert(links[2].parent==links[1] and #storage.rows==0)
            assert(require('CVP_Batch').jobs[player]==nil)
        """)

    def test_nearest_action_chooses_free_tail_once(self):
        lua = sp()
        lua.execute("""
            deferAction=false
            CVPTest.attach(player,body,car,rope)
            menu(body2)
            local n=0
            for _,o in ipairs(options) do
                if (o.label==getText('IGUI_CVP_QuickTail',getText('IGUI_CVP_Chain')) or o.label==getText('IGUI_CVP_QuickTail','Chain')) then n=n+1 end
            end
            assert(n==1);tailMenu(body2)
            assert(#CVPTest.links()==2 and CVPTest.links()[2].parent==CVPTest.links()[1])
            local B=require 'CVP_Batch'
            local third=corpse();third.x=.1
            local Core=require 'CVP_Core'
            assert(B.nearest(third,CVPTest.links(),Core.canFollow).body==body2)
        """)

    def test_cancel_child_keeps_completed_prefix(self):
        for cancel in ("queued:stop()", "speed=4;queued:perform()", "noPath=true;queued:perform()"):
            lua = sp()
            lua.execute("""
                batchMenu(true)
                finishAction();finishAction()
                assert(#CVPTest.links()==1)
                queued:start()
            """ + cancel + """
                assert(#CVPTest.links()==1 and chain.owner==storage)
                assert(require('CVP_Batch').jobs[player]==nil)
            """)

    def test_limit_and_no_path(self):
        for setup, expected in (("SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1", 1), ("noPath=true", 0)):
            lua = sp()
            lua.globals().expected = expected
            lua.execute(setup + """
                deferAction=false
                batchMenu(true)
                assert(#CVPTest.links()==expected and chain.owner==storage)
                assert(require('CVP_Batch').jobs[player]==nil)
            """)

    def test_mp_waits_for_ack_and_matching_state(self):
        for state_first in (True, False):
            server, client = vm(True), vm(False)
            server.execute('CVPMPServer.tick()')
            deliver(client,copy_packet(server.globals().packets[1]))
            server.execute('packets={}')
            client.execute("""
                deferAction=true
                rope.getDisplayName=function() return 'Rope' end;chain.getDisplayName=function() return 'Chain' end
                batchMenu(true)
                for i=1,2 do queued:start();queued:perform() end
                assert(#clientPackets==1)
            """)
            packet = copy_packet(client.globals().clientPackets[1])
            server.globals().requestArgs = server.table_from(packet["args"], recursive=True)
            server.execute("player.x=2;command('attach',player,requestArgs);CVPMPServer.tick()")
            packets = [copy_packet(p) for _, p in server.globals().packets.items()]
            result = next(p for p in packets if p["name"] == "result")
            state = next(p for p in packets if p["name"] == "state" and p["player"] == 1)
            self.assertTrue(result["args"]["ok"])
            self.assertIn("connectionID", result["args"])
            if state_first:
                deliver(client, state)
                client.execute("CVPMPClient.tick();assert(#clientPackets==1)")
                deliver(client, result)
            else:
                deliver(client, result)
                client.execute("assert(require('CVP_Batch').jobs[player].wait);assert(#clientPackets==1)")
                deliver(client, state)
                client.execute("CVPMPClient.tick();CVPMPClient.tick()")
            client.execute("""
                for i=1,2 do queued:start();queued:perform() end
                assert(#clientPackets==2 and clientPackets[2].name=='chain')
                assert(clientPackets[2].args.sourceConnection==CVPMPClient.links[body.netID].target.connection.id)
                assert(rope.owner==storage and chain.owner==storage)
            """)
            packet = copy_packet(client.globals().clientPackets[2])
            server.globals().requestArgs = server.table_from(packet["args"], recursive=True)
            server.execute("player.x=0;command('chain',player,requestArgs);assert(#CVPMPServer.links==2)")
            deliver(client, copy_packet(server.globals().packets[len(server.globals().packets)]))
            client.execute("assert(require('CVP_Batch').jobs[player]==nil)")

    def test_mp_single_nearest_menu_action_uses_automatic_gear(self):
        server, client = vm(True), vm(False)
        server.execute("assert(CVPMPServer.attach(player,body,car,rope));CVPMPServer.tick()")
        for _, packet in server.globals().packets.items():
            if packet["name"] == "state" and packet["player"] == 1:
                deliver(client, copy_packet(packet))
        client.execute("""
            CVPMPClient.tick()
            -- Simulate the native inventory packet removing the used rope.
            storage:Remove(rope)
            chain.getDisplayName=function() return 'Chain' end
            deferAction=true;menu(body2)
            local n=0
            for _,o in ipairs(options) do
                if (o.label==getText('IGUI_CVP_QuickTail',getText('IGUI_CVP_Chain')) or o.label==getText('IGUI_CVP_QuickTail','Chain')) then n=n+1 end
            end
            assert(n==1);tailMenu(body2)
            for i=1,2 do queued:start();queued:perform() end
            assert(#clientPackets==1 and clientPackets[1].name=='chain')
            assert(clientPackets[1].args.gear==chain.id and clientPackets[1].args.source==body.netID)
        """)

    def test_mp_timeout_rejection_and_replaced_identity_stop_batch(self):
        for mode in ("reject", "timeout", "replace"):
            lua = vm(False)
            lua.globals().mode = mode
            lua.execute("""
                deferAction=true;rope.getDisplayName=function() return 'Rope' end;chain.getDisplayName=function() return 'Chain' end;batchMenu(true)
                for i=1,2 do queued:start();queued:perform() end
                CVPMPClient.receive('result',{protocol=3,epoch=CVPMPClient.epoch,request=1,ok=mode~='reject',connectionID='created'})
                if mode=='timeout' then now=11000;require('CVP_Batch').update()
                elseif mode=='replace' then
                    CVPMPClient.links[body.netID]={body=body,target={connection={id='replacement'}}}
                    require('CVP_Batch').update()
                end
                assert(require('CVP_Batch').jobs[player]==nil and #clientPackets==1)
            """)


if __name__ == "__main__":
    unittest.main()
