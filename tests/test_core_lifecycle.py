"""Shared-core behavior through both authoritative adapters, using the Lua fixture.

Hand-written v1 records intentionally do not use the new metadata constructor.
These are normal-load simulations, not native save-file or crash acceptance.
"""
import unittest
from test_multiplayer import vm
from test_stock_visuals import single_player


def environment(server):
    lua = vm(True) if server else single_player()
    lua.globals().serverMode = server
    lua.execute('''
        function attach(point)
            if serverMode then return CVPMPServer.attach(player,body,car,rope,point) end
            CVPTest.attach(player,body,car,rope,point)
            return body.md.CVPTether~=nil
        end
        function links() return serverMode and CVPMPServer.links or CVPTest.links() end
        function detach()
            if serverMode then return CVPMPServer.detach(player,body) end
            CVPTest.stop(links()[1],'test')
            return body.md.CVPTether==nil
        end
        function restore()
            if serverMode then CVPMPServer.discover()
            else CVPTest.discover(body:getSquare());CVPTest.resume() end
        end
        function legacy()
            car.md.CVPVehicleKey='old-vehicle'
            storage:Remove(rope);body.inv:AddItem(rope)
            body.md.CVPTether={version=1,vehicle='old-vehicle',gearID=rope.id,
                gearType='Base.Rope',length=5.55,slot=8,baseline='old-baseline',
                extension='preserve unknown saved fields'}
        end
    ''')
    return lua


class CoreLifecycleTests(unittest.TestCase):
    def test_legacy_records_are_discarded_and_new_attach_still_works(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute("""
                    legacy();restore();restore()
                    assert(#links()==0 and body.md.CVPTether==nil and worldCount(body)==1)
                    body.inv:Remove(rope);storage:AddItem(rope)
                    assert(attach() and #links()==1);assert(detach())
                """)

    def test_dormant_links_wait_and_invalid_connections_leave_items_in_place(self):
        for server in (False, True):
            for case in ('unloaded', 'distance', 'floor', 'missing-item'):
                with self.subTest(server=server, case=case):
                    lua = environment(server)
                    lua.globals().case = case
                    lua.execute('''
                        body.md.CVPTether=require('CVP_Core').metadata(require('CVP_World').vehicleKey(car),rope,1,'feet',body)
                        body.md.CVPTether.version=2
                        storage:Remove(rope);body.inv:AddItem(rope)
                        local saved=body.md.CVPTether
                        local x,y=body.x,body.y;local carSquare=car.getSquare
                        if case=='unloaded' then car.getSquare=function() return nil end
                        elseif case=='distance' then car.x=50
                        elseif case=='floor' then car.z=1
                        else body.inv:Remove(rope);storage:AddItem(rope) end
                        restore();restore()
                        assert(#links()==0 and body.x==x and body.y==y and worldCount(body)==1)
                        if case=='unloaded' then
                            assert(body.md.CVPTether==saved and rope.owner==body.inv)
                            car.getSquare=carSquare;restore();restore()
                            assert(#links()==1 and body.md.CVPTether==saved)
                        else
                            assert(not body.md.CVPTether)
                            assert(case=='missing-item' and rope.owner==storage or case~='missing-item' and (serverMode and rope:getWorldItem() or not serverMode and rope.owner==storage))
                        end
                    ''')

    def test_attach_failures_return_same_item_and_allow_retry(self):
        for server in (False, True):
            for failure in ('refusal', 'exception', 'remove', 'removed-error', 'geometry'):
                with self.subTest(server=server, failure=failure):
                    lua = environment(server)
                    lua.globals().failure = failure
                    lua.execute('''
                        local geometry=require 'CVP_Geometry'
                        local holder=ItemContainer.new();local makeContainer=ItemContainer.new
                        ItemContainer.new=function() return holder end
                        local capture,add,remove=geometry.capture,holder.AddItem,storage.Remove
                        local loot=body.inv.rows[1];local count=#storage.rows
                        if failure=='geometry' then geometry.capture=function() error('fixture geometry failure') end
                        elseif failure=='remove' or failure=='removed-error' then
                            storage.Remove=function(s,item)
                                if failure=='removed-error' then remove(s,item) end
                                error('fixture remove failure')
                            end
                        elseif failure=='exception' then holder.AddItem=function() error('fixture add failure') end
                        else holder.AddItem=function() end end
                        assert(not attach('feet'))
                        assert(#links()==0 and not body.md.CVPTether)
                        assert(rope.owner==storage and #storage.rows==count)
                        assert(#body.inv.rows==1 and body.inv.rows[1]==loot and worldCount(body)==1)
                        if serverMode then
                            assert(#containerPackets==0)
                        end
                        geometry.capture=capture;holder.AddItem=add;storage.Remove=remove;ItemContainer.new=makeContainer
                        assert(attach() and #links()==1 and rope.owner==CVPEquipmentRuntime.container)
                        assert(detach() and rope.owner==storage)
                    ''')

    def test_sp_failed_render_registration_keeps_towing_and_storage(self):
        lua = environment(False)
        lua.execute('''
            CVPViewpoint={track=function() error('fixture track failure') end,untrack=function() end}
            assert(attach())
            assert(#links()==1 and rope.owner==CVPEquipmentRuntime.container and body.md.CVPTether)
            assert(detach())
        ''')

    def test_detach_refusal_preserves_saved_link_until_successful_retry(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    assert(attach());local saved=body.md.CVPTether;local r=links()[1]
                    local add=storage.AddItem;storage.AddItem=function() end
                    assert(not detach())
                    assert(#links()==1 and links()[1]==r and body.md.CVPTether==saved)
                    assert(rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
                    if serverMode then assert(#containerPackets==1) end
                    storage.AddItem=add;assert(detach())
                    assert(#links()==0 and rope.owner==storage and not body.md.CVPTether)
                    if serverMode then assert(#containerPackets==2) end
                ''')

    def test_return_id_conflict_preserves_original_and_retries_in_both_modes(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    assert(attach());local saved=body.md.CVPTether
                    local other=item('Base.Rope');other.id=rope.id;storage:AddItem(other)
                    local ok=detach()
                    assert(rope.owner==CVPEquipmentRuntime.container and other.owner==storage)
                    assert(not ok and #links()==1 and body.md.CVPTether==saved)
                    storage:Remove(other);assert(detach() and rope.owner==storage)
                ''')

    def test_length_uses_attachment_distance_not_slot(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    local expected=math.sqrt(1.53^2+.675^2)
                    for i=1,8 do
                        if i>1 then
                            body=corpse();body.netID=tostring(100+i)
                            rope=item('Base.Rope');storage:AddItem(rope)
                        end
                        assert(attach());local md=body.md.CVPTether
                        assert(md.version==3 and md.equipmentKey and md.slot==i and math.abs(md.length-expected)<1e-10)
                        assert(md.gearID==rope.id and md.gearType=='Base.Rope')
                        assert(md.connection.a.key==car.md.CVPVehicleKey)
                        assert((serverMode and md.owner=='owner' and md.baseline==nil)
                            or (not serverMode and md.owner==nil and type(md.baseline)=='string'))
                    end
                ''')


if __name__ == '__main__':
    unittest.main()
