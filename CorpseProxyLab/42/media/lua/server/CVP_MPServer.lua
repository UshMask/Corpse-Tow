-- Authoritative graph transport. Clients can request actions, never positions/items.
if not isServer() then return end
local W=require 'CVP_LinkWire'
local G=require 'CVP_LinkGraph'
local Runtime=require 'CVP_LinkRuntime'
local Appearance=require 'CVP_Appearance'
local LoadWindow=require 'CVP_LoadWindow'
local S={schema=4,authority=Runtime.new(),peers=setmetatable({},{__mode='k'}),sequence=0,
    epoch=getRandomUUID(),known={},terminal={},loadWindow=LoadWindow.new(),loadOwners=setmetatable({},{__mode='k'})}
CVPMPServer=S
local function report(err)
    if err and err~=S.error then print('[CVP MP] '..tostring(err)) end;S.error=err
end
local function online()
    local rows={};local all=getOnlinePlayers()
    for i=0,all:size()-1 do rows[#rows+1]=all:get(i) end;return rows
end
local function same(a,b)
    if a==b then return true end
    if type(a)~=type(b) then return false end
    if type(a)~='table' then return false end
    for k,v in pairs(a) do if not same(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
local structureIndex,structure,connections,previousGraph
local recordSet,recordsByBody,pageOrder
local function captureEndpoint(ref,point,old)
    point=point or ref
    if old and old.kind==ref.kind and old.key==ref.key and old.point==ref.point and old.holder==ref.holder
        and old.x==point.x and old.y==point.y and old.z==point.z then return old end
    return {kind=ref.kind,key=ref.key,point=ref.point,holder=ref.holder,x=point.x,y=point.y,z=point.z}
end
local function captureGraph(live,index,frame)
    -- Only endpoint coordinates and held-rope length change without a new index.
    -- These tables belong to snapshots, never to the mutable authority graph.
    if structureIndex~=index then
        structureIndex=index;structure=G.copy(live);connections={};previousGraph=nil
        for key,edges in pairs(index.byBody) do
            local ids={};for _,edge in ipairs(edges) do ids[#ids+1]=edge.id end
            connections[key]=ids
        end
    end
    local graph={version=live.version,revision=live.revision,links={}}
    local unchanged=previousGraph and previousGraph.version==live.version and previousGraph.revision==live.revision
    for id,link in pairs(live.links) do
        local old=previousGraph and previousGraph.links[id]
        local ends=frame and frame.endpoints[id]
        local a=captureEndpoint(link.a,ends and ends.a,old and old.a)
        local b=captureEndpoint(link.b,ends and ends.b,old and old.b)
        if old and old.a==a and old.b==b and old.length==link.length then graph.links[id]=old
        else
            unchanged=false
            local row={};for k,v in pairs(structure.links[id]) do if k~='a' and k~='b' then row[k]=v end end
            row.a=a;row.b=b;row.length=link.length;graph.links[id]=row
        end
    end
    if unchanged then return previousGraph end
    previousGraph=graph;return graph
end
function S.capture()
    local runtime=S.authority;local live=runtime.service.graph or G.empty()
    local index=runtime.service.index or assert(G.index(live));local host=runtime.host
    local frame=runtime.simulationFrame
    if frame and frame.revision~=live.revision then frame=nil end
    local graph=captureGraph(live,index,frame)
    runtime.simulation:build(graph,index)
    if recordSet~=runtime.simulation.records then
        local records={}
        for _,r in pairs(runtime.simulation.records) do records[r.link[r.edge.side=='a' and 'b' or 'a'].key]=r end
        recordsByBody=records;recordSet=runtime.simulation.records
    end
    local records=recordsByBody
    local bodies={};local now=getTimestampMs();local vehicleSamples={}
    local function sourceSample(e)
        if e.kind~='vehicle' then return host.sample(e) end
        local key=e.key..':'..tostring(e.point);local row=vehicleSamples[key]
        if row==nil then row=host.sample(e) or false;vehicleSamples[key]=row end
        -- host.sample returns a fresh value; all rows in this snapshot only read it.
        if row then return row end
    end
    for key,edges in pairs(index.byBody) do
        local b=host.body({key=key})
        if b then
            local pose=frame and frame.bodies[key]
            if pose and pose.body~=b then pose=nil end -- Never apply an old object's pose to its replacement.
            local r=records[key];if r and r.body~=b then r=nil end
            local source
            if pose then source=pose.source
            elseif r then source=r.committedSource or sourceSample(graph.links[r.path[1].id][r.path[1].side]) end
            local row={key=key,id=CVPNetwork.id(b),x=pose and pose.x or b:getX(),y=pose and pose.y or b:getY(),
                z=pose and pose.z or b:getZ(),angle=pose and pose.angle or b:getAngle(),
                token=r and (r.link.id..':'..tostring(graph.links[r.link.id].revision)) or 'body:'..key,
                source=source,sourceSampledAt=(pose and pose.sourceSampledAt or not pose and r and r.committedAt) or nil,
                parent=pose and pose.parent or not pose and r and r.parent and r.parent.link[r.parent.edge.side=='a' and 'b' or 'a'].key or nil,
                vehicle=r and not r.horse and r.vehicle:getId() or nil,
                taut=pose and pose.taut==true or not pose and r and r.taut==true or false,
                corrected=pose and pose.corrected==true or not pose and r and r.corrected==true or false,
                blocked=pose and pose.blocked==true or not pose and r and r.blocked==true or false,connections=connections[key]}
            Appearance.fill(row,b,now)
            bodies[key]=row;S.known[key]=row;S.terminal[key]=nil
        end
    end
    for key,row in pairs(S.known) do if not index.byBody[key] then
        local final=G.copy(row);local body=host.body({key=key})
        if body then final.x=body:getX();final.y=body:getY();final.z=body:getZ();final.angle=body:getAngle() end
        final.retired=true;final.token='free:'..tostring(S.sequence)..':'..key
        if body then Appearance.fill(final,body,now,true) end
        final.source=nil;final.parent=nil;final.vehicle=nil;final.taut=false;final.blocked=false
        S.terminal[key]={row=final,expires=now+300000};S.known[key]=nil
    end end
    for key,t in pairs(S.terminal) do
        if now>=t.expires then S.terminal[key]=nil else bodies[key]=t.row end
    end
    local loads={}
    for key in pairs(index.byVehicle) do local v=host.vehicle({key=key});local forceN=v and runtime.loads and runtime.loads[v]
        if v then
            local owner=v.getNetPlayerId and v:getNetPlayerId() or -1
            local identity=S.loadOwners[v]
            if not identity or identity.owner~=owner then
                S.loadGeneration=(S.loadGeneration or 0)+1
                identity={owner=owner,generation=S.loadGeneration};S.loadOwners[v]=identity
            end
            loads[key]={vehicle=v:getId(),ownerGeneration=identity.generation,resistanceForceN=LoadWindow.force(S.loadWindow,v,forceN or 0),
            intervalSeconds=LoadWindow.interval(S.loadWindow,v,frame and frame.intervalSeconds or 0),
            owner=owner} end
    end
    return {graph=graph,index=index,bodies=bodies,loads=loads,obstacles=frame and frame.obstacles or G.copy(runtime.simulation.obstacles),sampledAt=frame and frame.sampledAt or now,frameSchema=1,intervalSeconds=frame and frame.intervalSeconds or 0}
end
local function samePages(a,b)
    if not b or #a~=#b then return false end
    for i,page in ipairs(a) do
        for _,field in ipairs({'links','bodies','loads','obstacles'}) do
            if not same(page[field],b[i][field]) then return false end
        end
    end
    return true
end
-- Loads have their own freshness and assembly; a missing body page cannot hold
-- vehicle feedback hostage. Full snapshots still carry loads for recovery.
local function publishLoads(p,peer,snapshot,pages)
    local rows={};local count=0;local batches={}
    for _,page in ipairs(pages or {}) do for key in pairs(page.loads) do
        local row=snapshot.loads[key]
        if row then
            rows[key]=row;count=count+1
            if count==W.pageSize*2 then batches[#batches+1]=rows;rows={};count=0 end
        end
    end end
    -- An empty visible set has no feedback to refresh. Send one empty page
    -- when the last visible load disappears so the client can clear its cache.
    local hasLoads=count>0 or #batches>0
    if not hasLoads and not peer.sentLoads then return end
    peer.sentLoads=hasLoads
    if count>0 or #batches==0 then batches[#batches+1]=rows end
    for i,loads in ipairs(batches) do
        sendServerCommand(p,W.module,'loads',{protocol=W.version,epoch=S.epoch,session=peer.session,
            sequence=S.sequence,revision=snapshot.graph.revision,sampledAt=snapshot.sampledAt,
            page=i,count=#batches,loads=loads})
    end
end
local function motionCompatible(pages,old,peer,revision)
    if not old or #pages~=#old or peer.fullRevision~=revision then return false end
    for i,page in ipairs(pages) do
        local previous=old[i]
        if #page.links~=#previous.links or #page.bodies~=#previous.bodies then return false end
        for j,link in ipairs(page.links) do local before=previous.links[j]
            if link.id~=before.id or link.revision~=before.revision then return false end
        end
        for j,row in ipairs(page.bodies) do local before=previous.bodies[j]
            if row.key~=before.key or row.id~=before.id or row.token~=before.token or row.retired~=before.retired
                or not peer.appearanceAck or peer.appearanceAck[row.key]~=row.appearanceRevision then return false end
        end
    end
    return true
end
function S.publish(p,snapshot,onlyChanged)
    local peer=S.peers[p];if not peer or not peer.session then return end
    if not S.authority.started or S.error then
        sendServerCommand(p,W.module,'status',{protocol=W.version,epoch=S.epoch,session=peer.session,sequence=S.sequence,
            error=S.error=='skeleton graph backend unavailable' and 'backend' or 'runtime'})
        return
    end
    snapshot=snapshot or S.capture()
    if not snapshot.pageOrder then
        pageOrder=W.pageOrder(snapshot.graph,snapshot.bodies,pageOrder)
        snapshot.pageOrder=pageOrder
    end
    local pages=W.pages(snapshot.graph,snapshot.bodies,snapshot.loads,snapshot.index,p,snapshot.obstacles,snapshot.pageOrder)
    local now=getTimestampMs();local ready=S.authority.started==true and not S.error
    publishLoads(p,peer,snapshot,pages)
    local motion=onlyChanged and motionCompatible(pages,peer.visiblePages,peer,snapshot.graph.revision)
    if onlyChanged and peer.visibleReady==ready and now<(peer.heartbeat or 0) and samePages(pages,peer.visiblePages) then return end
    peer.visiblePages=pages;peer.visibleReady=ready;peer.heartbeat=now+1000
    local offered={}
    for _,source in ipairs(pages) do
        -- Keep the comparison snapshot intact when adding wire metadata or omitting appearance.
        local page={};for key,value in pairs(source) do page[key]=value end;page.bodies={}
        for i,row in ipairs(source.bodies) do
            local outgoing=row
            if peer.appearanceAck and peer.appearanceAck[row.key]==row.appearanceRevision then
                snapshot.omittedBodies=snapshot.omittedBodies or {}
                outgoing=snapshot.omittedBodies[row.key]
                if not outgoing then
                    outgoing={};for key,value in pairs(row) do
                        if key~='cosmetic' and key~='clothing' then outgoing[key]=value end
                    end
                    outgoing.appearanceOmitted=true;snapshot.omittedBodies[row.key]=outgoing
                end
            end
            offered[row.key]=row.appearanceRevision;page.bodies[i]=outgoing
        end
        if motion then
            page.geometry={};page.links={};page.loads={}
            for i,link in ipairs(source.links) do
                page.geometry[i]={id=link.id,revision=link.revision,length=link.length,a=link.a,b=link.b}
            end
        end
        page.protocol=W.version;page.epoch=S.epoch;page.session=peer.session;page.sequence=S.sequence
        page.sampledAt=snapshot.sampledAt;page.frameSchema=snapshot.frameSchema;page.intervalSeconds=snapshot.intervalSeconds
        page.ready=S.authority.started==true and not S.error
        sendServerCommand(p,W.module,motion and 'motion' or 'state',page)
    end
    if not motion then peer.fullRevision=snapshot.graph.revision end
    peer.appearanceOffered=offered
    for key in pairs(peer.appearanceAck or {}) do if not offered[key] then peer.appearanceAck[key]=nil end end
end
local function sendResult(p,peer,request,result)
    result.protocol=W.version;result.epoch=S.epoch;result.session=peer.session;result.request=request
    sendServerCommand(p,W.module,'result',result)
end
function S.command(module,name,p,args)
    if module~=W.module or not p or type(args)~='table' then return end
    if args.protocol~=W.version then
        if name=='sync' then sendServerCommand(p,W.module,'state',{protocol=W.version}) end
        return
    end
    if not W.session(args.session) then return end
    local now=getTimestampMs();local peer=S.peers[p]
    if not peer then peer={retired={},tokens=8,time=now,results={},lastRequest=0};S.peers[p]=peer end
    if name=='sync' then
        if S.authority.saveJob then return end
        if peer.retired[args.session] then return end
        if peer.session~=args.session then
            if now<(peer.nextSession or 0) then return end
            peer.nextSession=now+1000
            if peer.session then
                peer.retired[peer.session]=true;peer.history=peer.history or {};peer.history[#peer.history+1]=peer.session
                if #peer.history>64 then peer.retired[table.remove(peer.history,1)]=nil end
            end
            for _,job in pairs(peer.requestJobs or {}) do S.authority:cancel(job) end
            peer.pendingRequests={};peer.requestJobs={}
            peer.session=args.session;peer.results={};peer.lastRequest=0;peer.nextSync=0
            peer.appearanceAck={};peer.appearanceOffered={}
            peer.visiblePages=nil;peer.visibleReady=nil
            local ok,err=S.authority:start()
            if ok then ok,err=S.authority.service:disconnect(p:getUsername()) end
            if not ok then report(err) end
        end
        if now<(peer.nextSync or 0) then return end;peer.nextSync=now+1000
        S.sequence=S.sequence+1;S.publish(p);return
    end
    if peer.session~=args.session or args.epoch~=S.epoch then return end
    if name=='cancelRequest' then
        if W.integer(args.request) and peer.requestJobs then S.authority:cancel(peer.requestJobs[args.request]) end
        return
    end
    if name=='appearanceMissing' then
        if W.key(args.key) and peer.appearanceAck then peer.appearanceAck[args.key]=nil;peer.snapshotVersion=nil;peer.visiblePages=nil end
        return
    end
    if name=='appearanceAck' then
        if type(args.rows)~='table' then return end
        local count=0
        for key,revision in pairs(args.rows) do
            count=count+1;if count>64 then return end
            if not W.key(key) or not W.integer(revision) then return end
        end
        peer.appearanceAck=peer.appearanceAck or {}
        for key,revision in pairs(args.rows) do
            if peer.appearanceOffered and peer.appearanceOffered[key]==revision then peer.appearanceAck[key]=revision end
        end
        return
    end
    if name=='body' then
        if now<(peer.nextBody or 0) or not W.key(args.key) or not W.key(args.token) then return end
        peer.nextBody=now+1000
        if not S.authority.service.index or not S.authority.service.index.byBody[args.key] then return end
        local snapshot=S.capture();local row=snapshot.bodies[args.key]
        local body=S.authority.host.body({key=args.key})
        if not row or row.retired or row.token~=args.token or not body or not W.near(p,row) then return end
        local payload=CVPNetwork.encode(body);local count=math.ceil(#payload/W.partBytes)
        if count<1 or count>W.maxParts then return end
        local transfer=getRandomUUID()
        for part=1,count do sendServerCommand(p,W.module,'body',{protocol=W.version,epoch=S.epoch,session=peer.session,
            key=args.key,id=row.id,token=row.token,transfer=transfer,part=part,count=count,
            data=payload:sub((part-1)*W.partBytes+1,part*W.partBytes)}) end
        return
    end
    if p:isDead() or not W.integer(args.request) or args.request<1 then return end
    if peer.results[args.request] then
        S.sequence=S.sequence+1;S.publish(p)
        local result=G.copy(peer.results[args.request]);result.sequence=S.sequence
        sendResult(p,peer,args.request,result);return
    end
    if peer.pendingRequests and peer.pendingRequests[args.request] then return end
    if args.request<=peer.lastRequest then
        sendResult(p,peer,args.request,{ok=false,reason='stale request',sequence=S.sequence});return
    end
    peer.tokens=math.min(8,peer.tokens+math.max(0,now-peer.time)*.02);peer.time=now;peer.lastRequest=args.request
    local session=peer.session
    local function reply(ok,result,reason)
        if peer.session~=session then return end
        if peer.pendingRequests then peer.pendingRequests[args.request]=nil end
        if peer.requestJobs then peer.requestJobs[args.request]=nil end
        S.sequence=S.sequence+1
        local answer={ok=ok==true,result=result,reason=reason,sequence=S.sequence}
        peer.results[args.request]=G.copy(answer)
        for id in pairs(peer.results) do if id<peer.lastRequest-63 then peer.results[id]=nil end end
        S.publish(p)
        sendResult(p,peer,args.request,answer)
    end
    if peer.tokens<1 then reply(false,nil,'request rate exceeded')
    elseif not W.request(name,args.args) then reply(false,nil,'invalid command')
    elseif S.error then reply(false,nil,'authority unavailable')
    else
        peer.tokens=peer.tokens-1;peer.pendingRequests=peer.pendingRequests or {};peer.pendingRequests[args.request]=true
        local job=S.authority:submit(p,name,args.args,reply)
        if job and not job.done then
            peer.requestJobs=peer.requestJobs or {};peer.requestJobs[args.request]=job
        end
    end
end
local lastTick,nextSend=getTimestampMs(),0
local previousSnapshot,previousReady,snapshotVersion=nil,nil,0
function S.tick()
    local now=getTimestampMs();local dt=math.max(0,(now-lastTick)/1000);lastTick=now
    -- Runtime owns the limit and must see long gaps to mark recovery.
    local players=online();local ok,err=S.authority:tick(players,dt);report(not ok and err or nil)
    local graph=S.authority.service.graph
    LoadWindow.add(S.loadWindow,ok and S.authority.loads or {},S.authority.loadElapsed or 0,graph and graph.revision,ok)
    if now>=nextSend then
        nextSend=now+W.interval;S.sequence=S.sequence+1
        if not S.authority.started or S.error then
            for _,p in ipairs(players) do local peer=S.peers[p]
                if peer and now>=(peer.heartbeat or 0) then S.publish(p);peer.heartbeat=now+1000 end
            end
            return
        end
        local subscribed=false
        for _,p in ipairs(players) do local peer=S.peers[p]
            if peer and peer.session then subscribed=true;break end
        end
        if not subscribed then previousSnapshot=nil;LoadWindow.clear(S.loadWindow);return end
        local snapshot=S.capture();LoadWindow.clear(S.loadWindow)
        local ready=S.authority.started==true and not S.error
        if ready~=previousReady or not previousSnapshot or not same(snapshot.graph,previousSnapshot.graph)
            or not same(snapshot.bodies,previousSnapshot.bodies) or not same(snapshot.loads,previousSnapshot.loads)
            or not same(snapshot.obstacles,previousSnapshot.obstacles) then snapshotVersion=snapshotVersion+1 end
        previousSnapshot=snapshot;previousReady=ready
        for _,p in ipairs(players) do local peer=S.peers[p]
            if peer and (peer.snapshotVersion~=snapshotVersion or peer.sentSession~=peer.session
                or peer.x~=p:getX() or peer.y~=p:getY() or peer.z~=p:getZ() or now>=(peer.heartbeat or 0)) then
                S.publish(p,snapshot,true)
                peer.snapshotVersion=snapshotVersion;peer.sentSession=peer.session
                peer.x=p:getX();peer.y=p:getY();peer.z=p:getZ()
            elseif peer and peer.session then publishLoads(p,peer,snapshot,peer.visiblePages) end
        end
    end
end
Events.OnClientCommand.Add(function(...) local ok,err=pcall(S.command,...);if not ok then report(err) end end)
Events.OnCVPVehicleRemoved.Add(function(vehicle) S.authority:vehicleRemoved(vehicle) end)
Events.OnTick.Add(function() local ok,err=pcall(S.tick);if not ok then report(err) end end)
Events.OnSave.Add(function() if S.authority.started then local ok,err=S.authority:save();if not ok then report(err) end end end)
