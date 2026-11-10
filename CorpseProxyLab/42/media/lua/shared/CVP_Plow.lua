-- Ownership adapter for PlowAttachment 0.3.2. Its own registration path stays
-- untouched: Tow waits until Plow has finished with the original world corpse.
local P={}
local clientGraph,clientBodies
local motionTables={'_pile','_coast','_spin','_seenAhead','_mpDirtyBody'}
local function owned(body)
    local md=body:getModData()
    if md.CVPTether then return true end
    local key=md.CVPBodyKey;if not key then return false end
    if isClient() and not isServer() then
        local graph=CVPMPClient and CVPMPClient.graph
        if graph~=clientGraph then
            clientGraph=graph;clientBodies={}
            for _,link in pairs(graph and graph.links or {}) do
                if link.a.kind=='body' then clientBodies[link.a.key]=true end
                if link.b.kind=='body' then clientBodies[link.b.key]=true end
            end
        end
        return clientBodies and clientBodies[key]==true or false
    end
    local runtime=isServer() and CVPMPServer and CVPMPServer.authority or CVPRuntime and CVPRuntime.authority
    local index=runtime and runtime.service.index
    return index and index.byBody[key]~=nil or false
end
local function live(body)
    return body and body:getSquare() and body:getStaticMovingObjectIndex()>=0
end
local function clearMotion(plow,body)
    for _,name in ipairs(motionTables) do
        if plow[name] then plow[name][body]=nil end
    end
    local tracks=PlowDrag and PlowDrag._track
    local id=tracks and body.getObjectIDAsLong and body:getObjectIDAsLong()
    if id and tracks[id] and tracks[id].body==body then tracks[id]=nil end
end
function P.busy(body)
    P.install()
    local p=PlowBlade;if not p or not p._cvpAdapter then return false end
    -- A server snapshot can claim a body before this client has flushed Plow's
    -- last move. Stop local Plow motion, then let its normal flush finish first.
    if owned(body) then clearMotion(p,body) end
    local now=getTimestampMs();local pile=p._pile and p._pile[body]
    return pile and now-pile.ms<=(p.STICK_EXPIRE_MS or 500)
        or p._coast and p._coast[body]~=nil
        or p._fastMoved and p._fastMoved[body]~=nil
        or p._mpLastMovedMs and p._mpLastMovedMs[body] and now-p._mpLastMovedMs[body]<500 or false
end
function P.install()
    local p=PlowBlade
    if not p or p._cvpAdapter then return end
    -- Feature gate: leave an unknown Plow API alone rather than half-installing.
    for _,name in ipairs({'collectSquares','moveBody','relocateRemote','mpValidateMove',
        'updateCoast','flushFastMoved'}) do
        if type(p[name])~='function' then return end
    end
    if type(p._squares)~='table' or type(p._fastMoved)~='table' or type(p._coast)~='table' then return end
    local collect=p.collectSquares
    local views={}
    p.collectSquares=function(...)
        local count=collect(...)
        for i=1,count do
            local square=p._squares[i];local objects=square:getStaticMovingObjects()
            local view=views[i];local n=0;local filtered=false
            if not view then
                view={rows={}}
                function view:size() return self.count end
                function view:get(index) return self.rows[index+1] end
                function view:getStaticMovingObjects() return self end
                views[i]=view
            end
            for j=0,objects:size()-1 do local body=objects:get(j)
                if instanceof(body,'IsoDeadBody') and owned(body) then
                    filtered=true;clearMotion(p,body)
                else n=n+1;view.rows[n]=body end
            end
            for j=n+1,#view.rows do view.rows[j]=nil end
            view.count=n
            if filtered then p._squares[i]=view end
        end
        -- Release Java references left by a previous, larger scan.
        for i=count+1,#views do local v=views[i]
            for j=1,#v.rows do v.rows[j]=nil end;v.count=0
        end
        return count
    end
    for _,name in ipairs({'moveBody','relocateRemote'}) do local original=p[name]
        p[name]=function(body,...)
            if not live(body) or owned(body) then clearMotion(p,body);return false end
            return original(body,...)
        end
    end
    local validate=p.mpValidateMove
    p.mpValidateMove=function(message,body,...)
        return live(body) and not owned(body) and validate(message,body,...) or false
    end
    local coast=p.updateCoast
    p.updateCoast=function(...)
        for body in pairs(p._coast) do
            if not live(body) or owned(body) then clearMotion(p,body) end
        end
        return coast(...)
    end
    p._cvpAdapter=true
end
-- Both loading orders are supported; these events run after Lua files load.
Events.OnGameStart.Add(P.install)
Events.OnServerStarted.Add(P.install)
return P
