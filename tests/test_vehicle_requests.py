"""Menu requests must not promote client-local vehicle identities to authority."""
import unittest
from test_link_multiplayer import Network
from test_link_client import client


class RecordedNetwork(Network):
    def __init__(self):
        self.targets = []
        super().__init__()

    def send(self, packet):
        args = packet['args'].get('args', {})
        target = args.get('target', {})
        if target.get('kind') == 'vehicle':
            self.targets.append(target)
        return super().send(packet)


class VehicleRequestTests(unittest.TestCase):
    def test_mp_first_attachment_ignores_unconfirmed_client_identity(self):
        for stale in ('none', 'legacy', 'local_sql'):
            for route in ('car', 'body', 'held', 'reconnect'):
                with self.subTest(stale=stale, route=route):
                    n = RecordedNetwork(); s = n.server; c = n.clients['owner']
                    if stale!='none':
                        c.execute("car.md.CVPVehicleKey='old-client-key'")
                    if stale=='local_sql':
                        c.execute('car.getSqlId=function() return 999 end')
                    if route == 'reconnect':
                        s.execute("id=link(C,A,rope);beside(S.graph.links[id].a);assert(R:command(player,{op='release',id=id,revision=S.graph.links[id].revision,side='a'}))")
                        n.publish()
                        c.execute("carMenu();choose('IGUI_CVP_ReconnectTrain')")
                    elif route == 'held':
                        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry')"); n.finish()
                        c.execute('carMenu();context.children[1].run()')
                    elif route == 'body':
                        c.execute('menu(body);context.children[1].run()')
                    else:
                        c.execute("carMenu();choose('IGUI_CVP_AutoSequence')")
                    n.finish()
                    self.assertTrue(n.targets)
                    self.assertEqual(n.targets[0]['native'], 17)
                    self.assertNotIn('key', n.targets[0])
                    s.execute('''
                        local count=0;local equipment=require('CVP_Equipment')
                        for _,row in pairs(S.graph.links) do
                            count=count+1
                            if row.a.kind=='vehicle' then assert(row.a.key=='sql:71') end
                            if row.b.kind=='vehicle' then assert(row.b.key=='sql:71') end
                            local item=equipment.get(row.equipment)
                            assert(item==rope or item==chain)
                        end
                        assert(count>0)
                        assert(worldCount(body)==1 and body.inv:getItems():size()==1)
                        assert(worldCount(body2)==1 and body2.inv:getItems():size()==1)
                        local ids={};for id in pairs(S.graph.links) do ids[#ids+1]=id end
                        for _,id in ipairs(ids) do local row=S.graph.links[id]
                            beside(row.a)
                            assert(R:command(player,{op='remove',id=id,revision=row.revision,side='a'}))
                        end
                        assert(rope:getContainer()==storage and chain:getContainer()==storage)
                        assert(storage:getItemWithIDRecursiv(rope:getID())==rope)
                        assert(storage:getItemWithIDRecursiv(chain:getID())==chain)
                    ''')
                    n.pump()
                    c.execute('''
                        assert(localPlayer:getInventory():getItemWithIDRecursiv(rope:getID()))
                        assert(localPlayer:getInventory():getItemWithIDRecursiv(chain:getID()))
                    ''')

    def test_mp_existing_attachment_uses_server_confirmed_key(self):
        n=RecordedNetwork();s=n.server;c=n.clients['owner']
        s.execute('link(C,A,rope)');n.publish()
        c.execute("car.md.CVPVehicleKey='old-client-key';car.getSqlId=function() return 999 end;menu(body2);context.children[1].run()")
        n.finish()
        self.assertTrue(n.targets)
        self.assertEqual(n.targets[0]['key'], 'sql:71')
        s.execute("local count=0;for _ in pairs(S.graph.links) do count=count+1 end;assert(count==2)")

    def test_mp_cancel_with_stale_key_preserves_materials(self):
        n=RecordedNetwork();s=n.server;c=n.clients['owner']
        c.execute("car.md.CVPVehicleKey='old-client-key';carMenu();choose('IGUI_CVP_AutoSequence');CVPMPClient.actions.jobs[localPlayer].feedback.cancelled=true")
        n.finish()
        s.execute('assert(next(S.graph.links)==nil and rope:getContainer()==storage and chain:getContainer()==storage)')
        c.execute('assert(rope:getContainer()==localPlayer:getInventory() and chain:getContainer()==localPlayer:getInventory())')

    def test_server_still_rejects_wrong_persistent_key_with_correct_native_id(self):
        n=RecordedNetwork();s=n.server
        s.execute('''
            local token,why=R:prepare(player,{kind='vehicle',key='sql:999',native=17,point='hitch'},rope:getID())
            assert(not token and why=='vehicle unavailable')
            assert(next(S.graph.links)==nil and rope:getContainer()==storage and chain:getContainer()==storage)
        ''')

    def test_sp_attachment_and_return_preserve_identity(self):
        for route in ('car', 'body'):
            with self.subTest(route=route):
                l=client()
                l.execute("car.md.CVPVehicleKey='old-local-key'")
                l.execute("carMenu();choose('IGUI_CVP_AutoSequence')" if route=='car' else 'menu(body);context.children[1].run()')
                l.execute('''
                    completeJob();local ids={};local equipment=require('CVP_Equipment')
                    for id,row in pairs(S.graph.links) do
                        ids[#ids+1]=id;local item=equipment.get(row.equipment)
                        assert(item==rope or item==chain)
                        if row.a.kind=='vehicle' then assert(row.a.key=='sql:71') end
                        if row.b.kind=='vehicle' then assert(row.b.key=='sql:71') end
                    end
                    assert(#ids>0)
                    for _,id in ipairs(ids) do edit(id,'remove','a') end
                    assert(rope:getContainer()==storage and chain:getContainer()==storage)
                    intact(body);intact(body2)
                ''')


if __name__=='__main__':
    unittest.main()
