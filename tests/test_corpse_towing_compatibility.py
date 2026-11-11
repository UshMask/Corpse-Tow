"""Foreign ownership markers match the inspected Corpse Towing 42.20 source.

These test our adapters with those markers, not a live pair of game mods.
"""
import unittest
from pathlib import Path
from lupa.lua51 import LuaRuntime
from test_core_lifecycle import environment
from test_multiplayer import vm
from test_trains import train


class CorpseTowingCompatibilityTests(unittest.TestCase):
    def test_foreign_attachment_rejected_but_loose_rope_allowed(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    body.md.CorpseTowingVehicleToken='other-car'
                    body.md.CorpseTowingRopeAttached=true
                    body.md.CorpseTowingSlot=2
                    assert(not attach() and #links()==0)
                    assert(not body.md.CVPTether and rope.owner==storage)
                    assert(body.md.CorpseTowingVehicleToken=='other-car' and body.md.CorpseTowingSlot==2)
                    for _,candidate in ipairs(require('CVP_Batch').candidates(player,car)) do
                        assert(candidate~=body,'batch selected a foreign-owned body')
                    end
                    body.md.CorpseTowingVehicleToken=nil
                    assert(attach() and detach(),'loose CT rope must not reserve a body')
                    assert(body.md.CorpseTowingRopeAttached==true)
                ''')

    def test_foreign_claim_releases_our_link_and_returns_original_without_moving_body(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    assert(attach());local x,y=body.x,body.y;local loot=body.inv.rows[1]
                    body.md.CorpseTowingVehicleToken='other-car';car.x=3
                    now=now+100
                    if serverMode then CVPMPServer.tick() else callbacks.OnTick() end
                    assert(#links()==0 and not body.md.CVPTether)
                    assert(body.x==x and body.y==y and body.inv.rows[1]==loot)
                    assert((serverMode and rope:getWorldItem() or not serverMode and rope.owner==storage) and worldCount(body)==1)
                    assert(body.md.CorpseTowingVehicleToken=='other-car')
                    assert(not next(car.md.CVPConnections))
                ''')

    def test_saved_conflict_is_not_restored_even_without_loaded_vehicle(self):
        for server in (False, True):
            for unloaded in (False, True):
                with self.subTest(server=server, unloaded=unloaded):
                    lua = environment(server)
                    lua.globals().unloadedCar = unloaded
                    lua.execute('''
                        local Core=require 'CVP_Core';local World=require 'CVP_World'
                        local md=Core.metadata(World.vehicleKey(car),rope,1,'feet',body);md.version=2
                        body.md.CVPTether=md;car.md.CVPConnections={[md.connection.id]=true}
                        storage:Remove(rope);body.inv:AddItem(rope)
                        body.md.CorpseTowingVehicleToken='other-car'
                        local square=car.getSquare
                        if unloadedCar then car.getSquare=function() return nil end end
                        restore();restore()
                        if unloadedCar then
                            assert(#links()==0 and body.md.CVPTether==md)
                            car.getSquare=square;restore();restore()
                        end
                        assert(#links()==0 and not body.md.CVPTether)
                        assert(not next(car.md.CVPConnections))
                        assert((serverMode and rope:getWorldItem() or not serverMode and rope.owner==storage) and worldCount(body)==1)
                        assert(body.md.CorpseTowingVehicleToken=='other-car')
                    ''')

    def test_foreign_chain_claim_blocks_substeps_and_releases_only_its_tail(self):
        for server in (False, True):
            for claimed in (1, 2):
                with self.subTest(server=server, claimed=claimed):
                    lua = train(server, 3)
                    lua.globals().claimed = claimed
                    lua.execute('''
                        local Core=require 'CVP_Core';local b=trainBodies[claimed]
                        b.md.CorpseTowingVehicleToken='other-car'
                        assert(not Core.canFollow(trainRecords[claimed]))
                        local poses={}
                        for i,row in ipairs(trainBodies) do poses[i]={row.x,row.y} end
                        car.x=3;stepTrain(.1)
                        for i,row in ipairs(trainBodies) do
                            assert(row.x==poses[i][1] and row.y==poses[i][2],'conflicted chain advanced')
                        end
                        stepTrain(.1)
                        assert(#links()==claimed-1)
                        assert(not b.md.CVPTether and b.md.CorpseTowingVehicleToken=='other-car')
                        assert(serverMode and trainRecords[claimed].gear:getWorldItem() or not serverMode and trainRecords[claimed].gear.owner==storage)
                        assert(not trainBodies[3].md.CVPTether and worldCount(b)==1)
                    ''')

    def test_observer_ignores_stale_pose_for_foreign_claimed_body(self):
        lua = vm(False)
        lua.execute('''
            local md=require('CVP_Core').metadata(require('CVP_World').vehicleKey(car),rope,1,'feet',body)
            body.md.CorpseTowingVehicleToken='other-car'
            CVPMPClient.links[body.netID]={received=now,target={
                x=2,y=0,z=0,angle=0,vehicle=7,slot=1,length=3,
                footX=-.65,footY=0,gearType='Base.Rope',gearID=rope.id,
                taut=true,mass=75,connection=md.connection}}
            local x,y=body.x,body.y;physicsOwner=true
            now=now+100;CVPMPClient.tick()
            assert(body.x==x and body.y==y and not body.md.CVPTether)
            assert(#impulses==0 and body.md.CorpseTowingVehicleToken=='other-car')
        ''')


class TemporaryVectorTests(unittest.TestCase):
    def test_vectors_reused_across_vehicles_without_stale_coordinates(self):
        lua = LuaRuntime()
        lua.execute('''
            allocations=0;forces={}
            CVPWorldNative={applyVehicleResistance=function(v,amount)
                forces[#forces+1]={v,amount}
            end}
            Vector3f={new=function()
                allocations=allocations+1
                return {x=function(s) return s.xx end,y=function(s) return s.yy end,z=function(s) return s.zz end}
            end}
            function isClient() return false end;function isServer() return false end
            function vehicle(x,y,vx,vz)
                return {getX=function() return x end,getY=function() return y end,getZ=function() return 0 end,
                    getLinearVelocity=function(_,out) out.xx=vx;out.yy=0;out.zz=vz;return out end,
                    getWorldPos=function(_,a,b,c,out) out.xx=x;out.yy=y;out.zz=0;return out end,
                    getScript=function() return {getExtents=function() return {z=function() return 4 end} end} end,
                    getMass=function() return 1200 end,isDoingOffroad=function() return false end,
                    applyImpulseGeneric=function(_,px,py,pz,dx,dy,dz,amount)
                        forces[#forces+1]={px,py,dx,dy,amount}
                    end}
            end
            a=vehicle(10,20,3,4);b=vehicle(-7,8,-4,3)
        ''')
        lua.globals().Load = lua.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Load.lua').read_text())
        lua.execute("package.path=.....'/?.lua;'..package.path", Path('CorpseProxyLab/42/media/lua/shared').as_posix())
        lua.globals().Geometry = lua.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Geometry.lua').read_text())
        lua.execute('''
            for i=1,20 do
                Load.apply(a,75,.1);local ax,ay=Geometry.anchor(a)
                Load.apply(b,75,.1);local bx,by=Geometry.anchor(b)
                assert(ax==10 and ay==20 and bx==-7 and by==8)
                local fa,fb=forces[#forces-1],forces[#forces]
                assert(fa[1]==a and fb[1]==b,'resistance went to the wrong vehicle')
                assert(fa[2]==fb[2] and fa[2]>0)
            end
            assert(allocations==2,'one scratch vector per hot-path module expected')
        ''')


if __name__ == '__main__':
    unittest.main()
