-- Distance-based authority wear. Broken clothing is unwearable, but remains loot.
local W={}
local rates={40,20,10}
local function clothes(body)
    if body:isPlayer() or body:isAnimal() or body:isSkeleton() or not body.getWornItems then return end
    return body:getWornItems()
end
local function eligible(item)
    return instanceof(item,'Clothing') and item:getVisual()
end
function W.snapshot(body)
    local worn=clothes(body);if not worn then return end
    local rows={}
    for id in pairs(body:getModData().CVPBrokenClothes or {}) do
        local item=body:getContainer():getItemWithID(tonumber(id))
        if item and item:getCondition()==0 then rows[#rows+1]={id=item:getID(),condition=0,holes={}} end
    end
    for i=0,worn:size()-1 do local item=worn:getItemByIndex(i)
        if eligible(item) and item:getCondition()>0 and item:getModData().CVPTowWear then
            local holes={};local v=item:getVisual()
            for n=0,BloodBodyPartType.MAX:index()-1 do
                if v:getHole(BloodBodyPartType.FromIndex(n))>0 then holes[#holes+1]=n end
            end
            rows[#rows+1]={id=item:getID(),condition=item:getCondition(),holes=holes}
        end
    end
    if #rows>0 then return rows end
end
function W.apply(body,rows)
    if not rows then return end
    local worn=clothes(body);if not worn then return end
    local changed=false;local pending=false
    for _,row in ipairs(rows) do
        local item=worn:getItemById(row.id) or body:getContainer():getItemWithID(row.id)
        if item and eligible(item) then
            local condition=math.max(0,math.min(item:getCondition(),row.condition))
            if item:getCondition()>condition then item:setCondition(condition);changed=true end
            local v=item:getVisual()
            for _,n in ipairs(row.holes) do local part=BloodBodyPartType.FromIndex(n)
                if v:getHole(part)==0 then v:setHole(part);changed=true end
            end
            item:getModData().CVPTowWear=true
            if condition==0 then
                if worn:getItemById(row.id)==item then worn:remove(item);changed=true end
                local md=body:getModData();md.CVPBrokenClothes=md.CVPBrokenClothes or {}
                md.CVPBrokenClothes[tostring(item:getID())]=true
            end
        else pending=true end
    end
    if changed then body:invalidateCorpse() end
    return not pending
end
function W.trail(r,now)
    if isClient() or SandboxVars.CorpseProxyLab.ClothingWear==false then return end
    local b,p=r.body,r.before;local worn=clothes(b);if not worn then return end
    local dx,dy=b:getX()-p.x,b:getY()-p.y
    local distance=r.effectDistance or math.sqrt(dx*dx+dy*dy)
    if (not r.effectDistance and distance>4) or math.floor(b:getZ())~=math.floor(p.z) then return end
    local md=b:getModData()
    local progress=md.CVPClothingWear
    if distance==0 and type(progress)~='table' then return end
    if type(progress)~='table' then progress={distance=0,turn=0};md.CVPClothingWear=progress end
    progress.distance=progress.distance+distance
    if now and r.clothingDue and now<r.clothingDue then return end
    if now then r.clothingDue=now+2000 end
    local spacing=rates[SandboxVars.CorpseProxyLab.ClothingWearRate or 2] or 20
    if progress.distance<spacing then return end
    -- Changing the rate must not cause a backlog of damage on following ticks.
    local damage=math.floor(progress.distance/spacing)
    progress.distance=progress.distance%spacing
    local items={}
    for i=0,worn:size()-1 do local item=worn:getItemByIndex(i)
        if eligible(item) and item:getCondition()>0 then items[#items+1]=item end
    end
    if #items==0 then return end
    local item=items[progress.turn%#items+1];progress.turn=progress.turn+1
    local parts=item:getCanHaveHoles() and item:getCoveredParts();local v=item:getVisual()
    for i=0,(parts and parts:size() or 0)-1 do local part=parts:get(i)
        -- Do not tear through a repaired patch or modify its materials.
        if item:getCanHaveHoles() and v:getHole(part)==0 and not item:getPatchType(part) then v:setHole(part);break end
    end
    item:setCondition(math.max(0,item:getCondition()-damage))
    if item:getCondition()==0 then
        worn:remove(item)
        md.CVPBrokenClothes=md.CVPBrokenClothes or {};md.CVPBrokenClothes[tostring(item:getID())]=true
    end
    item:getModData().CVPTowWear=true;b:invalidateCorpse()
end
function W.committed(group,now)
    for _,r in ipairs(group.records) do
        local ok,err=pcall(W.trail,r,now)
        if not ok and not W.reported then W.reported=true;print('[CVP clothing] '..tostring(err)) end
    end
end
return W
