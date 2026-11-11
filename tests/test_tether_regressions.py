import unittest
from test_multiplayer import vm, copy_packet, deliver
from test_stock_visuals import single_player

class TetherRegressions(unittest.TestCase):
    def test_terminal_clears_metadata_after_tracking_timeout(self):
        s,c=vm(True),vm(False)
        s.execute('assert(CVPMPServer.attach(player,body,car,rope));now=1000;CVPMPServer.tick()')
        deliver(c,copy_packet(s.globals().packets[1]))
        c.execute('now=1000;CVPMPClient.tick();now=5000;CVPMPClient.tick();assert(body.md.CVPTether);body.x=12')
        s.execute('assert(CVPMPServer.detach(player,body));now=6000;CVPMPServer.tick()')
        packet=copy_packet(s.globals().packets[len(s.globals().packets)-1])
        deliver(c,packet)
        c.execute('assert(not body.md.CVPTether);assert(body.x==12,"old terminal must not move an untracked body")')

    def test_loot_mass_refresh_in_sp_and_server(self):
        for server in (False,True):
            with self.subTest(server=server):
                lua=vm(True) if server else single_player()
                lua.execute(('assert(CVPMPServer.attach(player,body,car,rope));local r=CVPMPServer.links[1]' if server else
                             'CVPTest.attach(player,body,car,rope);local r=CVPTest.links()[1]')+"""
                    local initial=r.mass
                    local heavy=item('Base.TestHeavy');heavy.getActualWeight=function() return 100 end
                    body.inv:AddItem(heavy)
                    now=2000;callbacks.OnTick()
                    assert(r.mass==initial+100,'added loot must increase towing mass')
                    body.inv:Remove(heavy)
                    now=4000;callbacks.OnTick()
                    assert(r.mass==initial,'removed loot must decrease towing mass')
                """)

if __name__=='__main__': unittest.main()
