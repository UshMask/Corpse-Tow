local Clock=require 'CVP_SimulationClock'
local SimulationFrame=require 'CVP_SimulationFrame'
-- SP and server share one authority. No client may open this ledger or advance
-- its world bodies; adapters supply their current online-player list.
local E=require 'CVP_Equipment'
local World=require 'CVP_World'
local Load=require 'CVP_Load'
local Runtime={};Runtime.__index=Runtime
if LuaEventManager then LuaEventManager.AddEvent('OnCVPVehicleRemoved') end
local function empty(t) for _ in pairs(t) do return false end;return true end
function Runtime.new(host)
    assert(not isClient() or isServer(),'link runtime requires world authority')
    host=host or require('CVP_LinkHost').new()
    return setmetatable({host=host,service=require('CVP_LinkService').new(E,host),
        simulation=require('CVP_LinkSimulation').new(host,E),seenBodies={},
        recovered=setmetatable({},{__mode='k'}),recoveryErrors=setmetatable({},{__mode='k'}),nextDiscovery=0,saveQueue={}},Runtime)
end
function Runtime:start()
    if self.started then return true end
    if not CVPSkeletonNative or not CVPSkeletonNative.version or CVPSkeletonNative.version()~='2-graph-clocks' then
        return false,'skeleton graph backend unavailable'
    end
    local ok,err=self.service:load();if not ok then return false,err end
    self.started=true;return true
end
function Runtime:players(players)
    self.host.players={}
    for _,p in ipairs(players) do self.host.actor(p) end
    local missing={}
    for holder in pairs(self.service.index.held) do
        local p=self.host.players[holder];local actor=p and self.host.actor(p)
        if not actor or not actor.alive or not actor.onFoot then missing[#missing+1]=holder end
    end
    for _,holder in ipairs(missing) do
        local ok,err=self.service:disconnect(holder);if not ok then return false,err end
    end
    return true
end
function Runtime:discover(players)
    self.host.discover()
    require('CVP_BodyWear').observe(self)
    local now=self.host.now()
    for _,p in ipairs(players) do
        if not self.recovered[p] or now>=self.recovered[p] then
            local saved,why=self.service:flush();if not saved then return false,why end
            local ok,err=E.recover(p)
            -- A single unresolved transfer stays unavailable, but cannot stop
            -- every other player's independent train from moving.
            self.recoveryErrors[p]=not ok and err or nil
            self.recovered[p]=now+5000
        end
    end
    for _,body in pairs(self.host.bodies) do if body then
        local ok,err=E.observeClock(body);if not ok then self.recoveryErrors[body]=err end
    end end
    if not self.groundRetry or now>=self.groundRetry then
        local pending,why=E.hasFreeWork(self.service.graph,self.service.index)
        if pending==nil then return false,why end
        if pending then
            local saved,why=self.service:flush();if not saved then return false,why end
            local ok,err=E.dropFree();self.groundError=not ok and err or nil
            self.groundRetry=not ok and now+5000 or nil
        else self.groundError=nil;self.groundRetry=nil end
    end
    local graph,err=self.service:refresh();if not graph then return false,err end
    return require('CVP_Legacy').migrate(self)
end
function Runtime:removedVehicleRequests()
    local requests={};local graph=self.service.graph
    for id,request in pairs(self.removedVehicleEnds or {}) do
        local link=graph.links[id]
        if link and link[request.side].kind=='vehicle' and link[request.side].key==request.vehicleKey then
            request.revision=link.revision
            requests[#requests+1]=request
        else self.removedVehicleEnds[id]=nil end
    end
    return requests
end
function Runtime:removedEnds()
    local requests=self:removedVehicleRequests();local graph=self.service.graph
    for key,edges in pairs(self.service.index.byHorse) do
        local horse=self.host.horse({key=key})
        if horse and horse:isDead() then for _,edge in ipairs(edges) do
            requests[#requests+1]={id=edge.id,revision=graph.links[edge.id].revision,side=edge.side,where=graph.links[edge.id][edge.side],reason='horse_dead'}
        end end
    end
    for key,edges in pairs(self.service.index.byBody) do
        local body=self.host.body({key=key});local previous=self.seenBodies[key]
        if body then
            self.seenBodies[key]={body=body,square=body:getSquare(),x=body:getX(),y=body:getY(),z=body:getZ()}
        elseif previous then
            -- A missing chunk/object is not proof of deletion. Require the same
            -- still-loaded square and the original object's removal from it.
            local square=getCell():getGridSquare(math.floor(previous.x),math.floor(previous.y),math.floor(previous.z))
            if square and square==previous.square and previous.body:getSquare()==square
                and previous.body:getStaticMovingObjectIndex()<0 then
                for _,edge in ipairs(edges) do
                    requests[#requests+1]={id=edge.id,revision=graph.links[edge.id].revision,side=edge.side,where=graph.links[edge.id][edge.side],reason='body_removed'}
                end
            end
        end
    end
    for key,previous in pairs(self.seenBodies) do if not self.service.index.byBody[key] then
        local square=getCell():getGridSquare(math.floor(previous.x),math.floor(previous.y),math.floor(previous.z))
        -- Also retire clocks for confirmed removed bodies after saving their old
        -- square; unloading alone must retain the durable pending clock.
        if square==previous.square and previous.body:getSquare()==square then
            local ok=E.observeClock(previous.body,square);if ok then self.seenBodies[key]=nil end
        else self.seenBodies[key]=nil end
    end end
    return requests
end
-- Wreckers may recreate a packed vehicle with a different SQL ID. Bodies stay
-- outside: release the old vehicle end rather than silently retargeting it.
-- The native event follows permanent deletion, never ordinary chunk unloading.
function Runtime:vehicleRemoved(vehicle)
    if not self.started then return end
    local graph=self.service.graph;local sql=vehicle:getSqlId()
    local keys={sql and ('sql:'..tostring(sql)),vehicle:getModData().CVPVehicleKey}
    self.removedVehicleEnds=self.removedVehicleEnds or {}
    for _,key in pairs(keys) do for _,edge in ipairs(self.service.index.byVehicle[key] or {}) do
        local link=graph.links[edge.id]
        self.removedVehicleEnds[edge.id]={id=edge.id,revision=link.revision,side=edge.side,
            vehicleKey=key,where=link[edge.side],reason='vehicle_removed'}
    end end
    self.loads={};self.simulationFrame=nil
end
function Runtime:samples(forPresentation,advance)
    local graph=self.service.graph
    local samples,holders=self.host.samples(graph)
    local ok,why=true,nil
    if advance~=false then ok,why=self.service:tick(samples,holders) end
    if not ok or self.service.graph~=graph then return ok,why end
    return ok,why,samples
end
function Runtime:skeletons()
    local now=self.host.now();if self.clockNextTry and now<self.clockNextTry then return end
    local generation=self.host.generationFor and self.host.generationFor(self.service.index) or self.host.generation
    if self.clockIndex==self.service.index and self.clockGeneration==generation then return end
    for key in pairs(self.service.index.byBody) do
        local body=self.host.body({key=key});if body then
            local ok,err=pcall(CVPSkeletonNative.sync,body)
            if not ok then self.clockError=tostring(err);self.clockNextTry=now+5000;return end
        end
    end
    self.clockError=nil;self.clockNextTry=nil
    self.clockIndex=self.service.index;self.clockGeneration=generation
end
function Runtime:submit(player,name,args,callback)
    if self.saveJob and self.saveJob.player==player or #self.saveQueue>=16 then
        callback(false,nil,'equipment operation pending');return
    end
    for _,waiting in ipairs(self.saveQueue) do
        if waiting.player==player then callback(false,nil,'equipment operation pending');return end
    end
    local x,y,z=player:getX(),player:getY(),player:getZ()
    local Jobs=require 'CVP_SaveJobs'
    local deadline=self.host.now()+8000
    local job
    job=Jobs.new(function() return self:request(player,name,args) end,function(...)
        if self.saveJob==job then self.saveJob=nil end
        callback(...)
    end,function()
        if job.cancelReason then return job.cancelReason end
        if self.host.now()>=deadline then return 'IGUI_CVP_ResultUnknown' end
        if job.disconnected then return 'player disconnected' end
        if player:isDead() or player:getVehicle() then return 'leave vehicle or unavailable player' end
        if player:getZ()~=z or (player:getX()-x)^2+(player:getY()-y)^2>.04 then return 'endpoint not reachable' end
    end)
    job.player=player
    if self.saveJob or #self.saveQueue>0 then self.saveQueue[#self.saveQueue+1]=job
    else self.saveJob=job;Jobs.advance(job) end
    return job
end
function Runtime:cancel(job)
    if job and not job.done and not job.committed then job.cancelReason='IGUI_CVP_CancelledQueue' end
end
-- One authority accumulator; only the source clock differs between SP and MP.
-- Keep fractional time, cap catch-up work, and integrate each solved load once.
function Runtime:simulate(dt,now)
    self.motionUpdated=false;self.loadElapsed=0
    local clock=not isServer() and not isClient() and CVPVehicleMotion and CVPVehicleMotion.localTime()
    local elapsed,steps=Clock.advance(self,dt,now,clock)
    local graph,index=self.service.graph,self.service.index
    local urgent=self.motionGraph~=graph or self.motionIndex~=index
        or self.simulation.pendingPoses or self.simulation.calculating
        or not self.host.enabled() or empty(graph.links) or not empty(self.simulation.wearPending)
    if not urgent and steps==0 then return {},self.loads or {} end
    self.loadElapsed=elapsed
    local requests,loads=self.simulation:tick(graph,index,elapsed,now,self.motionElapsed,self.motionCorrection)
    if elapsed>0 then self.motionCorrection=nil end
    self.motionGraph=graph;self.motionIndex=index;self.motionUpdated=true
    return requests,loads
end
-- Publish only after endpoint maintenance/recovery, never half-way through a tick.
function Runtime:publishFrame(now,samples)
    local graph=self.service.graph
    if not self.motionUpdated and self.simulationFrame and self.simulationFrame.revision==graph.revision
        and empty(self.service.index.held) then return end
    self.simulationSequence=(self.simulationSequence or 0)+1
    self.simulationFrame=SimulationFrame.capture(self.simulation,graph,self.loads or {},now,
        self.loadElapsed or 0,self.simulationSequence,self.host,samples)
end
function Runtime:tick(players,dt,forPresentation)
    self.loadElapsed=0
    local now=self.host.now()
    if self.saveJob or #self.saveQueue>0 then
        if type(players)=='function' then players=players() end
        local online={};for _,p in ipairs(players) do online[p]=true end
        for i=#self.saveQueue,1,-1 do
            local job=self.saveQueue[i];job.disconnected=not online[job.player]
            if job.valid() then
                table.remove(self.saveQueue,i);require('CVP_SaveJobs').advance(job)
            end
        end
        if not self.saveJob and #self.saveQueue>0 then self.saveJob=table.remove(self.saveQueue,1) end
        if self.saveJob and not self.saveJob.committed then
            self.saveJob.disconnected=not online[self.saveJob.player]
        end
    end
    if self.saveJob then
        local job=self.saveJob
        if require('CVP_SaveJobs').advance(job) and self.saveJob==job then self.saveJob=nil end
        -- A completion callback may already have submitted the next batch operation.
        if self.saveJob or #self.saveQueue>0 then
            -- Keep existing towing moving; defer graph mutations/recovery until the transaction finishes.
            E.beginRead()
            local ok,requests,loads=pcall(function()
                local requests,loads=self:simulate(dt,now)
                if #requests>0 and not self.pendingRelease then self.pendingRelease=requests end
                if not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.VehicleDrag~=false then
                    for car,forceN in pairs(loads) do Load.apply(car,forceN,self.loadElapsed or dt) end
                end
                return requests,loads
            end)
            E.endRead()
            if not ok then self.loads={};self.simulationFrame=nil;self.error=tostring(requests);return false,self.error end
            self.loads=loads
            self:publishFrame(now)
            return true
        end
    end
    if self.retryAt and now<self.retryAt then return false,self.error end
    local service=self.service
    -- An idle authority still performs discovery/recovery once a second. Any live link
    -- or unfinished operation keeps the normal per-frame path.
    if self.idleGraph and self.idleGraph==service.graph and now<self.nextDiscovery
        and not service.dirty and not self.pendingRelease and not self.clockNextTry
        and not self.simulation.pendingPoses and not self.simulation.calculating
        and empty(service.graph.links) and empty(service.pending)
        and (not service.rewires or empty(service.rewires))
        and empty(self.simulation.wearPending) and empty(self.seenBodies) then
        -- External ledger changes must wake immediately; failures fall through
        -- to the regular error/backoff handling instead of escaping the event.
        local ok,revision=pcall(service.store.linkRevision)
        if ok and revision~=nil and revision==service.persistedRevision then return true end
    end
    self.idleGraph=nil
    local function run()
        if type(players)=='function' then players=players() end
        local ok,err=self:start();if not ok then return false,err end
        local graph,why=self.service:refresh();if not graph then return false,why end
        local active,reason=self:players(players);if not active then return false,reason end
        if now>=self.nextDiscovery then
            local found,problem=self:discover(players);if not found then return false,problem end
            self.nextDiscovery=now+1000
        end
        if self.pendingRelease then
            local saved,problem=self.service:releaseSystem(self.pendingRelease);if not saved then return false,problem end
            self.pendingRelease=nil
        end
        local removed=self:removedEnds()
        if #removed>0 then
            self.pendingRelease=removed
            local saved,problem=self.service:releaseSystem(removed);if not saved then return false,problem end
            self.pendingRelease=nil
        end
        local recovered,wearError=require('CVP_BodyWear').recover(self)
        self.wearError=not recovered and wearError or nil
        local requests,loads=self:simulate(dt,now)
        if #requests>0 then
            self.pendingRelease=requests
            local saved,problem=self.service:releaseSystem(requests);if not saved then return false,problem end
            self.pendingRelease=nil
        end
        self.loads=loads
        if not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.VehicleDrag~=false then
            for car,forceN in pairs(loads) do Load.apply(car,forceN,self.loadElapsed or dt) end
        end
        local sampled,why,points=self:samples(forPresentation,self.motionUpdated);if not sampled then return false,why end
        local sampledGraph=self.service.graph
        local recovered,wearError=require('CVP_BodyWear').recover(self)
        self.wearError=not recovered and wearError or nil
        if self.service.graph~=sampledGraph then points=nil end
        self:skeletons()
        self:publishFrame(now,points)
        return true,nil,self.simulationFrame.endpoints
    end
    E.beginRead()
    local called,success,problem,points=pcall(run)
    E.endRead()
    if not called or not success then
        self.loads={};self.simulationFrame=nil
        self.error=tostring(called and problem or success);self.retryAt=now+5000
        return false,self.error
    end
    self.error=nil;self.retryAt=nil
    self.idleGraph=empty(self.service.graph.links) and self.service.graph or nil
    return true,nil,points
end
function Runtime:prepare(player,target,gearID)
    local ok,err=self:start();if not ok then return nil,err end
    return self.service:prepare(player,target,gearID)
end
function Runtime:create(player,token,target)
    local ok,err=self:start();if not ok then return false,err end
    local created,why=self.service:create(player,token,target);self:skeletons();return created,why
end
function Runtime:command(player,args)
    local ok,err=self:start();if not ok then return false,err end
    local sampled,why=self:samples();if not sampled then return false,why end
    local done,why=self.service:command(player,args);self:skeletons();return done,why
end
function Runtime:save()
    local ok,err=pcall(self.simulation.restore,self.simulation)
    if not ok then return false,tostring(err) end
    if self.saveJob then return true end -- durable intermediate ledger states remain restart-recoverable
    local removed=self:removedVehicleRequests()
    if #removed>0 then
        local released,why=self.service:releaseSystem(removed);if not released then return false,why end
    end
    return self.service:flush()
end
-- Same command contract for SP and the authenticated multiplayer transport.
function Runtime:request(player,name,args)
    if name=='ropePrepare' then
        local ok,why=self:start();if not ok then return false,nil,why end
        local token,err,reference=self.service:prepare(player,args.target,args.gear,true,args.link,args.revision)
        return token~=nil,token and {token=token,reference=reference} or nil,err
    elseif name=='prepare' then
        local token,err,reference=self:prepare(player,args.target,args.gear)
        return token~=nil,token and {token=token,reference=reference} or nil,err
    elseif name=='create' then
        local done,id=self:create(player,args.token,args.target)
        if not done then return false,nil,id end
        self.loads={};self.simulationFrame=nil
        return true,{id=id,revision=self.service.graph.links[id].revision}
    elseif name=='rewirePrepare' then
        local plan,err=self:prepareRewire(player,args.target);return plan~=nil,plan,err
    elseif name=='rewireVisit' then
        local done,result=self:visitRewire(player,args.token)
        if done and result.done then self.loads={};self.simulationFrame=nil end
        return done,done and result or nil,not done and result or nil
    elseif name=='command' then
        local done,err=self:command(player,args);if done then self.loads={};self.simulationFrame=nil end;return done,nil,err
    end
    return false,nil,'unknown action'
end
function Runtime:prepareRewire(player,ref)
    local ok,err=self:start();if not ok then return nil,err end
    return self.service:prepareRewire(player,ref)
end
function Runtime:visitRewire(player,token)
    local ok,err=self:start();if not ok then return false,err end
    local done,result=self.service:visitRewire(player,token);self:skeletons();return done,result
end
return Runtime
