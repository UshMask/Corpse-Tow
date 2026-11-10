-- The world corpse is the only persisted body. Never serialize a second carrier.
local Connection=require 'CVP_Connection'
local Plow=require 'CVP_Plow'
local World={}
local observing=false
function World.foreignTowed(b)
    return b:getModData().CorpseTowingVehicleToken~=nil or Plow.busy(b)
end
function World.towable(b)
    return b and instanceof(b,'IsoDeadBody') and not b:isFakeDead()
end
function World.towingEnabled()
    return not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.Enabled~=false
end
function World.maxChain()
    local value=tonumber(SandboxVars.CorpseProxyLab and SandboxVars.CorpseProxyLab.MaxBodiesPerChain) or 32
    if value==0 then return math.huge end
    return math.max(1,math.floor(value))
end
function World.playerBodiesAllowed()
    return not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.AllowPlayerCorpses~=false
end
function World.canDetach(p,md)
    return not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.AllowDetachOthers~=false
        or not md.owner or md.owner==p:getUsername()
end
-- Old alpha records can be discarded; independently held equipment must retain
-- its recovery address even when its connection metadata is not usable.
function World.data(b)
    if not observing and (not isClient() or isServer()) then
        observing=true
        local ok=pcall(function() require('CVP_Equipment').observeBody(b) end)
        observing=false
        if not ok then return nil end
    end
    local data=b:getModData();local md=data.CVPTether
    if md~=nil and (not World.valid(md) or not Connection.bodyMatches(b,md.connection)) then
        if type(md)~='table' or not md.equipmentKey then data.CVPTether=nil end
        return nil
    end
    return md
end
function World.vehicleKey(v)
    local md=v:getModData()
    if not md.CVPVehicleKey then
        md.CVPConnections=nil
        md.CVPVehicleKey=tostring(getTimestampMs())..'-'..ZombRand(1000000000)..'-'..ZombRand(1000000000)
    end
    return md.CVPVehicleKey
end
function World.gear(b,md)
    if not md then return nil end
    if md.version==3 then
        if isClient() and not isServer() then return nil end
        if not md.connection or not md.connection.b then return nil end
        local item=require('CVP_Equipment').get(md.equipmentKey,md.connection.b.key)
        if item and item:getID()==md.gearID and item:getFullType()==md.gearType then return item end
        return nil
    end
    if md.version~=2 then return nil end
    local item=b:getContainer():getItemWithID(md.gearID)
    if item and item:getFullType()==md.gearType then return item end
end
function World.valid(md)
    return type(md)=='table' and (md.version==2 or md.version==3
            and type(md.equipmentKey)=='string' and #md.equipmentKey>0 and #md.equipmentKey<=256)
        and type(md.gearID)=='number' and type(md.gearType)=='string'
        and type(md.length)=='number' and md.length>=0.1 and md.length<=12
        and type(md.slot)=='number' and md.slot>=1 and md.slot==math.floor(md.slot)
        and Connection.valid(md.connection)
        and (md.connection.a.kind=='vehicle' or
            (type(md.parentConnection)=='string' and type(md.rootVehicle)=='string'))
end
function World.angle(b,angle)
    if CVPWorldNative and CVPWorldNative.setAngle then CVPWorldNative.setAngle(b,angle)
    elseif b:getAngle()~=angle then b:setForwardDirectionAngle(angle);b:invalidateCorpse() end
end
function World.present(b,readPass)
    if readPass then return CVPWorldNative.contains(readPass,b) end
    return b:getSquare()~=nil and b:getStaticMovingObjectIndex()>=0
end
-- before is permitted only immediately after the caller validates the live pose.
-- Ordinary moves and rollback still read the world, never an earlier solver pose.
function World.move(b,x,y,z,sq,readPass,before,skipInvalidation)
    assert(CVPWorldNative and CVPWorldNative.move,'CVP native movement unavailable; update the mod JAR and restart the game')
    CVPWorldNative.move(b,x,y,z,sq,readPass,before,skipInvalidation)
end
return World
