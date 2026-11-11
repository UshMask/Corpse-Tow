"""Permanent removal used by W900; no Workshop code or live game in these tests."""
import unittest
from test_link_runtime import environment
from test_link_multiplayer import Network


class VehicleTransportTests(unittest.TestCase):
    def test_packing_releases_only_vehicle_end_and_survives_reload(self):
        l = environment()
        l.execute('''
            id=link(C,A,rope);tail=link(A,B,chain);run()
            local x,y=body.x,body.y
            -- W900 copies modData, permanently removes the original, then
            -- creates a different native vehicle on unloading.
            local data=equipmentCopy(car.md)
            R:vehicleRemoved(car);R:vehicleRemoved(car)
            car.getSquare=function() return nil end
            assert(R:save()) -- Removal immediately followed by a normal save.
            assert(S.graph.links[id].a.kind=='ground')
            assert(S.graph.links[tail].a.kind=='body' and S.graph.links[tail].b.kind=='body')
            assert(body.x==x and body.y==y)
            local saved=serializeEquipment();loadEquipment(saved);assert(S:load())
            car.md=data;car.getSqlId=function() return 92 end
            car.getSquare=function() return gridSquare(10,0,0) end
            H.discover();run()
            assert(S.graph.links[id].a.kind=='ground','unloading must not retarget the rope')
            assert(E.get(S.graph.links[id].equipment)==rope)
            assert(E.get(S.graph.links[tail].equipment)==chain)
            intact(body);intact(body2)
        ''')

    def test_unload_is_not_removal_and_failed_write_retries(self):
        l = environment()
        l.execute('''
            id=link(C,A,rope);run()
            local square=car.getSquare
            car.getSquare=function() return nil end;H.discover();run()
            assert(S.graph.links[id].a.kind=='vehicle','ordinary chunk unload')
            car.getSquare=square;H.discover()
            R:vehicleRemoved(car);car.getSquare=function() return nil end
            equipmentWriteFailure=true
            now=now+50;assert(not R:tick({player},.05))
            assert(S.graph.links[id].a.kind=='vehicle')
            assert(E.get(S.graph.links[id].equipment)==rope)
            equipmentWriteFailure=false;now=now+5000;run()
            assert(S.graph.links[id].a.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body)
        ''')

    def test_mp_packing_publishes_ground_end_and_keeps_items(self):
        n=Network();s=n.server
        s.execute('id=link(C,A,rope);tail=link(A,B,chain)');n.publish()
        s.execute('R:vehicleRemoved(car);car.getSquare=function() return nil end')
        n.tick(.05);n.publish()
        s.execute("assert(S.graph.links[id].a.kind=='ground');assert(require('CVP_Equipment').get(S.graph.links[id].equipment)==rope)")
        for c in n.clients.values():
            c.execute("local count=0;for _,r in pairs(CVPMPClient.graph.links) do count=count+1;assert(r.a.kind~='vehicle' and r.b.kind~='vehicle') end;assert(count==2)")

    def test_pending_removal_survives_other_end_edit(self):
        l=environment();l.execute('''
            id=link(C,A,rope);R:vehicleRemoved(car)
            edit(id,'release','b') -- Changes revision while vehicle release is queued.
            assert(R:save())
            assert(S.graph.links[id].a.kind=='ground' and S.graph.links[id].b.kind=='ground')
            assert(E.get(S.graph.links[id].equipment)==rope);intact(body)
        ''')

    def test_mp_trailer_owner_and_legacy_alias_apply_total_load_once(self):
        n=Network();s=n.server
        s.execute('''
            car.md.CVPVehicleKey='legacy-trailer';H.discover()
            root=link(C,A,rope)
            other=link({kind='vehicle',key='legacy-trailer',native=17,point='front'},B,chain)
        ''')
        n.publish()
        for c in n.clients.values():
            c.execute("car.getVehicleTowedBy=function() error('do not redirect the trailer force to its tractor') end")
        n.clients['owner'].execute('physicsOwner=true')
        n.clients['friend'].execute('physicsOwner=false')
        # Let the initially slack attachments reach steady towing first.
        for _ in range(60):n.tick(.035)
        owner=n.clients['owner'];friend=n.clients['friend']
        before=len(owner.globals().impulses)
        n.tick(.035)
        self.assertEqual(len(owner.globals().impulses)-before,1)
        self.assertEqual(len(friend.globals().impulses),0)
        s.execute('car.getNetPlayerId=function() return 2 end')
        for c in (owner,friend): c.execute('car.getNetPlayerId=function() return 2 end')
        owner.execute('physicsOwner=false');friend.execute('physicsOwner=true')
        before=len(owner.globals().impulses)
        for _ in range(5): n.tick(.035)
        self.assertEqual(len(owner.globals().impulses),before)
        self.assertGreater(len(friend.globals().impulses),0)


if __name__ == '__main__':
    unittest.main()
