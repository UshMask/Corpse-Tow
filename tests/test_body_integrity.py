"""Corpse/item identity across lifecycle boundaries in the Lua engine model.

The save payload below models engine persistence; it does not exercise native
IsoDeadBody serialization or prove atomic disk writes during a process crash.
"""
import unittest

from test_core_lifecycle import environment
from lua_fixture import copy_packet
from test_trains import train


INVENTORY_MODEL = '''
    function savedItem(a)
        local row={id=a.id,t=a.t,w=a.w,md=a.md,state=a.state,custom=a.custom}
        if a.inv then row.items=savedInventory(a.inv) end
        return row
    end
    function savedInventory(inv)
        local rows={}
        for _,a in ipairs(inv.rows) do rows[#rows+1]=savedItem(a) end
        return rows
    end
    function loadedItem(row)
        local a=item(row.t,row.w);a.id=row.id;a.md=row.md;a.state=row.state;a.custom=row.custom
        if row.items then
            a.kind='InventoryContainer';a.inv=container()
            a.getInventory=function(s) return s.inv end
            for _,child in ipairs(row.items) do a.inv:AddItem(loadedItem(child)) end
        end
        return a
    end
    function assertOwned(inv,seen)
        seen=seen or {}
        for _,a in ipairs(inv.rows) do
            assert(a.owner==inv and not seen[a.id],'lost ownership or duplicate item ID')
            seen[a.id]=true
            if a.inv then assertOwned(a.inv,seen) end
        end
    end
    function setPlayerCorpse(b)
        b.isZombie=function() return false end
        -- Native dead players are IsoDeadBody, not IsoPlayer.
        b.isPlayer=function() return false end
    end
'''


class BodyIntegrityTests(unittest.TestCase):
    def test_displaced_equipment_keeps_addressable_link_and_never_reclaims_item(self):
        for server in (False, True):
            for selected in (1, 2):
                with self.subTest(server=server, selected=selected):
                    lua = train(server, 3)
                    lua.globals().selected = selected
                    lua.execute('''
                        local square=car.getSquare
                        car.getSquare=function() return nil end;stepTrain(.1)
                        assert(#links()==0)
                        local r=trainRecords[selected];local md=r.body.md.CVPTether
                        r.gear:getContainer():Remove(r.gear);storage:AddItem(r.gear)
                        for i=1,4 do restore() end
                        assert(r.body.md.CVPTether==md and r.gear.owner==storage,
                            'missing equipment cleared the parent before tail membership was available')
                        car.getSquare=square
                        for i=1,4 do restore() end
                        assert(#links()==selected-1)
                        for i=selected,3 do
                            assert(trainBodies[i].md.CVPTether and worldCount(trainBodies[i])==1)
                            assert(car.md.CVPConnections[trainRecords[i].connection.id])
                            assert(trainRecords[i].gear.owner==(i==selected and storage or CVPEquipmentRuntime.container))
                        end
                        storage:Remove(r.gear);CVPEquipmentRuntime.container:AddItem(r.gear)
                        for i=1,4 do restore() end
                        assert(#links()==3)
                    ''')

    def test_sp_dormant_detach_waits_for_vehicle_before_releasing_root_or_middle(self):
        for selected in (1, 2):
            with self.subTest(selected=selected):
                lua = train(False, 3)
                lua.globals().selected = selected
                lua.execute('''
                    local square=car.getSquare
                    car.getSquare=function() return nil end;stepTrain(.1)
                    assert(#links()==0)
                    local b=trainBodies[selected];local r=trainRecords[selected]
                    local md=b.md.CVPTether
                    menu(b);click(getText('IGUI_CVP_Detach'))
                    if queued then queued:start();queued:complete();queued:perform() end
                    assert(b.md.CVPTether==md and r.gear.owner==CVPEquipmentRuntime.container,
                        'dormant release lost the unloaded vehicle membership')
                    assert(messages[#messages]==getText('IGUI_CVP_VehicleUnavailable'))
                    car.getSquare=square
                    speed=5;queued=nil
                    menu(b);click(getText('IGUI_CVP_Detach'))
                    assert(not queued and messages[#messages]==getText('IGUI_CVP_StopVehicle'))
                    assert(b.md.CVPTether==md and r.gear.owner==CVPEquipmentRuntime.container)
                    speed=0
                    for i=1,4 do restore() end
                    assert(#links()==3)
                    menu(b);click(getText('IGUI_CVP_DetachNumber',tostring(CVPRuntime.registry.byBody[b].id)))
                    queued:start();queued:complete();queued:perform()
                    assert(#links()==selected-1)
                    for i=selected,3 do
                        assert(not trainBodies[i].md.CVPTether and worldCount(trainBodies[i])==1)
                        assert(trainRecords[i].gear.owner==storage)
                    end
                ''')

    def test_player_corpse_nested_loot_survives_fresh_runtime_restore_and_release(self):
        for server in (False, True):
            for point in ('feet', 'neck'):
                with self.subTest(server=server, point=point):
                    old = environment(server)
                    old.execute(INVENTORY_MODEL)
                    old.execute('''
                        setPlayerCorpse(body)
                        bag=loadedItem({id=1001,t='Base.Bag',w=.8,md={owner='dead player'},
                            state={condition=17,favorite=true},items={
                                {id=1002,t='Base.Purse',w=.2,items={
                                    {id=1003,t='Base.Watch',w=.15,custom=true,
                                     md={personal={text='keepsake',number=42}},
                                     state={condition=19,name='My watch',favorite=true}}}},
                                {id=1004,t='Base.Bandage',w=.1,md={uses=2}}}})
                        jacket=loadedItem({id=1005,t='Base.Jacket',w=1.2,
                            state={condition=37,blood=.4,wetness=.3,holes={LeftArm=true}}})
                        body.inv:AddItem(bag);body.inv:AddItem(jacket)
                        body.worn={Jacket=jacket};body.held=jacket
                        body.reanimateTime=42;body.ownerName='dead player'
                        rope.state={condition=12,name='Used rope',favorite=true}
                        rope.md={personal='same equipment'};rope.w=.6;rope.custom=true
                        -- The original equipment can live inside the player's bag.
                        playerBag=loadedItem({id=1010,t='Base.Bag',w=.5,items={}})
                        storage:AddItem(playerBag);storage:Remove(rope);playerBag.inv:AddItem(rope)
                    ''')
                    loot = copy_packet(old.eval('savedInventory(body.inv)'))
                    equipment = copy_packet(old.eval('savedItem(rope)'))
                    old.globals().attachPoint = point
                    old.execute('''
                        assert(attach(attachPoint));assertOwned(body.inv);assertOwned(storage)
                        if callbacks.OnSave then callbacks.OnSave() end
                        saved={md=body.md,items=savedInventory(body.inv),car=car.md,equipment=serializeEquipment(),
                            worn=body.worn.Jacket.id,held=body.held.id,
                            reanimateTime=body.reanimateTime,ownerName=body.ownerName}
                    ''')
                    saved = copy_packet(old.globals().saved)

                    fresh = environment(server)
                    fresh.execute(INVENTORY_MODEL)
                    fresh.globals().saved = fresh.table_from(saved, recursive=True)
                    fresh.execute('''
                        setPlayerCorpse(body);body.md=saved.md;body.inv=container()
                        for _,row in ipairs(saved.items) do body.inv:AddItem(loadedItem(row)) end
                        car.md=saved.car
                        body.worn={Jacket=body.inv:getItemWithID(saved.worn)}
                        body.held=body.inv:getItemWithID(saved.held)
                        body.reanimateTime=saved.reanimateTime;body.ownerName=saved.ownerName
                        -- The new fixture's starting gear is not part of this save.
                        storage:Remove(rope);storage:Remove(chain)
                        loadEquipment(saved.equipment)
                        rope=assert(require('CVP_Equipment').get(body.md.CVPTether.equipmentKey,body.md.CVPBodyKey))
                        local inv=body.inv;local bag=inv:getItemWithID(1001)
                        local keepsake=bag.inv:getItemWithID(1002).inv:getItemWithID(1003)
                        local jacket=inv:getItemWithID(1005)
                        for i=1,10 do
                            restore()
                            if callbacks.OnSave then callbacks.OnSave() end
                            assert(#links()==1 and links()[1].body==body and links()[1].gear==rope)
                        end
                        assert(detach())
                        for i=1,5 do restore() end
                        assert(#links()==0 and not body.md.CVPTether and worldCount(body)==1)
                        assert(body.inv==inv and body.worn.Jacket==jacket and body.held==jacket)
                        assert(bag.inv:getItemWithID(1002).inv:getItemWithID(1003)==keepsake)
                        assert(body.reanimateTime==42 and body.ownerName=='dead player')
                        assert(rope.owner==storage and #storage.rows==1)
                        assertOwned(body.inv);assertOwned(storage)
                    ''')
                    self.assertEqual(copy_packet(fresh.eval('savedInventory(body.inv)')), loot)
                    self.assertEqual(copy_packet(fresh.eval('savedItem(rope)')), equipment)

    def test_partial_attach_save_never_reclaims_or_manufactures_equipment(self):
        for server in (False, True):
            for phase in ('item-only', 'metadata-only', 'metadata-item-in-bag'):
                with self.subTest(server=server, phase=phase):
                    lua = environment(server)
                    lua.globals().phase = phase
                    lua.execute(INVENTORY_MODEL)
                    lua.execute('''
                        setPlayerCorpse(body)
                        local Core=require 'CVP_Core';local World=require 'CVP_World'
                        local md=Core.metadata(World.vehicleKey(car),rope,1,'feet',body);md.version=2
                        local loot=body.inv.rows[1];local ropeID=rope.id
                        if phase=='item-only' then storage:Remove(rope);body.inv:AddItem(rope)
                        else body.md.CVPTether=md end
                        local bag
                        if phase=='metadata-item-in-bag' then
                            bag=loadedItem({id=1001,t='Base.Bag',w=.5,items={}})
                            body.inv:AddItem(bag);storage:Remove(rope);bag.inv:AddItem(rope)
                        end
                        local destination=rope.owner
                        for i=1,5 do restore() end
                        assert(#links()==0 and not body.md.CVPTether and worldCount(body)==1)
                        assert(body.inv.rows[1]==loot and loot.owner==body.inv)
                        assert(rope.owner==destination and rope.id==ropeID)
                        assertOwned(body.inv);assertOwned(storage)
                        -- Recovery is ordinary looting followed by a fresh attach.
                        destination:Remove(rope);storage:AddItem(rope)
                        assert(attach() and #links()==1);assert(detach())
                        assert(rope.owner==storage and worldCount(body)==1)
                    ''')

    def test_unloaded_player_tail_keeps_nested_items_when_middle_is_released(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = train(server, 4)
                lua.execute(INVENTORY_MODEL)
                lua.execute('''
                    local Core=require 'CVP_Core'
                    local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                    local inventories={};local loot={}
                    for i,b in ipairs(trainBodies) do
                        setPlayerCorpse(b);inventories[i]=b.inv
                        local bag=loadedItem({id=1000+i,t='Base.Bag',w=.5,items={
                            {id=2000+i,t='Base.Watch',w=.1,md={owner=i}}}})
                        b.inv:AddItem(bag);loot[i]=bag
                    end
                    -- Descendants sleep independently of the selected middle body.
                    for i=4,3,-1 do
                        local r=trainRecords[i];Core.unregister(reg,r)
                        if serverMode then CVPMPServer.byID[r.id]=nil end
                    end
                    if serverMode then assert(CVPMPServer.detach(player,trainBodies[2]))
                    else CVPTest.stop(trainRecords[2],'test') end
                    for i=1,5 do restore() end
                    assert(#links()==1 and links()[1]==trainRecords[1])
                    for i,b in ipairs(trainBodies) do
                        assert(b.inv==inventories[i] and b.inv:getItemWithID(1000+i)==loot[i])
                        assert(loot[i].inv.rows[1].md.owner==i and worldCount(b)==1)
                        assertOwned(b.inv)
                        if i>1 then assert(not b.md.CVPTether) end
                    end
                    assert(trainRecords[2].gear.owner==storage)
                    for i=3,4 do
                        assert(serverMode and trainRecords[i].gear:getWorldItem() or not serverMode and trainRecords[i].gear.owner==storage)
                        assert(not car.md.CVPConnections[trainRecords[i].connection.id])
                    end
                ''')


if __name__ == '__main__':
    unittest.main()
