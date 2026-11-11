"""Working length is fixed by the actual endpoints, not item type or slot."""
import unittest
from test_core_lifecycle import environment
from test_multiplayer import vm, copy_packet, deliver


class FittedLengthTests(unittest.TestCase):
    def test_car_endpoints_and_saved_length(self):
        for server in (False, True):
            for point, horizontal in (("feet", 2.65), ("neck", 1.53)):
                lua = environment(server)
                lua.globals().point = point
                lua.globals().expected = (horizontal**2 + .675**2)**.5
                lua.execute("""
                    assert(attach(point))
                    local md=body.md.CVPTether;local r=links()[1]
                    assert(math.abs(md.length-expected)<1e-9 and r.length==md.length)
                    local saved=md.length
                    car.x=3
                    for i=1,20 do now=now+16;if serverMode then CVPMPServer.tick() else callbacks.OnTick() end end
                    assert(md.length==saved and r.length==saved)
                    local Core=require 'CVP_Core'
                    local restored=Core.link(body,car,rope,md)
                    assert(restored.length==saved,'loading must not remeasure after movement')
                """)

    def test_short_child_uses_parent_attachment_point_and_survives_restore(self):
        for server in (False, True):
            lua = environment(server)
            lua.execute("""
                assert(attach('neck'));local parent=links()[1]
                -- Parent neck is x=.47; child's feet x=.65-.65=0.
                body2.x=.65
                if serverMode then
                    assert(CVPMPServer.attach(player,body2,car,chain,'feet','body',body,parent.connection.id))
                else CVPTest.attach(player,body2,car,chain,'feet',false,parent) end
                local r=links()[2];local md=body2.md.CVPTether
                assert(math.abs(md.length-.47)<1e-9 and r.length==md.length)
                local Core=require 'CVP_Core';local World=require 'CVP_World'
                assert(World.valid(md))
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                local status,g,v,p=Core.restore(body2,md,Core.loadedVehicles(),reg)
                assert(status=='ready' and p==parent)
                assert(Core.link(body2,v,g,md,p).length==md.length)
            """)

    def test_coincident_endpoints_stay_finite_in_motion(self):
        for server in (False, True):
            lua = environment(server)
            lua.execute("""
                assert(attach('feet'));local parent=links()[1]
                if serverMode then
                    assert(CVPMPServer.attach(player,body2,car,chain,'feet','body',body,parent.connection.id))
                else CVPTest.attach(player,body2,car,chain,'feet',false,parent) end
                local child=links()[2]
                assert(math.abs(child.length-.1)<1e-9)
                for i=1,300 do
                    car.x=2+i*.02;player.x=car.x;now=now+16
                    if serverMode then CVPMPServer.tick() else callbacks.OnTick() end
                    assert(#links()==2)
                    for _,r in ipairs(links()) do
                        assert(not r.failed and r.x==r.x and r.y==r.y and math.abs(r.vx)<100)
                    end
                end
                assert(child.body:getX()>1)
            """)

    def test_short_and_long_lengths_replicate_without_clamping(self):
        for x in (0, -5.8):
            server, client = vm(True), vm(False)
            server.globals().childX = x
            server.execute("""
                body.x=childX;player.x=childX
                assert(CVPMPServer.attach(player,body,car,rope,'feet'))
                player.x=0
                local parent=CVPMPServer.links[1]
                assert(CVPMPServer.attach(player,body2,car,chain,'feet','body',body,parent.connection.id))
                CVPMPServer.tick()
            """)
            for _, packet in server.globals().packets.items():
                if packet["name"] == "state" and packet["player"] == 1:
                    deliver(client, copy_packet(packet))
            root_length = server.globals().body.md.CVPTether.length
            self.assertAlmostEqual(client.globals().CVPMPClient.links[client.globals().body.netID].target.length, root_length)
            if x < -5:
                self.assertGreater(root_length, 8)
            expected = server.globals().body2.md.CVPTether.length
            self.assertAlmostEqual(client.globals().CVPMPClient.links[client.globals().body2.netID].target.length, expected)
            client.execute("CVPMPClient.tick();assert(require('CVP_World').valid(body2.md.CVPTether))")


if __name__ == "__main__":
    unittest.main()
