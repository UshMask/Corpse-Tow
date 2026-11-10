if not isClient() then return end
local W=require 'CVP_LinkWire'
local G=require 'CVP_LinkGraph'
local World=require 'CVP_World'
local Motion=require 'CVP_Motion'
local Load=require 'CVP_Load'
local Clock=require 'CVP_SimulationClock'
local View=require 'CVP_Viewpoint'
local Actions=require 'CVP_LinkActions'
local Menu=require 'CVP_LinkMenu'
local Presentation=require 'CVP_LinkPresentation'
local function empty(t) for _ in pairs(t) do return false end;return true end
local Abrasion=require 'CVP_Abrasion'
local ClothingWear=require 'CVP_ClothingWear'
local C={schema=4,session=getRandomUUID(),graph=G.empty(),rows={},parts={},pending={},retiredEpochs={},finals={},
    sequence=-1,request=0,lastState=0,nextSync=0,nextBody=0,loads={}}
C.host=require('CVP_LinkHost').new()
local vehicle=C.host.vehicle
C.host.vehicle=function(ref)
    local map=ref.key and C.loads[ref.key]
    if map then local v=getVehicleById(map.vehicle);if v and v:getSquare() then return v end;return end
    return vehicle(ref)
end
C.host.vehicleKey=function(v)
    -- Only a server snapshot confirms the persistent identity. Local modData
    -- and database IDs may belong to an older world/build; use the network ID
    -- alone until the server has supplied its key.
    for key,row in pairs(C.loads) do if row.vehicle==v:getId() then return key end end
end
CVPMPClient=C
C.appearances={};C.appearanceApplied=setmetatable({},{__mode='k'})
C.appearanceRetry=setmetatable({},{__mode='k'})
local function send(p,name,args)
    args.protocol=W.version;args.session=C.session;args.epoch=C.epoch
    sendClientCommand(p or getPlayer(),W.module,name,args)
end
local function sync()
    local p=getPlayer();if not p then return end
    local now=getTimestampMs();C.started=C.started or now;C.nextSync=now+2000
    send(p,'sync',{})
end
function C.connectionReason()
    if not CVPBodyPresentation or CVPBodyPresentation.version()~='1-shared-playback'
        or not CVPNetwork or not CVPWorldNative or not CVPFreeRopeScene or not CVPFreeRopeScene.version
        or CVPFreeRopeScene.version()~='1-free-endpoints' then return 'IGUI_CVP_NativeUnavailable' end
    if C.protocolMismatch then return 'IGUI_CVP_ProtocolMismatch' end
    if C.serverFailure and getTimestampMs()-C.serverFailure.time<10000 then return C.serverFailure.key end
    if not C.epoch then return (not C.started or getTimestampMs()-C.started<10000) and 'IGUI_CVP_SyncWaiting' or 'IGUI_CVP_ServerUnavailable' end
    if getTimestampMs()-C.lastState>10000 then return 'IGUI_CVP_SyncLost' end
    if not C.ready then return 'IGUI_CVP_ServerNotReady' end
end
local api={host=C.host,graph=function() return C.graph end,ready=C.connectionReason}
function api.obstacle(id) return C.obstacles and C.obstacles[id] end
function api.request(p,name,args,callback)
    local why=C.connectionReason();if why then callback(false,nil,why);return end
    C.request=C.request+1
    local now=getTimestampMs();local payload={request=C.request,args=G.copy(args)}
    C.pending[C.request]={callback=callback,time=now,epoch=C.epoch,player=p,name=name,payload=payload,nextRetry=now+2000,retries=0}
    send(p,name,payload)
    local id=C.request
    return function()
        local pending=C.pending[id]
        if pending then pending.cancelled=true;send(p,'cancelRequest',{request=id}) end
    end
end
C.actions=Actions.new(api);C.menu=Menu.new(api,C.actions);C.presentation=Presentation.new(C.host);C.api=api
local function untrack(r) if r then
    Motion.unpresent(r,C.host)
    if r.tracked then View.untrack(r.tracked);r.tracked=nil end
    r.body=nil
end end
local function place(body,pose)
    -- Plow's busy check can flush per-body state; keep its sequential adapter.
    if CVPWorldNative and CVPWorldNative.placeClientPose and not PlowBlade and not PlowDrag then
        return CVPWorldNative.placeClientPose(body,pose.x,pose.y,pose.z,pose.angle)
    end
    local square=getCell():getGridSquare(math.floor(pose.x),math.floor(pose.y),math.floor(pose.z))
    if not square or not body:getSquare() or body:getStaticMovingObjectIndex()<0 or body:isBeingGrappled() or World.foreignTowed(body) then return false end
    World.move(body,pose.x,pose.y,pose.z,square)
    World.angle(body,pose.angle)
    return true
end
local function finalPose(key,s,old,body)
    local final=C.finals[key];if final==s.token then return end
    if type(final)~='table' or final.token~=s.token then
        local original=old and old.descriptor.id==s.id and (body or old.body or CVPNetwork.find(s.id))
        if not original then C.finals[key]=s.token;return end
        final={token=s.token,body=original,x=original:getX(),y=original:getY(),z=original:getZ(),angle=original:getAngle()}
        C.finals[key]=final
    end
    local b=final.body
    -- A later ordinary move or a replacement object supersedes this final pose.
    if body and body~=b or b:getX()~=final.x or b:getY()~=final.y or b:getZ()~=final.z or b:getAngle()~=final.angle
        or b:isBeingGrappled() or World.foreignTowed(b) then C.finals[key]=s.token;return end
    if body and place(body,s) then C.finals[key]=s.token end
end
local function resolved(row,force)
    local cached=C.rows[row.key];local now=getTimestampMs()
    if not force and cached and cached.descriptor.id==row.id and cached.descriptor.token==row.token
        and cached.lookupMissing and now<(cached.nextLookup or 0) then return end
    local b=CVPNetwork.find(row.id)
    if cached then cached.nextLookup=now+250;cached.lookupMissing=true end
    if not b or not World.towable(b) or not b:getSquare() or b:getStaticMovingObjectIndex()<0 then return end
    local md=b:getModData()
    if md.CVPBodyKey and md.CVPBodyKey~=row.key then return end
    if cached then cached.lookupMissing=nil end
    md.CVPBodyKey=row.key
    -- Clear only a legacy marker explicitly superseded by the server graph.
    local old=md.CVPTether
    if old and old.connection and old.connection.b and old.connection.b.key==row.key then
        for _,id in ipairs(row.connections) do if old.connection.id==id then md.CVPTether=nil;break end end
    end
    if force then C.appearanceApplied[b]=nil;C.appearanceRetry[b]=nil end
    local appearance=C.appearances[row.key]
    if appearance and appearance.revision==row.appearanceRevision and C.appearanceApplied[b]~=appearance
        and now>=(C.appearanceRetry[b] or 0) then
    local ok,err=pcall(Abrasion.apply,b,appearance.cosmetic)
    if not ok and err~=C.cosmeticError then C.cosmeticError=err;print('[CVP wear] '..tostring(err)) end
    local worn,why=pcall(ClothingWear.apply,b,appearance.clothing)
    if not worn and why~=C.clothingError then C.clothingError=why;print('[CVP clothing] '..tostring(why)) end
    if ok and err~=false and worn and why~=false then C.appearanceApplied[b]=appearance;C.appearanceRetry[b]=nil
    else C.appearanceRetry[b]=now+500 end
    end
    return b
end
local function drain()
    local ready={}
    for id,pending in pairs(C.pending) do
        if pending.result and pending.result.sequence<=C.sequence then ready[#ready+1]=id end
    end
    table.sort(ready)
    for _,id in ipairs(ready) do
        local pending=C.pending[id];C.pending[id]=nil
        local reply=pending.result;pending.callback(reply.ok==true,reply.result,reply.reason)
    end
end
function C.apply(snapshot,args)
    local discover=C.epoch~=args.epoch
    if C.epoch~=args.epoch then
        if C.epoch then C.retiredEpochs[C.epoch]=true end
        local pending=C.pending;C.pending={}
        for _,entry in pairs(pending) do entry.callback(false,nil,'IGUI_CVP_QueueStopped') end
        for _,r in pairs(C.rows) do untrack(r) end
        C.rows={};C.parts={};C.loadAssembly=nil;C.assembly=nil;C.finals={};C.appearances={};C.appearanceApplied=setmetatable({},{__mode='k'});C.appearanceRetry=setmetatable({},{__mode='k'});C.presentation:clear()
        C.epoch=args.epoch;C.endpointRows=nil;C.motionClock=nil;C.loadSequence=-1;C.loadClock={};C.loadOwners={};C.loadReceived=nil
    end
    local previous=C.rows;local rows={};local now=getTimestampMs()
    local orderChanged=discover or not C.orderedRows
    local previousClock=C.motionClock
    if snapshot.sampledAt~=nil then C.motionClock=Motion.syncClock(C.motionClock,snapshot.sampledAt,now) end
    local newClock=C.motionClock~=previousClock
    local sampleTime=snapshot.sampledAt or Motion.time(C.motionClock,now)
    if C.graph.revision~=snapshot.graph.revision then C.visualRevision=nil end
    C.graph=snapshot.graph;C.index=snapshot.index
    C.endpointRows=Motion.pushEndpoints(C.endpointRows,C.graph,sampleTime,newClock,snapshot.bodies)
    if not snapshot.motion and (args.sequence>=(C.loadSequence or -1) or C.loadRevision~=snapshot.graph.revision) then
        C.loads=snapshot.loads;C.loadSequence=args.sequence;C.loadRevision=snapshot.graph.revision
        C.loadReceived=now;C.loadSampledAt=snapshot.sampledAt
    end
    C.obstacles=snapshot.obstacles
    local acknowledgements={};local ackCount=0
    for key,s in pairs(snapshot.bodies) do
        local appearance=C.appearances[key]
        if not s.appearanceOmitted and s.appearanceRevision then
            if not appearance or appearance.revision~=s.appearanceRevision then
                appearance={revision=s.appearanceRevision,cosmetic=G.copy(s.cosmetic),clothing=G.copy(s.clothing)}
                C.appearances[key]=appearance
            end
            acknowledgements[key]=s.appearanceRevision;ackCount=ackCount+1
            if ackCount==64 then send(nil,'appearanceAck',{rows=acknowledgements});acknowledgements={};ackCount=0 end
        elseif s.appearanceOmitted and (not appearance or appearance.revision~=s.appearanceRevision) then
            send(nil,'appearanceMissing',{key=key})
        end
        local old=previous[key]
        -- A newly accepted snapshot permits one retry; empty ticks keep the lookup cooldown.
        if old and old.lookupMissing and not s.retired then old.nextLookup=nil end
        local body=resolved(s)
        if not s.retired and (not old or old.descriptor.id~=s.id or old.descriptor.token~=s.token
            or body and old.body~=body) then discover=true end
        if s.retired then
            finalPose(key,s,old,body);untrack(old);C.parts[key]=nil
        else
            C.finals[key]=nil
            local r=old
            if not r or newClock or r.descriptor.token~=s.token or r.descriptor.id~=s.id then untrack(r);r={};C.parts[key]=nil end
            local target,changed=Motion.target(r,s)
            if r~=old or changed then orderChanged=true end
            Motion.push(r,target,sampleTime);r.descriptor=s;r.received=now
            if r.body and r.body~=body then untrack(r) end
            r.body=body;rows[key]=r
        end
    end
    for key,r in pairs(previous) do if not rows[key] then untrack(r);discover=true;orderChanged=true end end
    if orderChanged then C.orderedRows=nil end
    C.rows=rows;if discover then C.host.discover() end
    for key in pairs(C.appearances) do if not snapshot.bodies[key] then C.appearances[key]=nil end end
    for key in pairs(C.finals) do if not snapshot.bodies[key] then C.finals[key]=nil end end
    if ackCount>0 then send(nil,'appearanceAck',{rows=acknowledgements}) end
    C.sequence=args.sequence;C.lastState=now;C.ready=args.ready==true;C.protocolMismatch=nil;C.serverFailure=nil
    drain()
end
local function receiveLoads(args)
    if not W.loadPage(args) or args.epoch~=C.epoch or args.sequence<=(C.loadSequence or -1) then return end
    if args.revision~=C.graph.revision then
        if args.revision>C.graph.revision and getTimestampMs()>=C.nextSync then sync() end
        return
    end
    local part=C.loadAssembly
    if part and args.sequence<part.sequence then return end
    if not part or args.sequence~=part.sequence then
        part={sequence=args.sequence,revision=args.revision,sampledAt=args.sampledAt,count=args.count,pages={},received=0,time=getTimestampMs()}
        C.loadAssembly=part
    end
    if part.count~=args.count or part.revision~=args.revision or part.sampledAt~=args.sampledAt then return end
    if not part.pages[args.page] then part.received=part.received+1 end
    part.pages[args.page]=args.loads
    if part.received~=part.count then return end
    local loads={}
    for i=1,part.count do for key,row in pairs(part.pages[i]) do
        if loads[key] or not C.index or not C.index.byVehicle[key] then C.loadAssembly=nil;return end
        loads[key]=row
    end end
    C.loads=loads;C.loadSequence=args.sequence;C.loadRevision=args.revision
    C.loadReceived=getTimestampMs();C.loadSampledAt=args.sampledAt;C.loadAssembly=nil
end
function C.receive(name,args)
    if type(args)~='table' then return end
    if name=='state' and W.integer(args.protocol) and args.protocol~=W.version then
        if C.protocolMismatch~=args.protocol then print('[CVP MP] Protocol mismatch: client='..W.version..', server='..args.protocol) end
        C.protocolMismatch=args.protocol;return
    end
    if args.protocol~=W.version or args.session~=C.session then return end
    if name=='loads' then receiveLoads(args);return end
    if name=='status' then
        if not W.session(args.epoch) or C.retiredEpochs[args.epoch] or not W.integer(args.sequence)
            or C.epoch==args.epoch and args.sequence<=C.sequence
            or (args.error~='backend' and args.error~='runtime') then return end
        C.ready=false
        C.serverFailure={time=getTimestampMs(),key=args.error=='backend' and 'IGUI_CVP_ServerBackendMissing' or 'IGUI_CVP_ServerNotReady'}
        return
    end
    if name=='state' or name=='motion' then
        local motion=name=='motion'
        if not (motion and W.motionPage(args) or not motion and W.page(args)) or C.retiredEpochs[args.epoch] or C.epoch==args.epoch and args.sequence<=C.sequence then return end
        if motion and (args.epoch~=C.epoch or args.revision~=C.graph.revision) then
            if (args.epoch~=C.epoch or args.revision>C.graph.revision) and getTimestampMs()>=C.nextSync then sync() end
            return
        end
        local part=C.assembly
        if part and part.epoch~=C.epoch and args.epoch==C.epoch then return end
        if part and part.epoch==args.epoch and args.sequence<part.sequence then return end
        -- Complete one full baseline per revision. Until its appearance is
        -- acknowledged the server may keep sending full snapshots every 100 ms;
        -- replacing unfinished pages each time can starve initial/recovery sync.
        if part and part.epoch==args.epoch and not part.motion and part.revision==args.revision
            and args.sequence>part.sequence then return end
        if not part or part.epoch~=args.epoch or part.sequence~=args.sequence then
            part={motion=motion,epoch=args.epoch,sequence=args.sequence,count=args.count,revision=args.revision,pages={},received=0,time=getTimestampMs(),ready=args.ready,sampledAt=args.sampledAt,frameSchema=args.frameSchema,intervalSeconds=args.intervalSeconds}
            C.assembly=part
        end
        if part.motion~=motion or part.count~=args.count or part.revision~=args.revision or part.ready~=args.ready or part.sampledAt~=args.sampledAt or part.frameSchema~=args.frameSchema or part.intervalSeconds~=args.intervalSeconds then return end
        if not part.pages[args.page] then part.received=part.received+1 end
        part.pages[args.page]=args
        local snapshot=part.received==part.count and W.assemble(part,motion and C.graph or nil)
        if snapshot then
            snapshot.motion=motion;C.assembly=nil;C.apply(snapshot,args)
        elseif part.received==part.count then
            C.assembly=nil;if getTimestampMs()>=C.nextSync then sync() end
        end
    elseif args.epoch~=C.epoch then return
    elseif name=='result' then
        if not W.integer(args.request) or not W.integer(args.sequence) or type(args.ok)~='boolean' then return end
        local pending=C.pending[args.request]
        if pending and pending.epoch==args.epoch and not pending.result then pending.result=args;drain() end
    elseif name=='body' then
        local row=W.key(args.key) and C.rows[args.key]
        if not row or row.descriptor.token~=args.token or row.descriptor.id~=args.id or not W.session(args.transfer)
            or not W.integer(args.count) or args.count<1 or args.count>W.maxParts
            or not W.integer(args.part) or args.part<1 or args.part>args.count
            or type(args.data)~='string' or #args.data>W.partBytes then return end
        local part=C.parts[args.key]
        if not part or part.transfer~=args.transfer then part={transfer=args.transfer,count=args.count,parts={},time=getTimestampMs()};C.parts[args.key]=part end
        if part.count~=args.count then return end
        part.parts[args.part]=args.data
        for i=1,part.count do if not part.parts[i] then return end end
        CVPNetwork.receive(args.id,table.concat(part.parts));C.parts[args.key]=nil
        local body=resolved(row.descriptor,true)
        if row.body~=body then untrack(row) end
        row.body=body;C.host.discover()
    end
end
local function serviceNetwork(now)
    local expired={};for id,pending in pairs(C.pending) do if now-pending.time>10000 then expired[#expired+1]=id end end
    for _,id in ipairs(expired) do local pending=C.pending[id];C.pending[id]=nil;send(pending.player,'cancelRequest',{request=id});pending.callback(false,nil,'IGUI_CVP_ResultUnknown') end
    for _,pending in pairs(C.pending) do
        if not pending.result and pending.epoch==C.epoch and pending.retries<3 and now>=pending.nextRetry
            and not C.connectionReason() then
            pending.retries=pending.retries+1;pending.nextRetry=now+2000
            send(pending.player,pending.cancelled and 'cancelRequest' or pending.name,pending.cancelled and {request=pending.payload.request} or pending.payload)
        end
    end
    if C.assembly and now-C.assembly.time>5000 then C.assembly=nil end
    if C.loadAssembly and now-C.loadAssembly.time>1000 then C.loadAssembly=nil end
    for key,part in pairs(C.parts) do if now-part.time>5000 then C.parts[key]=nil end end
    if (not C.epoch or now-C.lastState>=3000) and now>=C.nextSync then sync() end
end
local function applyLoads(now,dt)
    if not C.loadReceived or not C.ready then return end
    if SandboxVars.CorpseProxyLab and SandboxVars.CorpseProxyLab.VehicleDrag==false then return end
    local age=math.max(now-C.loadReceived,Motion.time(C.motionClock,now)-(C.loadSampledAt or 0))
    if age>=1000 then return end
    C.loadOwners=C.loadOwners or {};local applied={}
    for key,row in pairs(C.loads) do
        local v=C.index and C.index.byVehicle[key] and C.host.vehicle({key=key})
        if v and not applied[v] then
            applied[v]=true
            local owned=v:isLocalPhysicSim() and v:getNetPlayerId()==row.owner
            local previous=C.loadOwners[key]
            if not previous or row.ownerGeneration>previous.generation then
                previous={vehicle=v,owner=row.owner,generation=row.ownerGeneration};C.loadOwners[key]=previous
            elseif row.ownerGeneration==previous.generation and previous.vehicle~=v then
                -- A streamed replica changed. Block the cached sample once, not
                -- again every frame; the next fresh feedback may resume it.
                previous.vehicle=v;previous.blocked=C.loadSequence
            end
            if row.ownerGeneration==previous.generation then
                if not owned or previous.owner~=row.owner then previous.blocked=C.loadSequence
                elseif previous.blocked and C.loadSequence>previous.blocked then previous.blocked=nil end
                if owned and not previous.blocked then Load.apply(v,row.resistanceForceN,dt,age) end
            end
        end
    end
    for key in pairs(C.loadOwners) do if not C.loads[key] then C.loadOwners[key]=nil end end
end
local function updateBodies(now)
    local missing,discover
    local motionTime=Motion.time(C.motionClock,now)
    -- Parent order changes only with membership, parent or record identity. Keep
    -- live records, not cached poses: movement and body lookup still run each tick.
    if not C.orderedRows then C.orderedRows=Motion.ordered(C.rows);C.visualRevision=nil end
    if C.visualRevision~=C.graph.revision then
        Motion.bindJoints(C.rows,C.graph,C.index,C.host);C.visualRevision=C.graph.revision
    end
    Motion.begin(C.host,motionTime-Motion.delay)
    C.host.displayBodies={}
    for _,r in ipairs(C.orderedRows) do
        local body=resolved(r.descriptor)
        local pose=Motion.pose(r,motionTime)
        local changedBody=r.body~=body
        if r.body and r.body~=body then untrack(r) end
        r.body=body
        if Motion.present(r,pose,C.rows,C.host) and now>=C.nextSync then sync() end
        if body then
            local registered=C.host.bodies[r.descriptor.key]
            if changedBody or registered~=body and registered~=false then discover=true end
            if place(body,pose) then
                pose.body=body;C.host.displayBodies[r.id]=pose
                if r.tracked~=body then View.track(body);r.tracked=body end
            else untrack(r) end
        elseif not missing or (r.requested or 0)<(missing.requested or 0) then missing=r end
    end
    C.displayEndpoints=Motion.endpoints(C.endpointRows,motionTime,C.host.displayBodies,C.displayEndpoints)
    if CVPBodyPresentation then CVPBodyPresentation.update(C.orderedRows) end
    if discover then C.host.discover() end
    -- A missing chunk or failed replica must not monopolize the request slot.
    if missing and now>=C.nextBody then
        missing.requested=now;C.nextBody=now+1100
        send(nil,'body',{key=missing.descriptor.key,token=missing.descriptor.token})
    end
end
local lastTick=getTimestampMs()
function C.tick()
    C.host.discoverIfDue()
    local now=getTimestampMs();local dt=math.max(0,math.min(.1,(now-lastTick)/1000));lastTick=now
    C.loadClock=C.loadClock or {}
    local loadDt=Clock.advance(C.loadClock,dt,now,CVPVehicleMotion and CVPVehicleMotion.localTime())
    if C.loadClock.motionCorrection then loadDt=0;C.loadClock.motionCorrection=nil end
    C.actions:update()
    serviceNetwork(now)
    -- Network recovery above stays active even without any world presentation.
    if empty(C.graph.links) and empty(C.rows) and empty(C.loads) and empty(C.actions.jobs) then
        C.presentation:clear();return
    end
    C.host.players={}
    local players=getOnlinePlayers()
    for i=0,players:size()-1 do C.host.actor(players:get(i)) end
    for id=0,getNumActivePlayers()-1 do C.host.actor(getSpecificPlayer(id)) end
    if not CVPBodyPresentation or not CVPNetwork or not CVPWorldNative or not C.epoch or not C.ready or now-C.lastState>3000 then
        C.presentation:clear();for _,r in pairs(C.rows) do untrack(r) end;return
    end
    applyLoads(now,loadDt)
    updateBodies(now)
    local ok,success,why=pcall(C.presentation.update,C.presentation,C.graph,C.displayEndpoints,dt)
    local err=not ok and success or not success and why or nil
    if err and err~=C.renderError then print('[CVP MP] Presentation: '..tostring(err)) end
    C.renderError=err
end
Events.OnServerCommand.Add(function(module,name,args)
    if module~=W.module then return end
    local ok,err=pcall(C.receive,name,args);if not ok then print('[CVP MP] Receive: '..tostring(err)) end
end)
Events.OnTick.Add(function()
    local ok,err=pcall(C.tick)
    if not ok then
        if CVPBodyPresentation then CVPBodyPresentation.clear() end;C.host.visualOffsets=nil;C.host.visualJoints=nil;C.visualRevision=nil
        print('[CVP MP] Client: '..tostring(err))
    end
end)
Events.OnGameStart.Add(function()
    View.clear();if CVPBodyPresentation then CVPBodyPresentation.clear() end;C.host.visualOffsets=nil;C.host.visualJoints=nil;C.visualRevision=nil
    for _,r in pairs(C.rows) do r.tracked=nil end
    C.presentation:clear();sync()
end)
Events.OnFillWorldObjectContextMenu.Add(function(id,context,objects,test)
    if test then return end;local p=getSpecificPlayer(id);if not p or p:isDead() then return end
    local why=C.connectionReason()
    if why then require('CVP_Menu').reason(context:addOption(getText('IGUI_CVP_TowingMenu'),nil,nil),getText(why));return end
    C.host.discover();C.menu:fill(p,context,objects)
end)
