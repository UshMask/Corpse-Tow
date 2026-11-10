-- Optional Horse 1.1.x bridge. Read its objects; never change its movement,
-- stamina, genes or files. Saved animal IDs are not Horse's network IDs.
local H={}
local manager,mounts
local known=setmetatable({},{__mode='v'})
local function api()
    if manager then return true end
    if not getActivatedMods or not getActivatedMods():contains('Horse') then return false end
    manager=require 'HorseMod/HorseManager';mounts=require 'HorseMod/Mounts'
    return true
end
function H.enabled() return SandboxVars.CorpseProxyLab.HorseTowing~=false and api() end
function H.key(horse) return tostring(horse:getAnimalID()) end
function H.all() return api() and manager.horses or {} end
function H.remember(key,horse) known[key]=horse or nil end
function H.dead(key)
    local horse=known[key]
    return horse and H.key(horse)==key and horse:isDead() and horse:getSquare() and horse or nil
end
function H.find(key)
    local found
    for _,horse in ipairs(H.all()) do if H.key(horse)==key and horse:getSquare() then
        if found and found~=horse then return end
        found=horse
    end end
    if found then known[key]=found end
    return found or known[key] and known[key]:isDead() and known[key]:getSquare() and known[key]
end
function H.mounted(player) return api() and mounts.hasMount(player) or false end
function H.rider(horse) return api() and mounts.getRider(horse) end
function H.stopped(horse)
    return horse and not horse:isDead() and horse:getMovementSpeed()<.01 and not horse:getVariableBoolean('HorseMountedMoving')
end
function H.active(horse)
    local rider=H.rider(horse)
    return H.enabled() and not horse:isDead() and rider and not rider:isDead()
end
function H.sample(horse)
    if not horse or horse:isDead() or not horse:getSquare() then return end
    -- Start with a fixed low rear attachment, not a dependency on animation bones.
    local angle=horse:getDirectionAngle()*math.pi/180
    return {kind='horse',key=H.key(horse),point='harness',
        x=horse:getX()-math.cos(angle)*.65,y=horse:getY()-math.sin(angle)*.65,z=horse:getZ()+.55}
end
return H
