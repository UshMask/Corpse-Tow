"""Independent SP scenarios against a fresh modeled engine per test."""
import unittest
from lupa.lua51 import LuaRuntime
from legacy_fixture import create_legacy_fixture


class ProxyLifecycleTests(unittest.TestCase):
    def setUp(self):
        env = create_legacy_fixture()
        self.lua = env["L"]
        self.source = env["source"]
        self.lua.execute(self.source)

    def test_death_during_unload_returns_original(self):
        self.lua.execute(r'''
-- Death and a vehicle unload in the same frame must not bypass release.
resetPositions();menu();click('(верёвка)')
local alive=player.isDead;local carSquare=car.getSquare
player.isDead=function() return true end;car.getSquare=function() return nil end
tick()
assert(#CVPTest.links()==0 and not body.md.CVPTether,'death must release even if car is unloaded')
assert(rope:getWorldItem() and worldCount(body)==1,'death must return the same original rope to ground')
player.isDead=alive;car.getSquare=carSquare
takeGround(rope,storage)
print('PASS owner death simultaneous with vehicle unload')
        ''')

    def test_dead_player_does_not_resume(self):
        self.lua.execute(r'''
local alive=player.isDead
-- A dead player must not be assigned dormant tethers on a discovery tick.
menu();click('(верёвка)');player.x=40;tick();player.x=0
player.isDead=function() return true end
CVPTest.resume()
assert(#CVPTest.links()==0 and body.md.CVPTether,'dead player must not resume dormant links')
assert(rope.owner==CVPEquipmentRuntime.container)
player.isDead=alive;CVPTest.resume();assert(#CVPTest.links()==1);releaseAll()
print('PASS dormant discovery waits for a living player')
        ''')

    def test_moved_vehicle_does_not_teleport_body(self):
        self.lua.execute(r'''
-- A reloaded vehicle that moved away must not teleport the dormant body.
for _,mode in ipairs({'distance','floor'}) do
 resetPositions();menu();click('(верёвка)');player.x=40;tick();player.x=0
 local x,y=body.x,body.y
 if mode=='distance' then car.x=50 else car.z=1 end
 CVPTest.resume()
 assert(#CVPTest.links()==0 and not body.md.CVPTether)
 assert(body.x==x and body.y==y and worldCount(body)==1 and rope.owner==storage)
 car.z=0
end
print('PASS moved vehicle and floor mismatch leave dormant body/items intact')
        ''')

    def test_refused_return_is_retryable(self):
        self.lua.execute(r'''
-- A refused return must be retryable, without losing or duplicating the rope.
resetPositions();menu();click('(верёвка)')
local add=storage.AddItem;storage.AddItem=function() return nil end
releaseAll()
assert(#CVPTest.links()==1 and CVPTest.links()[1].failed and body.md.CVPTether)
assert(rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
storage.AddItem=add;releaseAll()
assert(#CVPTest.links()==0 and rope.owner==storage and not body.md.CVPTether)
print('PASS refused inventory return retains original and supports retry')
        ''')

    def test_fresh_objects_restore_exactly_once(self):
        self.lua.execute(r'''
-- Real unload/reload replaces Java object instances. Simulate that with fresh
-- body/container/item objects and metadata containing only serialized values.
local function copy(t)
 if type(t)~='table' then return t end
 local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end
resetPositions();menu();click('(верёвка)');menu(body2);click('(цепь)')
local originals={body,body2};local saved={};local vehicleKey=car.md.CVPVehicleKey
for _,b in ipairs(originals) do
 local row={md=copy(b.md),x=b.x,y=b.y,z=b.z,items={},fingerprint=CVPTest.snapshot(b.inv)}
 for _,v in ipairs(b.inv.rows) do row.items[#row.items+1]={id=v.id,t=v.t,w=v.w} end
 saved[#saved+1]=row
end
callbacks.OnSave()
for i=#CVPRuntime.links,1,-1 do require('CVP_Core').unregister(CVPRuntime.registry,CVPRuntime.links[i]) end
CVPRuntime.pending={}
for _,b in ipairs(originals) do b.sq:removeCorpse(b) end
local restored={}
for _,row in ipairs(saved) do
 local b=corpse();b.world=false;b.x=row.x;b.y=row.y;b.z=row.z;b.md=copy(row.md);b.inv=container()
 b.getSquare=function(s) return s.sq end;b.setSquare=function(s,q) s.sq=q end
 b.getStaticMovingObjectIndex=function(s) return s.world and s.sq and list(s.sq.rows):contains(s) and 0 or -1 end
 for _,v in ipairs(row.items) do local a=item(v.t,v.w);a.id=v.id;b.inv:AddItem(a) end
 local q=gridSquare(math.floor(b.x),math.floor(b.y),b.z);q:addCorpse(b);restored[#restored+1]=b
 callbacks.LoadGridsquare(q)
end
-- A fresh vehicle instance with the saved persistent key.
local oldCar=car;local newCar={};for k,v in pairs(oldCar) do newCar[k]=v end
newCar.md={CVPVehicleKey=vehicleKey};car=newCar
callbacks.OnGameStart()
for n=1,5 do for _,b in ipairs(restored) do callbacks.LoadGridsquare(b.sq) end;CVPTest.resume();callbacks.OnSave() end
assert(#CVPTest.links()==2,'two saved links must restore exactly once')
local slots={}
for _,r in ipairs(CVPTest.links()) do
 assert(r.vehicle==newCar and r.vehicle~=oldCar)
 assert(r.body~=originals[1] and r.body~=originals[2])
 assert(r.gear==rope or r.gear==chain,'body chunk reload must preserve independently held instances')
 assert(not slots[r.slot]);slots[r.slot]=true
end
for i,b in ipairs(restored) do
 assert(worldCount(b)==1 and CVPTest.snapshot(b.inv)==saved[i].fingerprint)
end
releaseAll()
for _,b in ipairs(restored) do assert(worldCount(b)==1 and not b.md.CVPTether and #b.inv.rows==1) end
print('PASS two-body save/load with fresh objects, original IDs, slots and exact-once restore/release')
        ''')


if __name__ == '__main__':
    unittest.main()
