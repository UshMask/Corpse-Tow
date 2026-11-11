"""Shared indexes, alpha reset policy and server snapshot work bounds."""
import unittest
from test_core_lifecycle import environment


class RegistryTests(unittest.TestCase):
    def test_registration_release_unload_and_replacement(self):
        for server in (False, True):
            lua = environment(server)
            lua.execute("""
                local Core=require 'CVP_Core'
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                assert(attach());local old=links()[1];local id=old.connection.id
                assert(reg.byConnection[id]==old and reg.byBody[body]==old)
                assert(#reg.byVehicle[car]==1)
                assert(detach())
                assert(not reg.byConnection[id] and not reg.byBody[body] and not reg.byVehicle[car])
                assert(attach());local current=links()[1]
                Core.unregister(reg,old)
                assert(#links()==1 and reg.byBody[body]==current)
                Core.unregister(reg,current)
                if serverMode then CVPMPServer.byID={} end
                restore()
                assert(#links()==1 and reg.byBody[body]==links()[1])
                assert(reg.byConnection[current.connection.id]==links()[1])
                local count=#links()
                assert(not pcall(Core.register,reg,links()[1]))
                assert(#links()==count and #reg.byVehicle[car]==count)
            """)

    def test_bad_saved_records_do_not_block_valid_bodies(self):
        for server in (False, True):
            for invalid in ("false", "42", "'bad'", "{version=1}",
                            "{version=2,connection={}}"):
                lua = environment(server)
                lua.execute("""
                    local Core=require 'CVP_Core';local World=require 'CVP_World'
                    local md=Core.metadata(World.vehicleKey(car),chain,1,'neck',body2);md.version=2
                    storage:Remove(chain);body2.inv:AddItem(chain);body2.md.CVPTether=md
                    body.md.CVPTether=""" + invalid + """
                    restore()
                    assert(not body.md.CVPTether and #links()==1)
                    assert(links()[1].body==body2 and links()[1].point=='neck')
                """)

    def test_snapshot_built_once_per_connection_not_per_player(self):
        for count in (0, 8, 64):
            lua = environment(True)
            lua.globals().count = count
            lua.execute("""
                local Core=require 'CVP_Core';local World=require 'CVP_World'
                local Connection=require 'CVP_Connection'
                -- Populate restored state across eight cars, eight links per car.
                local cars={}
                for i=1,8 do
                    local v={};for k,value in pairs(car) do v[k]=value end
                    v.md={CVPVehicleKey='car-'..i};cars[i]=v
                end
                for i=1,count do
                    local b=corpse();b.netID=tostring(1000+i)
                    b.getSquare=body.getSquare;b.setSquare=body.setSquare
                    b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex
                    sq:addCorpse(b)
                    local gear=item('Base.Rope');b.inv:AddItem(gear)
                    local v=cars[math.floor((i-1)/8)+1]
                    local md=Core.metadata(World.vehicleKey(v),gear,(i-1)%8+1,'feet',b);md.version=2
                    b.md.CVPTether=md
                    local r=Core.link(b,v,gear,md);r.id=b.netID
                    Core.register(CVPMPServer.registry,r);CVPMPServer.byID[r.id]=r
                end
                -- Count descriptor construction in the real server publish path.
                local copy=Connection.copy;local copies=0
                Connection.copy=function(c) copies=copies+1;return copy(c) end
                players={player,player2,player,player2}
                now=100;CVPMPServer.tick()
                assert(copies==count and #packets==4)
                for _,p in ipairs(packets) do assert(#p.args.rows==count) end
                assert(#CVPMPServer.links==count)
                for _,r in ipairs(CVPMPServer.links) do assert(not r.failed) end
                -- Filtering is still per recipient, even with shared state rows.
                packets={};player2.x=1000;now=200;CVPMPServer.tick()
                assert(#packets[1].args.rows==count and #packets[2].args.rows==0)
                assert(copies==count*2)
            """)

    def test_duplicate_saved_identity_does_not_abort_discovery(self):
        for server in (False, True):
            lua=environment(server)
            lua.execute("""
                local Core=require 'CVP_Core';local World=require 'CVP_World'
                assert(attach());local original=links()[1]
                local md=Core.metadata(World.vehicleKey(car),chain,2,'feet',body2);md.version=2
                md.connection.id=original.connection.id
                storage:Remove(chain);body2.inv:AddItem(chain);body2.md.CVPTether=md
                restore()
                assert(#links()==1 and links()[1]==original and body2.md.CVPTether==md)
                assert(md.equipmentKey and World.gear(body2,md)==chain and chain.owner==CVPEquipmentRuntime.container)
                local reg=serverMode and CVPMPServer.registry or CVPRuntime.registry
                assert(reg.byConnection[original.connection.id]==original)
                assert(reg.byBody[body]==original and not reg.byBody[body2])
                assert(Core.release(body2,chain,storage) and chain.owner==storage)
                assert(detach())
            """)


if __name__ == '__main__':
    unittest.main()
