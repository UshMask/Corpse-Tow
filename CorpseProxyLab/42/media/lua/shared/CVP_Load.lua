local Load={}
local massSerial=0
local velocity
-- Build 42.21: BaseVehicle drains this queue into force * 30 for ONE
-- WorldSimulation step (0.01 s), so a queued amount delivers amount * 0.3 Ns.
-- Convert our time-integrated resistance into the native queue's units.
local nativeImpulseScale=30*0.01
-- Game weight is not kilograms. Use a nominal adult mass plus carried loot.
function Load.mass(container,baseMass)
    local weight=0
    local items=container:getItems()
    for i=0,items:size()-1 do local item=items:get(i)
        weight=weight+math.max(0,item:getActualWeight())
        if instanceof(item,'InventoryContainer') then weight=weight+Load.mass(item:getInventory())-75 end
    end
    return (baseMass or 75)+weight
end
-- Refresh mutable loot at most once a second, not on every physics tick.
function Load.refresh(r,now)
    if not r.nextMassRefresh or now>=r.nextMassRefresh then
        -- Animal corpses persist AnimalData.getWeight(); humans retain nominal mass.
        local base=75
        if r.body:isAnimal() then
            local weight=r.body:getWeight()
            if type(weight)=='number' and weight==weight and weight>0 and weight<math.huge then base=weight end
        end
        r.mass=Load.mass(r.body:getContainer(),base)
        if not r.nextMassRefresh then
            massSerial=massSerial+1
            r.nextMassRefresh=now+1000-(massSerial*137)%1000
        else
            r.nextMassRefresh=r.nextMassRefresh+(math.floor((now-r.nextMassRefresh)/1000)+1)*1000
        end
    end
end
-- An unloaded body contributes no resistance; tension builds over about half a second.
function Load.blend(dt) return 1-math.exp(-math.max(0,dt)/0.2) end
function Load.tension(r,taut,dt,blend)
    if not taut then r.loadMass=0;return 0 end
    local target=math.max(0,r.mass or 0)
    blend=blend or Load.blend(dt)
    r.loadMass=(r.loadMass or 0)+(target-(r.loadMass or 0))*blend
    return r.loadMass
end
local function root(r)
    while r.loadRoot~=r do r.loadRoot=r.loadRoot.loadRoot;r=r.loadRoot end
    return r
end
local function join(a,b)
    a=root(a);b=root(b)
    if a==b then return end
    if a.loadRank<b.loadRank then a,b=b,a end
    b.loadRoot=a
    if a.loadRank==b.loadRank then a.loadRank=a.loadRank+1 end
end
-- A body can transmit resistance through a taut tether OR compression against
-- another body. Slack alone is not a connection. Rebuild each substep: no grace
-- period that keeps a genuinely loose, separated tail pulling the vehicle.
function Load.connect(records,contacts)
    if #contacts==0 then
        for _,r in ipairs(records) do
            r.loadConnected=r.taut and not r.failed and (not r.parent or r.parent.loadConnected)
        end
        return
    end
    for _,r in ipairs(records) do r.loadRoot=r;r.loadRank=0;r.loadDriven=false end
    for _,r in ipairs(records) do
        if r.parent and r.taut and not r.failed and not r.parent.failed then join(r,r.parent) end
    end
    for i=1,#contacts,2 do local a,b=contacts[i],contacts[i+1]
        if not a.failed and not b.failed then join(a,b) end
    end
    for _,r in ipairs(records) do
        if not r.parent and r.taut and not r.failed then root(r).loadDriven=true end
    end
    for _,r in ipairs(records) do r.loadConnected=not r.failed and root(r).loadDriven end
end
function Load.impulse(forceN,speed,vehicleMass,dt)
    if forceN<=0 or vehicleMass<=0 or speed<0.02 or dt<=0 then return 0 end
    -- Force [N] times interval [s] yields impulse [N s].
    -- A time-based momentum cap also handles multiple Lua ticks queued before
    -- the next physics step at high FPS, without an abrupt reverse impulse.
    return math.min(forceN*dt,vehicleMass*speed*(1-math.exp(-8*dt)))
end
-- Fresh samples retain their exact force. Missing feedback fades to zero rather
-- than releasing all resistance abruptly at a timeout or replaying an old impulse.
function Load.freshness(ageMs)
    return math.max(0,math.min(1,(1000-math.max(0,ageMs or 0))/750))
end
function Load.apply(vehicle,forceN,dt,ageMs)
    forceN=forceN*Load.freshness(ageMs)
    if forceN<=0 or dt<=0 then return end
    -- B42 SP cars retain Server authorization, so this network flag is false
    -- even for the player's car. Enforce ownership only in multiplayer.
    if (isClient() or isServer()) and not vehicle:isLocalPhysicSim() then return end
    velocity=velocity or Vector3f.new()
    local vel=vehicle:getLinearVelocity(velocity)
    local x,y=vel:x(),vel:z();local speed=math.sqrt(x*x+y*y)
    -- The payload already encodes solver reaction; do not amplify it by terrain.
    local amount=Load.impulse(forceN,speed,vehicle:getMass(),dt)
    if amount>0 then CVPWorldNative.applyVehicleResistance(vehicle,amount/nativeImpulseScale) end
end
return Load
