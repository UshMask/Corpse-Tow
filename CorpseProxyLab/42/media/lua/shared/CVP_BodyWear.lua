-- Distance wears cargo; the ledger keeps the tether independent of that cargo.
-- A durable corpse marker precedes irreversible changes. Replays are idempotent.
local W={}
local distances={2000,1000,500}
local function eligible(b) return b and b:isZombie() and not b:isPlayer() end
function W.distance() return distances[(SandboxVars.CorpseProxyLab or {}).BodyWearRate or 2] or 1000 end
local function checkpoint(b)
    local ok,result=pcall(CVPEquipmentPersistence.checkpointSquare,b:getSquare())
    return ok and result==true
end
function W.committed(group,pending)
    if isClient() or (SandboxVars.CorpseProxyLab or {}).BodyWear~=true then return end
    for _,r in ipairs(group.records) do local b,p=r.body,r.before
        if eligible(b) then
            local dx,dy=b:getX()-p.x,b:getY()-p.y;local distance=r.effectDistance or math.sqrt(dx*dx+dy*dy)
            if distance>0 and (r.effectDistance or distance<=4) and math.floor(b:getZ())==math.floor(p.z) then
                local md=b:getModData();local row=md.CVPBodyWear
                if type(row)~='table' then row={distance=0,stage=b:isSkeleton() and 1 or 0};md.CVPBodyWear=row end
                if not row.pending then
                    if b:isSkeleton() and row.stage==0 then row.stage=1;row.distance=0 end
                    row.distance=row.distance+distance
                    local limit=W.distance()*(row.stage==1 and .5 or 1)
                    if row.distance>=limit then
                        row.pending=row.stage+1
                        if pending then pending[b]=b:getSquare() end
                    end
                end
            end
        end
    end
end
function W.observe(runtime)
    local pending=runtime.simulation.wearPending
    for _,b in pairs(runtime.host.bodies) do if eligible(b) then
        local row=b:getModData().CVPBodyWear
        if type(row)=='table' and (row.pending==1 or row.pending==2) and b:getSquare() then
            pending[b]=pending[b] or b:getSquare()
        end
    end end
end
local function recoverBody(runtime,b,square,row)
    local live=b:getStaticMovingObjectIndex()>=0
    if live then square=b:getSquare() end
    if not square or getCell():getGridSquare(square:getX(),square:getY(),square:getZ())~=square then
        return false,'body wear square unavailable'
    end
    runtime.simulation.wearPending[b]=square
    if not CVPBodyWearNative then return false,'body wear backend unavailable' end
    -- If removal already happened in memory, retry its final checkpoint.
    if live and not checkpoint(b) then return false,'body wear marker save failed' end
    if row.pending==1 then
        local ok,done=pcall(CVPBodyWearNative.skeleton,b)
        if not ok or not done then return false,'skeleton transition save failed' end
        row.stage=1;row.distance=0;row.pending=nil
        if not checkpoint(b) then row.pending=1;return false,'skeleton state save failed' end
    else
        local key=b:getModData().CVPBodyKey
        local ok,why=runtime.service:unloadBody(key,{x=b:getX(),y=b:getY(),z=math.floor(b:getZ())+.05})
        if not ok then return false,why end
        local called,done=pcall(CVPBodyWearNative.remove,b,square)
        if not called or not done then return false,'body removal save failed' end
        -- The square checkpoint already confirmed removal. Do not rediscover an
        -- in-memory corpse retained by another cache as an unfinished transition.
        row.stage=2;row.pending=nil
    end
    return true
end
function W.recover(runtime)
    local pending=runtime.simulation.wearPending
    local retries=runtime.wearRetries or {};runtime.wearRetries=retries
    local now=runtime.host.now();local problem
    for b,square in pairs(pending) do
        local row=b:getModData().CVPBodyWear
        if not row or not row.pending or not eligible(b) then pending[b]=nil;retries[b]=nil
        else
            local retry=retries[b]
            if not retry or now>=retry.at then
                local stage=row.pending
                local called,ok,why=pcall(recoverBody,runtime,b,square,row)
                if called and ok then
                    pending[b]=nil;retries[b]=nil
                    -- UI failures must never retry a committed destructive transition.
                    pcall(W.notify,runtime,b,stage)
                else
                    local err=tostring(called and why or ok)
                    retries[b]={at=now+5000,error=err};problem=problem or err
                end
            else problem=problem or retry.error end
        end
    end
    return problem==nil,problem
end
function W.notify(runtime,b,stage)
    local data={stage=stage,x=b:getX(),y=b:getY(),z=b:getZ()}
    if isServer() then
        for _,p in pairs(runtime.host.players) do
            if math.floor(p:getZ())==math.floor(data.z) and (p:getX()-data.x)^2+(p:getY()-data.y)^2<=35^2 then
                sendServerCommand(p,'CVP','wearNotice',data)
            end
        end
    elseif CVPFeedback and CVPFeedback.wearNotice then CVPFeedback.wearNotice(data) end
end
return W
