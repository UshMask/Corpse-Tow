"""Independent equipment through the authoritative core and SP/server adapters."""
import unittest

from test_core_lifecycle import environment
from test_multiplayer import vm, copy_packet, deliver


class EquipmentIntegrationTests(unittest.TestCase):
    def test_all_materials_stay_out_of_corpse_and_return_original_once(self):
        for server in (False, True):
            for material in ('Base.Rope', 'Base.HeavyChain', 'Base.HeavyChain_Hook'):
                with self.subTest(server=server, material=material):
                    lua = environment(server)
                    lua.globals().material = material
                    lua.execute('''
                        local E=require 'CVP_Equipment'
                        rope=item(material);rope.md.keep={nested=17};storage:AddItem(rope)
                        local original=rope;local loot=body.inv.rows[1]
                        assert(attach())
                        local md=body.md.CVPTether;local key=md.equipmentKey
                        assert(md.version==3 and type(key)=='string' and E.get(key,md.connection.b.key)==original)
                        assert(rope.owner==CVPEquipmentRuntime.container and rope.owner~=body.inv and rope.owner~=storage)
                        assert(#body.inv.rows==1 and body.inv.rows[1]==loot and loot.owner==body.inv)
                        assert(detach() and rope==original and rope.owner==storage and rope.md.keep.nested==17)
                        assert(not E.get(key) and not E.release(key,storage))
                        local found=0;for _,row in ipairs(storage.rows) do if row.id==rope.id then found=found+1 end end
                        assert(found==1 and #body.inv.rows==1 and body.inv.rows[1]==loot)
                    ''')

    def test_rewire_changes_connections_without_changing_equipment_keys(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    local core=require 'CVP_Core';local E=require 'CVP_Equipment'
                    assert(attach());local first=body;local firstKey=body.md.CVPTether.equipmentKey
                    local firstConnection=body.md.CVPTether.connection.id
                    local original=rope;body=body2;body.x=1;rope=chain;assert(attach())
                    local secondKey=body.md.CVPTether.equipmentKey
                    local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                    local R=require 'CVP_Rewire';assert(R.apply(reg,car,assert(R.plan(car,reg.links)),player))
                    assert(first.md.CVPTether.connection.id~=firstConnection)
                    assert(first.md.CVPTether.equipmentKey==firstKey and body.md.CVPTether.equipmentKey==secondKey)
                    assert(E.get(firstKey,first.md.CVPTether.connection.b.key)==original)
                    assert(E.get(secondKey,body.md.CVPTether.connection.b.key)==chain)
                    assert(#first.inv.rows==1 and #body.inv.rows==1)
                    for _,r in ipairs(reg.links) do assert(require('CVP_World').gear(r.body,r.md)==r.gear) end
                ''')

    def test_schema_two_migrates_only_when_vehicle_loaded_and_only_once(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    local core=require 'CVP_Core';local World=require 'CVP_World'
                    local md=core.metadata(World.vehicleKey(car),rope,1,'feet',body)
                    md.version=2;body.md.CVPTether=md
                    storage:Remove(rope);body.inv:AddItem(rope)
                    local status=core.restore(body,md,{},core.registry({}))
                    assert(status=='waiting' and md.version==2 and not md.equipmentKey and rope.owner==body.inv)
                    local original=rope
                    status=core.restore(body,md,core.loadedVehicles(),core.registry({}))
                    assert(status=='ready' and md.version==3 and type(md.equipmentKey)=='string')
                    assert(rope==original and rope.owner==CVPEquipmentRuntime.container and #body.inv.rows==1)
                    local key=md.equipmentKey
                    for i=1,3 do assert(core.restore(body,md,core.loadedVehicles(),core.registry({}))=='ready') end
                    assert(body.md.CVPTether==md and md.equipmentKey==key and World.gear(body,md)==original)
                    assert(core.release(body,rope,storage) and rope.owner==storage)
                ''')

    def test_failed_activation_and_refused_rollback_keep_recovery_address(self):
        lua = environment(False)
        lua.execute('''
            local core=require 'CVP_Core';local World=require 'CVP_World'
            local md=core.metadata(World.vehicleKey(car),rope,1,'feet',body)
            local add=storage.AddItem;local rolledBack=false
            local ok,err=core.attach(body,rope,md,function()
                storage.AddItem=function() end;error('registration failed')
            end,function() rolledBack=true end)
            assert(not ok and err and rolledBack)
            assert(body.md.CVPTether==md and md.equipmentKey and World.gear(body,md)==rope)
            assert(rope.owner==CVPEquipmentRuntime.container and #body.inv.rows==1)
            storage.AddItem=add
            assert(core.release(body,rope,storage) and not body.md.CVPTether and rope.owner==storage)
            assert(not require('CVP_Equipment').get(md.equipmentKey))
        ''')

    def test_unavailable_equipment_waits_without_discarding_connection(self):
        lua = environment(False)
        lua.execute('''
            assert(attach());local md=body.md.CVPTether;local key=md.equipmentKey
            local E=require 'CVP_Equipment';local get=E.get
            E.get=function() return nil,'recovery pending' end
            local status=require('CVP_Core').restore(body,md,require('CVP_Core').loadedVehicles(),CVPRuntime.registry)
            assert(status=='waiting' and body.md.CVPTether==md and md.equipmentKey==key)
            E.get=get;assert(require('CVP_World').gear(body,md)==rope and detach())
        ''')

    def test_orphan_invalid_connection_clears_without_touching_items(self):
        lua = environment(False)
        lua.execute('''
            local md={version=3,equipmentKey='unrecognized-saved-key',connection={}}
            body.md.CVPTether=md
            local loot=body.inv.rows[1];local owner=rope.owner
            assert(not require('CVP_World').data(body))
            assert(body.md.CVPTether==nil)
            assert(body.inv.rows[1]==loot and #body.inv.rows==1 and rope.owner==owner)
            assert(attach() and detach())
        ''')

    def test_failed_rewire_checkpoint_preserves_entire_previous_group(self):
        for server in (False, True):
            lua = environment(server)
            lua.execute('''
                assert(attach());local first=body
                body=body2;body.x=1;rope=chain;assert(attach())
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                local a,b=first.md.CVPTether,body.md.CVPTether
                local members=car.md.CVPConnections;local r1,r2=reg.links[1],reg.links[2]
                local R=require 'CVP_Rewire';local order=assert(R.plan(car,reg.links))
                equipmentWriteFailure=true
                assert(not R.apply(reg,car,order,player))
                equipmentWriteFailure=false
                assert(first.md.CVPTether==a and body.md.CVPTether==b and car.md.CVPConnections==members)
                assert(reg.links[1]==r1 and reg.links[2]==r2 and not r1.parent and not r2.parent)
                assert(require('CVP_World').data(first)==a and require('CVP_World').data(body)==b)
                assert(R.apply(reg,car,order,player))
            ''')

    def test_disabling_towing_keeps_equipment_and_allows_manual_removal(self):
        for server in (False, True):
            lua = environment(server)
            lua.execute('''
                assert(attach());local md=body.md.CVPTether;local original=rope
                local x,y=body.x,body.y;local writes=equipmentWrites
                SandboxVars.CorpseProxyLab.Enabled=false;car.x=5
                for i=1,5 do now=now+100;if serverMode then CVPMPServer.tick() else callbacks.OnTick() end end
                assert(#links()==1 and body.x==x and body.y==y and body.md.CVPTether==md)
                assert(require('CVP_World').gear(body,md)==original and equipmentWrites==writes)
                assert(require('CVP_Rewire').validate(serverMode and CVPMPServer.registry or CVPRuntime.registry,car,{},player)=='IGUI_CVP_TowingDisabled')
                if serverMode then
                    local ok,why=CVPMPServer.attach(player,body2,car,chain)
                    assert(not ok and why=='IGUI_CVP_TowingDisabled')
                else assert(CVPTest.reason(player,body2,car,chain)==getText('IGUI_CVP_TowingDisabled')) end
                assert(chain.owner==storage and detach() and original.owner==storage)
            ''')

    def test_disabled_observer_can_still_request_manual_detach(self):
        server, client = environment(True), vm(False)
        server.execute('assert(attach());now=1000;CVPMPServer.tick()')
        deliver(client, copy_packet(server.globals().packets[1]))
        client.execute('''
            now=1000;CVPMPClient.tick();SandboxVars.CorpseProxyLab.Enabled=false
            assert(CVPMPClient.queueAction('detach',player,body,car))
            assert(#clientPackets==1 and clientPackets[1].name=='detach')
            assert(clientPackets[1].args.connectionID==CVPMPClient.links[body.netID].target.connection.id)
        ''')

    def test_rewire_ledger_repairs_older_body_and_vehicle_saves(self):
        for server in (False, True):
            with self.subTest(server=server):
                old = environment(server)
                old.execute('''
                    assert(attach());local first=body
                    require('CVP_World').move(body2,1,0,0,gridSquare(1,0,0))
                    body=body2;rope=chain;assert(attach())
                    before={first=equipmentCopy(first.md),second=equipmentCopy(body.md),car=equipmentCopy(car.md)}
                    before.car.CVPConnections['stale-unknown-id']=true
                    local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                    local R=require 'CVP_Rewire';assert(R.apply(reg,car,assert(R.plan(car,reg.links)),player))
                    saved={old=before,equipment=serializeEquipment(),first=equipmentCopy(first.md),second=equipmentCopy(body.md)}
                ''')
                fresh = environment(server)
                fresh.globals().saved = fresh.table_from(copy_packet(old.globals().saved), recursive=True)
                fresh.execute('''
                    storage:Remove(rope);storage:Remove(chain)
                    local oldFirst=saved.old.first.CVPTether.connection.id;local oldSecond=saved.old.second.CVPTether.connection.id
                    body.md=saved.old.first;body2.md=saved.old.second;car.md=saved.old.car
                    require('CVP_World').move(body2,1,0,0,gridSquare(1,0,0))
                    loadEquipment(saved.equipment)
                    if not serverMode then CVPTest.discover(body2:getSquare()) end
                    for i=1,4 do restore() end
                    assert(#links()==2 and (links()[1].parent~=nil)~=(links()[2].parent~=nil))
                    assert(body.md.CVPTether.connection.id==saved.first.CVPTether.connection.id)
                    assert(body2.md.CVPTether.connection.id==saved.second.CVPTether.connection.id)
                    local members=car.md.CVPConnections
                    assert(not members[oldFirst] and not members[oldSecond])
                    assert(members[saved.first.CVPTether.connection.id] and members[saved.second.CVPTether.connection.id])
                    assert(not members['stale-unknown-id'] and #body.inv.rows==1 and #body2.inv.rows==1)
                ''')

    def test_attach_waits_for_legacy_membership_checkpoint(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    local Core=require 'CVP_Core';local World=require 'CVP_World'
                    local key=World.vehicleKey(car);local members={sleepingLegacy=true}
                    car.md.CVPConnections=members;equipmentWriteFailure=true
                    assert(not attach() and rope.owner==storage and not body.md.CVPTether)
                    assert(car.md.CVPConnections==members and members.sleepingLegacy)
                    assert(not Core.loadedVehicles()[key])
                    equipmentWriteFailure=false
                    assert(attach() and car.md.CVPConnections.sleepingLegacy)
                    assert(car.md.CVPConnections[body.md.CVPTether.connection.id])
                    assert(detach() and car.md.CVPConnections.sleepingLegacy)
                    car.md.CVPConnections={stale=true}
                    assert(Core.observeVehicle(car))
                    assert(car.md.CVPConnections.sleepingLegacy and not car.md.CVPConnections.stale)
                ''')

    def test_legacy_migration_waits_for_membership_checkpoint(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    local Core=require 'CVP_Core';local World=require 'CVP_World'
                    local key=World.vehicleKey(car);local md=Core.metadata(key,rope,1,'feet',body)
                    md.version=2;body.md.CVPTether=md
                    storage:Remove(rope);body.inv:AddItem(rope)
                    local members={sleepingLegacy=true};members[md.connection.id]=true
                    car.md.CVPConnections=members;equipmentWriteFailure=true
                    assert(Core.restore(body,md,{[key]=car},Core.registry({}))=='waiting')
                    assert(md.version==2 and not md.equipmentKey and rope.owner==body.inv)
                    assert(car.md.CVPConnections==members)
                    equipmentWriteFailure=false
                    assert(Core.restore(body,md,{[key]=car},Core.registry({}))=='ready')
                    assert(md.version==3 and rope.owner==CVPEquipmentRuntime.container)
                    assert(car.md.CVPConnections.sleepingLegacy)
                ''')


if __name__ == '__main__':
    unittest.main()
