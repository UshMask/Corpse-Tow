-- Vanilla skin overlays only. HumanVisual owns persistence; no inventory edits.
local A={}
local function visual(body)
    if body:isAnimal() or not BloodBodyPartType or not body.getHumanVisual or body:isSkeleton() then return end
    return body:getHumanVisual()
end
function A.snapshot(body)
    local v=visual(body);if not v then return end
    local part=BloodBodyPartType.Torso_Upper
    return {blood=v:getBlood(part),dirt=v:getDirt(part)}
end
function A.apply(body,state)
    if not state then return end
    local v=visual(body);if not v then return body:isSkeleton() end
    local part=BloodBodyPartType.Torso_Upper
    -- Never clean pre-existing vanilla blood/dirt when an older sample arrives.
    local blood=math.max(v:getBlood(part),state.blood)
    local dirt=math.max(v:getDirt(part),state.dirt)
    if blood==v:getBlood(part) and dirt==v:getDirt(part) then return end
    v:setBlood(part,blood);v:setDirt(part,dirt);body:invalidateCorpse()
end
function A.trail(r)
    if isClient() then return end
    local b,p=r.body,r.before
    if SandboxVars.CorpseProxyLab.CosmeticWear==false or not visual(b) then r.wearDistance=0;return end
    local dx,dy=b:getX()-p.x,b:getY()-p.y
    local distance=r.effectDistance or math.sqrt(dx*dx+dy*dy)
    if math.floor(b:getZ())~=math.floor(p.z) or (not r.effectDistance and distance>4) then r.wearDistance=0;return end
    local total=(r.wearDistance or 0)+distance
    local steps=math.floor(total/5);r.wearDistance=total%5
    if steps==0 then return end
    local state=A.snapshot(b)
    state.blood=math.min(1,state.blood+.05*steps)
    state.dirt=math.min(1,state.dirt+.1*steps)
    A.apply(b,state)
end
function A.committed(group)
    for _,r in ipairs(group.records) do
        local ok,err=pcall(A.trail,r)
        if not ok and not A.reported then A.reported=true;print('[CVP wear] '..tostring(err)) end
    end
end
return A
