local Skin=require 'CVP_Abrasion'
local Clothes=require 'CVP_ClothingWear'
local A={cache=setmetatable({},{__mode='k'}),serial=0,phase=0}
local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~='table' then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
function A.capture(body,now,force)
    local cached=A.cache[body]
    if cached and not force and now<cached.due then return cached end
    local skin,clothing=Skin.snapshot(body),Clothes.snapshot(body)
    if not cached then A.phase=(A.phase+137)%500 end
    local revision=cached and cached.revision
    if not cached or not equal(skin,cached.cosmetic) or not equal(clothing,cached.clothing) then
        A.serial=A.serial+1;revision=A.serial
    end
    local due=cached and cached.due or now+500+A.phase
    if now>=due then due=due+(math.floor((now-due)/500)+1)*500 end
    cached={cosmetic=skin,clothing=clothing,revision=revision,due=due}
    A.cache[body]=cached;return cached
end
function A.fill(row,body,now,force)
    local state=A.capture(body,now,force)
    row.cosmetic=state.cosmetic;row.clothing=state.clothing;row.appearanceRevision=state.revision
end
return A
