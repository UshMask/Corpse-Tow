"""Persistent connection identity, endpoint resolution and network compatibility."""
import unittest
from test_core_lifecycle import environment
from test_multiplayer import vm, copy_packet, deliver


class ConnectionTests(unittest.TestCase):
    def test_independent_id_and_endpoints_survive_reattach_with_new_connection(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    assert(attach('neck'))
                    local r=links()[1];local c=body.md.CVPTether.connection
                    local bodyKey=body.md.CVPBodyKey
                    assert(c.id~=bodyKey and c.id~=tostring(rope.id) and c.id~=tostring(r.id))
                    assert(c.a.kind=='vehicle' and c.a.key==car.md.CVPVehicleKey and c.a.point=='hitch')
                    assert(c.b.kind=='body' and c.b.key==bodyKey and c.b.point=='neck')
                    assert(r.connection.id==c.id)
                    assert(r.connection.a.object==car and r.connection.b.object==body)
                    assert(c.a.object==nil and c.b.object==nil)
                    assert(detach());assert(not body.md.CVPTether)
                    assert(attach('feet'));local next=body.md.CVPTether.connection
                    assert(next.id~=c.id and next.b.key==bodyKey and next.b.point=='feet')
                    assert(rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
                ''')

    def test_saved_endpoints_are_the_only_source_of_vehicle_and_point(self):
        for server in (False, True):
            lua=environment(server)
            lua.execute("""
                assert(attach('neck'));local md=body.md.CVPTether
                assert(md.version==3 and md.equipmentKey and md.vehicle==nil and md.point==nil)
                assert(md.connection.b.point=='neck')
            """)

    def test_roundtrip_into_fresh_objects_preserves_connection_identity(self):
        for server in (False, True):
            with self.subTest(server=server):
                old = environment(server)
                old.execute("assert(attach('neck'))")
                body_data = copy_packet(old.globals().body.md)
                vehicle_data = copy_packet(old.globals().car.md)
                equipment_data = copy_packet(old.eval('serializeEquipment()'))
                fresh = environment(server)
                fresh.globals().savedBody = fresh.table_from(body_data, recursive=True)
                fresh.globals().savedVehicle = fresh.table_from(vehicle_data, recursive=True)
                fresh.globals().savedEquipment = fresh.table_from(equipment_data, recursive=True)
                fresh.execute('''
                    body.md=savedBody;car.md=savedVehicle
                    storage:Remove(rope);loadEquipment(savedEquipment)
                    rope=assert(require('CVP_Equipment').get(body.md.CVPTether.equipmentKey,body.md.CVPBodyKey))
                    -- The connection must not depend on the runtime/native body lookup key.
                    body.netID='9007199254740999'
                    local before=uuidSequence
                    restore();restore();local r=links()[1]
                    assert(#links()==1 and r.connection.id==savedBody.CVPTether.connection.id)
                    assert(r.connection.a.object==car and r.connection.b.object==body)
                    assert(r.point=='neck' and uuidSequence==before)
                    assert(detach() and rope.owner==storage and worldCount(body)==1)
                ''')

    def test_authoritative_equipment_binding_repairs_inconsistent_saved_endpoints(self):
        for server in (False, True):
            for case in ('body-source', 'point', 'body-key', 'partial'):
                with self.subTest(server=server, case=case):
                    lua = environment(server)
                    lua.globals().case = case
                    lua.execute('''
                        assert(attach('feet'));local md=body.md.CVPTether;local originalID=md.connection.id
                        if serverMode then require('CVP_Core').unregister(CVPMPServer.registry,links()[1]);CVPMPServer.byID={}
                        else require('CVP_Core').unregister(CVPRuntime.registry,CVPRuntime.links[1]);CVPRuntime.pending={} end
                        if case=='body-source' then md.connection.a.kind='body'
                        elseif case=='point' then md.connection.b.point='invalid'
                        elseif case=='body-key' then md.connection.b.key='different-body'
                        else md.connection={id='partial'} end
                        restore();restore()
                        assert(#links()==1 and body.md.CVPTether.connection.id==originalID)
                        assert(body.md.CVPTether.connection.b.key==body.md.CVPBodyKey and body.md.CVPTether.connection.b.point=='feet')
                        assert(rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
                    ''')

    def test_server_rejects_detach_for_previous_connection_and_accepts_legacy_request(self):
        lua = environment(True)
        lua.execute('''
            assert(attach());local old=body.md.CVPTether.connection.id
            assert(detach());assert(attach());local current=body.md.CVPTether.connection.id
            command('detach',player,{request=1,id=body.netID,connectionID=old})
            assert(not packets[#packets].args.ok and body.md.CVPTether.connection.id==current)
            assert(rope.owner==CVPEquipmentRuntime.container)
            command('detach',player,{request=2,id=body.netID,connectionID=current})
            assert(packets[#packets].args.ok and rope.owner==storage)
            assert(attach())
            command('detach',player,{request=3,id=body.netID})
            assert(packets[#packets].args.ok and rope.owner==storage)
        ''')

    def state_pair(self):
        server, client = environment(True), vm(False)
        server.execute('assert(attach());now=1000;CVPMPServer.tick()')
        packet = copy_packet(server.globals().packets[1])
        deliver(client, packet)
        client.execute('now=1000;CVPMPClient.tick()')
        return server, client, packet

    def test_client_uses_server_identity_without_generating_ids(self):
        server, client, packet = self.state_pair()
        expected = copy_packet(server.globals().body.md.CVPTether.connection)
        actual = copy_packet(client.globals().body.md.CVPTether.connection)
        self.assertEqual(actual, expected)
        client.execute('''
            getRandomUUID=function() error('client must not mint connection IDs') end
            now=1100;CVPMPClient.tick()
            local r=CVPMPClient.links[body.netID]
            assert(r.connection.a.object==car and r.connection.b.object==body)
            CVPMPClient.queueAction('detach',player,body,car)
            assert(clientPackets[#clientPackets].args.connectionID==r.target.connection.id)
        ''')

    def test_old_terminal_cannot_clear_a_replacement_connection(self):
        server, client, _ = self.state_pair()
        server.execute('''
            assert(detach());now=1200;CVPMPServer.tick()
        ''')
        terminal = copy_packet(server.globals().packets[len(server.globals().packets)])
        server.execute('assert(attach());now=1400;CVPMPServer.tick()')
        current = copy_packet(server.globals().packets[len(server.globals().packets)])
        deliver(client, current)
        client.execute('now=1400;CVPMPClient.tick();saved=body.md.CVPTether.connection.id')
        terminal['args']['sequence'] = current['args']['sequence'] + 1
        deliver(client, terminal)
        client.execute('''
            assert(CVPMPClient.links[body.netID] and body.md.CVPTether.connection.id==saved)
            now=5000;CVPMPClient.tick();assert(not CVPMPClient.links[body.netID])
        ''')
        terminal['args']['sequence'] += 1
        deliver(client, terminal)
        client.execute('assert(body.md.CVPTether.connection.id==saved)')

    def test_client_stops_queued_detach_when_same_body_is_reattached(self):
        server, client, _ = self.state_pair()
        client.execute('''
            deferAction=true;CVPMPClient.queueAction('detach',player,body,car)
            oldAction=queued;oldAction:start()
        ''')
        server.execute('assert(detach());assert(attach());now=1200;CVPMPServer.tick()')
        deliver(client, copy_packet(server.globals().packets[len(server.globals().packets)]))
        client.execute('oldAction:perform();assert(#clientPackets==0)')

    def test_packets_without_connection_are_rejected(self):
        _, client, packet = self.state_pair()
        for row in packet['args']['rows'].values():
            row.pop('connection', None)
        packet['args']['sequence'] += 1
        before=client.globals().CVPMPClient.sequence
        deliver(client, packet)
        self.assertEqual(client.globals().CVPMPClient.sequence,before)

    def test_invalid_connection_packet_is_rejected_before_state_changes(self):
        _, client, packet = self.state_pair()
        row = next(iter(packet['args']['rows'].values()))
        row['connection']['a']['kind'] = 'body'
        packet['args']['sequence'] += 1
        before = client.globals().CVPMPClient.sequence
        deliver(client, packet)
        self.assertEqual(client.globals().CVPMPClient.sequence, before)


if __name__ == '__main__':
    unittest.main()
