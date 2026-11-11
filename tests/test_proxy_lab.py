"""Independent SP scenarios against a fresh modeled engine per test."""
import unittest
from lupa.lua51 import LuaRuntime
from legacy_fixture import create_legacy_fixture


class ProxyLabTests(unittest.TestCase):
    def setUp(self):
        env = create_legacy_fixture()
        self.lua = env["L"]
        self.source = env["source"]
        self.lua.execute(self.source)

    def test_menu_tows_and_returns_originals(self):
        self.lua.execute(r'''
menu();click('(верёвка)');assert(body.world and worldCount(body)==1 and #CVPTest.links()==1)
assert(rope.owner==CVPEquipmentRuntime.container and not body.carrier.owner and body.md.CVPTether)
menu(body2);click('(цепь)');assert(#CVPTest.links()==2 and worldCount(body2)==1)
assert(CVPTest.links()[1].length==CVPTest.links()[2].length)
for i=1,20 do car.x=3+i*0.2;tick();assert(worldCount(body)==1 and worldCount(body2)==1) end
assert(body.x>0 and body2.x>0 and #impulses>0)
local itemCount=#storage.rows;callbacks.OnSave()
assert(#CVPTest.links()==2 and body.md.CVPTether and #storage.rows==itemCount,'save must not detach or create carriers')
callbacks.RenderOpaqueObjectsInWorld(0);assert(not body.renders,'no duplicate manual render for world body')
SandboxVars.CorpseProxyLab.VehicleDrag=false;local n=#impulses;tick();assert(#impulses==n)
SandboxVars.CorpseProxyLab.VehicleDrag=true
releaseAll();assert(rope.owner==storage and chain.owner==storage and #body.inv.rows==1 and not body.md.CVPTether)
assert(worldCount(body)==1 and worldCount(body2)==1)
print('PASS persistent world ownership, no carrier, per-tile registration, multi-body movement/load, save retains links, detach returns originals')
        ''')

    def test_repeated_load_restores_once(self):
        self.lua.execute(r'''
-- Reload reconstruction: discard runtime object references; retain serialized world data.
resetPositions();menu();click('(верёвка)');local old=CVPTest.links()[1]
savedMD=body.md.CVPTether;savedVehicleKey=car.md.CVPVehicleKey
for i=#CVPRuntime.links,1,-1 do require('CVP_Core').unregister(CVPRuntime.registry,CVPRuntime.links[i]) end
CVPRuntime.pending={};callbacks.OnGameStart()
assert(#CVPTest.links()==1 and CVPTest.links()[1]~=old and CVPTest.links()[1].body==body)
assert(CVPTest.links()[1].length==savedMD.length and car.md.CVPVehicleKey==savedVehicleKey)
for i=1,5 do callbacks.LoadGridsquare(body.sq);CVPTest.resume();callbacks.OnSave() end
assert(#CVPTest.links()==1 and worldCount(body)==1 and rope.owner==CVPEquipmentRuntime.container,'idempotent restoration')
releaseAll();assert(rope.owner==storage)
print('PASS save metadata reconstruction and repeated load events create no duplicate links/bodies/items')
        ''')

    def test_missing_vehicle_defers_release(self):
        self.lua.execute(r'''
-- Vehicle missing: preserve dormant body/rope until saved tail membership is available.
resetPositions();menu();click('(верёвка)');require('CVP_Core').unregister(CVPRuntime.registry,CVPRuntime.links[1])
savedVehicleKey=car.md.CVPVehicleKey;car.md.CVPVehicleKey=nil;CVPTest.discover(body.sq);CVPTest.resume()
assert(#CVPTest.links()==0 and body.md.CVPTether and rope.owner==CVPEquipmentRuntime.container)
menu();click(getText('IGUI_CVP_Detach'));assert(body.md.CVPTether and rope.owner==CVPEquipmentRuntime.container)
assert(messages[#messages]==getText('IGUI_CVP_VehicleUnavailable'))
car.md.CVPVehicleKey=savedVehicleKey;CVPTest.resume();assert(#CVPTest.links()==1)
releaseAll();assert(not body.md.CVPTether and rope.owner==storage)
        ''')

    def test_distance_and_chunk_sleep_resume(self):
        self.lua.execute(r'''
-- Unloaded/far-away links sleep instead of being destroyed or reconstructed.
menu();click('(верёвка)');player.x=40;tick()
assert(#CVPTest.links()==0 and body.md.CVPTether and body.world)
player.x=0;CVPTest.resume();assert(#CVPTest.links()==1)
unloaded=true;tick();assert(#CVPTest.links()==0 and body.md.CVPTether)
unloaded=false;callbacks.LoadGridsquare(body.sq);CVPTest.resume();assert(#CVPTest.links()==1)
releaseAll()
        ''')

    def test_square_transfer_preserves_pose_and_rolls_back(self):
        self.lua.execute(r'''
-- Native square transition fails: same original stays in old square, no copy.
resetPositions();local target=gridSquare(1,0,0);addFail=target
local pose={};body.pose=pose
local ok=pcall(CVPTest.world.move,body,1.5,0,0,target);addFail=nil
assert(not ok and worldCount(body)==1 and body.sq==sq and body.x==0)
assert(body.pose==pose and not pose.released,'failed transfer released the death pose')
for i=1,5 do
 CVPTest.world.move(body,1.5,0,0,target)
 assert(body.pose==pose and not pose.released and worldCount(body)==1)
 CVPTest.world.move(body,0,0,0,sq)
 assert(body.pose==pose and not pose.released and worldCount(body)==1)
end
removeFail=true;assert(not pcall(CVPTest.world.move,body,1.5,0,0,target));removeFail=nil
assert(body.pose==pose and not pose.released and body.sq==sq)
print('PASS death pose retained across repeated tile transfers and removal/addition failures')
print('PASS missing vehicle defers release, distance/chunk sleep/resume, failed square transition rollback')
        ''')

    def test_external_removal_and_return_conflict(self):
        self.lua.execute(r'''
-- Never recreate externally removed bodies, or a stolen rope.
menu();click('(верёвка)');body.sq:removeCorpse(body);tick()
assert(#CVPTest.links()==0 and not body.world and not body.md.CVPTether and rope.owner==storage)
sq:addCorpse(body)
menu();click('(верёвка)');rope:getContainer():Remove(rope);other=container();other:AddItem(rope);tick()
assert(#CVPTest.links()==1 and body.md.CVPTether and rope.owner==other and worldCount(body)==1)
other:Remove(rope);CVPEquipmentRuntime.container:AddItem(rope);releaseAll();assert(rope.owner==storage)
-- A same-ID inventory conflict keeps the original independently held for retry.
menu();click('(верёвка)');local blocker=item('Base.Hammer');blocker.id=rope.id;storage:AddItem(blocker)
releaseAll();assert(rope.owner==CVPEquipmentRuntime.container and blocker.owner==storage and worldCount(body)==1)
storage:Remove(blocker);releaseAll();assert(rope.owner==storage and not body.md.CVPTether)
-- Pre-existing recovery item is preserved and never used to spawn a body.
local legacy=item('Base.CorpseMale',0);legacy.md.CVPRecovery={weight=20};storage:AddItem(legacy)
local before=#bodies;callbacks.OnGameStart();assert(#bodies==before and legacy.w==20 and legacy.owner==storage)
menu();click('(верёвка)');releaseAll();assert(legacy.owner==storage and not body.carrier.owner)
storage:Remove(legacy)
print('PASS no recreation on external removal, stolen gear, return-ID collision and legacy preservation')
        ''')

    def test_timed_action_cancel_and_revalidation(self):
        self.lua.execute(r'''
resetPositions();deferAction=true
menu();click('(верёвка)');local a=queued
assert(not body.md.CVPTether and rope.owner==storage)
a:start();assert(a.anim=='Loot' and a.LootPosition=='Low' and a.stopOnWalk and a.stopOnRun)
a:stop();assert(not a:complete() and not body.md.CVPTether)
for mode=1,4 do
 menu();click('(верёвка)');a=queued
 if mode==1 then speed=2 elseif mode==2 then unreachable=true elseif mode==3 then storage:Remove(rope) else player.x=10 end
 assert(not a:complete());speed=0;unreachable=false;player.x=0
 if not rope.owner then storage:AddItem(rope) end
end
menu();click('(верёвка)');a=queued;assert(a:complete() and not a:complete());releaseAll()
deferAction=false
print('PASS timed animation/cancel/revalidation and exactly-once completion')
        ''')

    def test_obstruction_save_and_resume(self):
        self.lua.execute(r'''
resetPositions();menu();click('(верёвка)')
local r=CVPTest.links()[1];local baseline=CVPTest.snapshot(body.inv)
blocked=true;car.x=8;speed=150
for i=1,10 do tick() end
assert(#CVPTest.links()==1 and r.blocked and r.tensionRatio>1 and body.x==0 and body.y==0)
assert(worldCount(body)==1 and rope.owner==CVPEquipmentRuntime.container and CVPTest.snapshot(body.inv)==baseline)
callbacks.OnSave();assert(body.md.CVPTether and #CVPTest.links()==1,'blocked tether must survive save')
blocked=false;tick();assert(body.x>0 and #CVPTest.links()==1,'resume as soon as obstruction clears')
car.x=40;tick()
assert(#CVPTest.links()==0 and rope.owner==storage and worldCount(body)==1,'distance release after obstruction')
speed=0;resetPositions()
print('PASS obstruction keeps original body/items/tether, save retains it, clear resumes, speed alone does not release, distance does')
        ''')

    def test_player_corpse_preserves_inventory(self):
        self.lua.execute(r'''

resetPositions()
body.isZombie=function() return false end
local inventory=body.inv;local original={}
for i,v in ipairs(inventory.rows) do original[i]=v end
body.reanimateTime=73
menu(body);click('(верёвка)')
assert(#CVPTest.links()==1 and rope.owner==CVPEquipmentRuntime.container)
car.x=5;tick();releaseAll()
assert(body.inv==inventory and #inventory.rows==#original and body.reanimateTime==73)
for i,v in ipairs(original) do assert(inventory.rows[i]==v) end
assert(rope.owner==storage and worldCount(body)==1)
print('PASS non-zombie human corpse SP attach/tow/detach preserves original inventory and reanimation data')
        ''')

    def test_settings_and_vehicle_bulk_detach(self):
        self.lua.execute(r'''
body.isZombie=function() return false end

resetPositions()
SandboxVars.CorpseProxyLab.AllowPlayerCorpses=false
assert(CVPTest.reason(player,body,car,rope)==getText('IGUI_CVP_PlayerBodiesDisabled'))
SandboxVars.CorpseProxyLab.AllowPlayerCorpses=true
SandboxVars.CorpseProxyLab.MaxBodiesPerChain=1
menu(body);click('(верёвка)')
assert(CVPTest.reason(player,body2,car,chain)==nil)
SandboxVars.CorpseProxyLab.MaxBodiesPerChain=8
menu(body2);click('(цепь)');assert(#CVPTest.links()==2)
speed=5;carMenu()
local label=getText('IGUI_CVP_DetachAllMenu','2')
local found=false
for _,o in ipairs(options) do if o.label:find(label,1,true) then
 found=true;assert(o.notAvailable);o.run();assert(#CVPTest.links()==2)
end end
assert(found)
speed=0;carMenu();click(label)
assert(#CVPTest.links()==0 and rope.owner==storage and chain.owner==storage)
print('PASS SP settings and vehicle-scoped bulk detach with movement revalidation')
        ''')

    def test_single_player_guard(self):
        for mode in ('client','server'):
         M=LuaRuntime()
         M.globals().mode=mode
         M.execute("function isClient() return mode=='client' end;function isServer() return mode=='server' end")
         M.execute(self.source)
        print('NOT VERIFIED HERE: native save bytes, live visuals or engine crash ordering; SP-only guard passed.')



if __name__ == '__main__':
    unittest.main()
