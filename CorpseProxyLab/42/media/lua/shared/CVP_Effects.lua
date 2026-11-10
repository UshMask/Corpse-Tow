-- Accumulate committed travel once; expensive effects run at staggered 0.5 s intervals.
local Blood=require 'CVP_Blood'
local Abrasion=require 'CVP_Abrasion'
local Clothing=require 'CVP_ClothingWear'
local Body=require 'CVP_BodyWear'
local Carcass=require 'CVP_CarcassWear'
local E={serial=0}
function E.committed(group,pending,now)
    if isClient() then return end
    local rules=SandboxVars.CorpseProxyLab or {}
    local blood=rules.BloodTrails~=false;local abrasion=rules.CosmeticWear~=false
    local clothing=rules.ClothingWear~=false;local carcass=rules.CarcassWear~=false
    local body=rules.BodyWear==true
    local mask=(blood and 1 or 0)+(abrasion and 2 or 0)+(clothing and 4 or 0)
        +(carcass and 8 or 0)+(body and 16 or 0)
    local due
    for _,r in ipairs(group.records) do
        -- Do not apply a pending shared interval to a newly enabled consumer.
        if r.effectMask~=mask then r.effectMask=mask;r.effectTravel=0 end
        if not blood then r.bloodDistance=0 end
        if not abrasion then r.wearDistance=0 end
        if mask~=0 then
        local b,p=r.body,r.before
        local dx,dy=(r.x or b:getX())-p.x,(r.y or b:getY())-p.y
        local distance=math.sqrt(dx*dx+dy*dy)
        if distance>4 or math.floor(r.z or b:getZ())~=math.floor(p.z) then
            r.effectTravel=0;r.bloodDistance=0;r.wearDistance=0
        else r.effectTravel=(r.effectTravel or 0)+distance end
        if not r.effectDue then
            E.serial=E.serial+1;r.effectDue=now+(E.serial*137)%500
        end
        if now>=r.effectDue then
            r.effectDue=r.effectDue+(math.floor((now-r.effectDue)/500)+1)*500
            r.effectDistance=r.effectTravel or 0;r.effectTravel=0
            if not due then due={records={}} end
            due.records[#due.records+1]=r
        end
        end
    end
    if due then
        if blood then Blood.committed(due) end
        if abrasion then Abrasion.committed(due) end
        if clothing then Clothing.committed(due,now) end
        if carcass then Carcass.committed(due) end
        if body then Body.committed(due,pending) end
        for _,r in ipairs(due.records) do r.effectDistance=nil end
    end
end
return E
