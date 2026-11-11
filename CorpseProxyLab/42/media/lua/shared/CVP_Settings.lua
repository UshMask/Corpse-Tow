-- World rules live in vanilla SandboxOptions, not the per-client preferences file.
local S={booleans={'CarcassWear','BodySpread','Enabled','VehicleDrag','HorseTowing','AllowPlayerCorpses','AllowDetachOthers','BloodTrails','CosmeticWear','ClothingWear','BodyWear'},
    enums={'CarcassWearRate','BodySpreadWidth','BodySpreadStrength','BloodTrailDensity','ClothingWearRate','BodyWearRate'}}
function S.validLimit(value)
    return type(value)=='number' and value>=0 and value<=100000 and value==math.floor(value)
end
function S.set(name,value)
    if isClient() or isServer() or not getPlayer() then return false end
    local allowed=false
    for _,key in ipairs(S.booleans) do if key==name and type(value)=='boolean' then allowed=true end end
    for _,key in ipairs(S.enums) do if name==key then allowed=value==1 or value==2 or value==3 end end
    if name=='MaxBodiesPerChain' then allowed=S.validLimit(value) end
    if not allowed then return false end
    local options=getSandboxOptions()
    if not options:getOptionByName('CorpseProxyLab.'..name) then return false end
    options:set('CorpseProxyLab.'..name,value)
    options:toLua()
    return true
end
return S
