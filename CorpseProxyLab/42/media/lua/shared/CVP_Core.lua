-- Current graph runtime: movement, item transfer and legacy vehicle observation.
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Rope=require 'CVP_Rope'
local Obstacles=require 'CVP_LinkObstacles'
local Core={}
function Core.connection(r)
    return r.connection
end

function Core.transfer(item,source,destination)
    if item:getContainer()~=source or not source:getItems():contains(item) then return false,'IGUI_CVP_ItemConflict' end
    if destination:getItemWithID(item:getID()) then return false,'IGUI_CVP_ItemConflict' end
    local ok,err=pcall(function()
        source:Remove(item)
        -- Another mod may refuse removal or move the item elsewhere.
        assert(not source:getItems():contains(item) and not item:getContainer(),'source did not release tether')
        destination:AddItem(item)
        assert(destination:getItems():contains(item),'inventory rejected tether')
    end)
    if not ok then
        if destination:getItems():contains(item) then destination:Remove(item) end
        if not item:getContainer() then source:AddItem(item) end
        return false,tostring(err)
    end
    return true
end

local vehicleRevisions=setmetatable({},{__mode='k'})
function Core.observeVehicle(v)
    local md=v:getModData();local key=md.CVPVehicleKey
    if not key then return true end
    local members,err,revision=require('CVP_Equipment').members(key,md.CVPConnections)
    if not members then return false,err end
    local seen=vehicleRevisions[v]
    if seen and seen.revision==revision and seen.members==md.CVPConnections then return true end
    local same=type(md.CVPConnections)=='table'
    if same then
        for id,parent in pairs(members) do if md.CVPConnections[id]~=parent then same=false;break end end
        if same then for id,parent in pairs(md.CVPConnections) do if members[id]~=parent then same=false;break end end end
    end
    if not same then
        local restored={};for id,parent in pairs(members) do restored[id]=parent end
        md.CVPConnections=restored
    end
    vehicleRevisions[v]={revision=revision,members=md.CVPConnections}
    return true
end

function Core.advance(r,ax,ay,az,dt,pathCache,deferred)
    local b=Core.connection(r).b.object
    if not r.footprint then Geometry.capture(r) end
    local oldAngle=r.angle
    local x,y,taut=Rope.step(r,r.x,r.y,ax,ay,dt,az)
    x,y,r.angle,r.blocked=Geometry.resolve(r,x,y,r.angle,oldAngle,pathCache)
    r.ropeBlocked=nil
    if pathCache then
        local bx,by=Rope.feet(r,x,y)
        r.ropeBlocked=Obstacles.check(pathCache,{x=ax,y=ay,z=az},{x=bx,y=by,z=r.z},(r.length or 4)+6)
        if r.ropeBlocked then x=r.x;y=r.y;r.angle=oldAngle;r.blocked=true;taut=false end
    end
    if r.blocked then r.vx=0;r.vy=0 end
    local sq
    if not deferred then
        sq=getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(r.z))
        r.movePending={square=b:getSquare(),x=r.x,y=r.y,z=r.z}
        World.move(b,x,y,r.z,sq)
        r.movePending=nil
    end
    r.x=x;r.y=y;r.taut=taut
    return sq
end
return Core
