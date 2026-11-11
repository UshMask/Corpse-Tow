if not isServer() then return end
local P=require 'CVP_Protocol'
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Rope=require 'CVP_Rope'
local Load=require 'CVP_Load'
local Core=require 'CVP_Core'
local Connection=require 'CVP_Connection'
local Rewire=require 'CVP_Rewire'
local S={links={},byID={},terminal={},peers=setmetatable({},{__mode='k'}),sequence=0,
    epoch=tostring(getTimestampMs())..':'..tostring(ZombRand(1000000000))}
S.registry=Core.registry(S.links)
CVPMPServer=S
local function grid(x,y,z) return getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(z)) end
local lastError,lastErrorTime
local function report(err)
    err=tostring(err);local now=getTimestampMs()
    if err~=lastError or now-(lastErrorTime or 0)>=5000 then print('[CVP MP] '..err);lastError=err;lastErrorTime=now end
end
local function state(r,active)
    local b=r.body
    local ax,ay,az
    if r.vehicle and r.vehicle:getSquare() then ax,ay,az=Core.anchor(r.connection and r or {connection={a={object=r.vehicle}}}) end
    return {id=r.id,connection=Connection.copy(r.md.connection),
        source=r.parent and CVPNetwork.id(r.parent.body),parentConnection=r.md.parentConnection,
        sourceX=r.parent and (r.parent.attachLocalX or r.parent.footLocalX),
        sourceY=r.parent and (r.parent.attachLocalY or r.parent.footLocalY),
        active=active,x=b:getX(),y=b:getY(),z=b:getZ(),angle=b:getAngle(),
        vehicle=r.vehicle and r.vehicle:getId() or -1,vehicleKey=Core.vehicleKey(r.md),
        gearID=r.md.gearID,gearType=r.md.gearType,slot=r.md.slot,length=r.md.length,
        footX=r.attachLocalX or r.footLocalX or -0.65,footY=r.attachLocalY or r.footLocalY or 0,point=r.md.connection.b.point,
        anchorX=ax,anchorY=ay,anchorZ=az,blocked=r.blocked==true,
        mass=r.mass or 0,loadMass=r.chainLoadMass or r.loadMass or 0,taut=r.taut==true,owner=r.md.owner}
end
local function makeLink(b,v,md,parent)
    local id=CVPNetwork.id(b);if S.byID[id] then return S.byID[id] end
    local r=Core.link(b,v,World.gear(b,md),md,parent);r.id=id
    Core.register(S.registry,r);S.byID[id]=r;S.terminal[id]=nil
    return r
end
local function forget(r)
    if S.byID[r.id]==r then S.byID[r.id]=nil end
    if r.connection then Core.unregister(S.registry,r) end
end
local transfer
local function clear(r,recipient)
    local gear=r.gear or World.gear(r.body,r.md)
    local ok,err=Core.release(r.body,gear,recipient and recipient:getInventory(),transfer)
    if not ok then r.failed=true;r.taut=false;report('Equipment return pending: '..tostring(err));return false,err end
    Core.endTail(r)
    S.terminal[r.id]={row=state(r,false),expires=getTimestampMs()+300000}
    local count,oldest,expiry=0,nil,math.huge
    for id,t in pairs(S.terminal) do count=count+1;if t.expires<expiry then oldest=id;expiry=t.expires end end
    if count>256 then S.terminal[oldest]=nil end
    forget(r)
    return true
end
-- Move the existing item and replicate native container changes. Never manufacture a rope.
transfer=function(item,source,destination)
    local ok,err=Core.transfer(item,source,destination)
    if not ok then return false,err end
    sendRemoveItemFromContainer(source,item)
    sendAddItemToContainer(destination,item)
    return true
end
function S.reason(p,b,v,gear,finishAt,parent)
    if not World.towingEnabled() then return 'IGUI_CVP_TowingDisabled' end
    if not CVPNetwork or not CVPWorldNative or not CVPItemNative or not CVPEquipmentPersistence then return 'IGUI_CVP_ServerMissing' end
    if not World.towable(b) then return 'IGUI_CVP_NeedCorpse' end
    if not b:isZombie() and not World.playerBodiesAllowed() then return 'IGUI_CVP_PlayerBodiesDisabled' end
    if finishAt~=nil and finishAt~='body' and finishAt~='vehicle' then return 'IGUI_CVP_Approach' end
    if p:getVehicle() or (finishAt=='vehicle' and not Geometry.nearAnchor(p,v))
        or (finishAt~='vehicle' and not P.near(p,b,4)) then return 'IGUI_CVP_Approach' end
    if not b:getSquare() or b:getStaticMovingObjectIndex()<0 or b:isBeingGrappled() then return 'IGUI_CVP_Unavailable' end
    -- canReachTo only accepts adjacent tiles. A body-first sequence ends at
    -- the hitch; nearAnchor already validates reachability of that endpoint.
    if not p:getSquare() or finishAt~='vehicle' and not p:getSquare():canReachTo(b:getSquare()) then return 'IGUI_CVP_NoPath' end
    if World.data(b) or S.byID[CVPNetwork.id(b)] or World.foreignTowed(b) then return 'IGUI_CVP_AlreadyAttached' end
    if not v or not v:getSquare() then return 'IGUI_CVP_VehicleUnavailable' end
    local ax,ay,az
    if parent then ax,ay,az=Core.anchor({parent=parent}) else ax,ay,az=Geometry.anchor(v) end
    if math.floor(az)~=math.floor(b:getZ()) or (ax-b:getX())^2+(ay-b:getY())^2>64 then return 'IGUI_CVP_VehicleFar' end
    if math.abs(v:getCurrentSpeedKmHour())>1 then return 'IGUI_CVP_StopVehicle' end
    if not gear or not P.materials[gear:getFullType()] or P.item(p:getInventory(),gear:getID())~=gear then return 'IGUI_CVP_NeedGear' end
    if p:getPrimaryHandItem()==gear or p:getSecondaryHandItem()==gear then return 'IGUI_CVP_StowGear' end
    
end
function S.attach(p,b,v,gear,point,finishAt,source,sourceConnection)
    if point~=nil and point~='feet' and point~='neck' then return false,'IGUI_CVP_ActionFailed' end
    if sourceConnection and not source then return false,'IGUI_CVP_LetGo' end
    local parent=source and S.registry.byBody[source]
    if source and (not parent or parent.connection.id~=sourceConnection or parent.vehicle~=v
        or not Core.canFollow(parent) or not World.canDetach(p,parent.md)
        or not source:getSquare() or source:getStaticMovingObjectIndex()<0 or source:isBeingGrappled()) then
        return false,'IGUI_CVP_LetGo'
    end
    local reason=S.reason(p,b,v,gear,finishAt,parent);if reason then return false,reason end
    point=point or (parent and 'feet' or Geometry.nearestPoint(b,v))
    local used={};local count=0;local bodies=CVPNetwork.bodies()
    local key=World.vehicleKey(v)
    local observed,observeError=Core.observeVehicle(v)
    if not observed then report(observeError);return false,'IGUI_CVP_AttachFailed' end
    for i=0,bodies:size()-1 do local md=World.data(bodies:get(i))
        if World.valid(md) and Core.vehicleKey(md)==key then used[md.slot]=true;count=count+1 end
    end
    local slot=1;while used[slot] do slot=slot+1 end
    if parent and Connection.chainSize(v:getModData().CVPConnections or {},parent.connection.id)>=World.maxChain() then return false,'IGUI_CVP_VehicleLimit' end
    local md=parent and Core.childMetadata(parent,b,gear,slot,point) or Core.metadata(key,gear,slot,point,b);md.owner=p:getUsername()
    local fitted,fitError=pcall(Core.fitLength,b,v,gear,md,parent)
    if not fitted then report(fitError);return false,'IGUI_CVP_AttachFailed' end
    local ok,err=Core.attach(b,gear,md,function()
        return makeLink(b,v,md,parent)
    end,function()
        local r=S.byID[CVPNetwork.id(b)];if r then Core.endTail(r);forget(r) end
    end,transfer)
    if not ok then report(err);return false,'IGUI_CVP_AttachFailed' end
    return true,'IGUI_CVP_AttachedOne'
end
function S.detach(p,b,vehicle,connectionID)
    if not b or not P.near(p,b,vehicle and 18 or 4) or p:getVehicle() or not p:getSquare()
        or not b:getSquare() or not p:getSquare():canReachTo(b:getSquare()) then return false,'IGUI_CVP_Approach' end
    local md=World.data(b);if not World.valid(md) then return false,'IGUI_CVP_AlreadyDetached' end
    if connectionID~=nil and (not md.connection or connectionID~=md.connection.id) then return false,'IGUI_CVP_LetGo' end
    if not World.canDetach(p,md) then return false,'IGUI_CVP_OtherOwner' end
    if vehicle and (Core.vehicleKey(md)~=vehicle:getModData().CVPVehicleKey or not P.near(p,vehicle,4)
        or math.abs(vehicle:getCurrentSpeedKmHour())>1) then return false,'IGUI_CVP_StopVehicle' end
    local r=S.byID[CVPNetwork.id(b)]
    local rootVehicle=r and r.vehicle or Core.loadedVehicles()[Core.vehicleKey(md)]
    -- Dormant descendants use membership saved on the car. Do not release the
    -- root item until that membership can be ended with the rest of its tail.
    if not rootVehicle or not rootVehicle:getSquare() then return false,'IGUI_CVP_VehicleUnavailable' end
    if math.abs(rootVehicle:getCurrentSpeedKmHour())>1 then return false,'IGUI_CVP_StopVehicle' end
    r=r or {id=CVPNetwork.id(b),body=b,md=md,vehicle=rootVehicle}
    local ok,err=clear(r,p);if not ok then return false,'IGUI_CVP_ReleaseFailed' end
    local failed=false
    for i=#S.links,1,-1 do local tail=S.links[i]
        if Core.ended(tail) then
            if not clear(tail,p) then failed=true end
        end
    end
    if failed then return false,'IGUI_CVP_BulkPartial' end
    return true,'IGUI_CVP_Released'
end
function S.detachAll(p,v)
    if not v or not v:getSquare() or not P.near(p,v,4) or p:getVehicle() then return false,'IGUI_CVP_Approach' end
    if math.abs(v:getCurrentSpeedKmHour())>1 then return false,'IGUI_CVP_StopVehicle' end
    local key=v:getModData().CVPVehicleKey
    if not key then return false,'IGUI_CVP_AlreadyDetached' end
    local bodies=CVPNetwork.bodies();local done,failed=0,0
    for i=0,bodies:size()-1 do local b=bodies:get(i);local md=World.data(b)
        if World.valid(md) and Core.vehicleKey(md)==key then
            local ok=S.detach(p,b,v);if ok then done=done+1 else failed=failed+1 end
        end
    end
    if failed>0 then return false,'IGUI_CVP_BulkPartial' end
    return done>0,done>0 and 'IGUI_CVP_Released' or 'IGUI_CVP_AlreadyDetached'
end
function S.rewire(p,v,selection)
    if not World.towingEnabled() then return false,'IGUI_CVP_TowingDisabled' end
    if not v or type(selection)~='table' or #selection<2 or #selection>World.maxChain() or p:getVehicle() then return false,'IGUI_CVP_RewireLimit' end
    local order={};local seen={}
    for _,entry in ipairs(selection) do
        if type(entry)~='table' or not P.id(entry.id) then return false,'IGUI_CVP_LetGo' end
        local r=S.byID[entry.id]
        if not r or seen[r] or r.connection.id~=entry.connection then return false,'IGUI_CVP_LetGo' end
        seen[r]=true;order[#order+1]=r
    end
    if not P.near(p,order[#order].body,4) or not p:getSquare() or not order[#order].body:getSquare()
        or not p:getSquare():canReachTo(order[#order].body:getSquare()) then return false,'IGUI_CVP_Approach' end
    local ok,fresh=Rewire.apply(S.registry,v,order,p)
    if not ok then return false,fresh end
    for _,r in ipairs(fresh) do S.byID[r.id]=r end
    return true,'IGUI_CVP_AttachedOne'
end
local function peer(p)
    local t=S.peers[p]
    if not t then t={lastRequest=0,nextCommand=0,nextBootstrap=0};S.peers[p]=t end
    return t
end
local function snapshot()
    local rows={}
    for _,r in ipairs(S.links) do
        local ok,row=pcall(state,r,true)
        if ok then rows[#rows+1]=row else report(row) end
    end
    return rows
end
local function publish(p,states)
    local rows={};local x,y=p:getX(),p:getY()
    for _,s in ipairs(states or snapshot()) do
        if (x-s.x)^2+(y-s.y)^2<=P.radius^2 then rows[#rows+1]=s end
    end
    for _,t in pairs(S.terminal) do
        local s=t.row
        if (x-s.x)^2+(y-s.y)^2<=P.radius^2 then rows[#rows+1]=s end
    end
    sendServerCommand(p,P.module,'state',{protocol=P.version,epoch=S.epoch,sequence=S.sequence,rows=rows,bulkDetach=true,neckAttach=true,twoPointAttach=true,rewire=true})
end
local function command(module,name,p,args)
    if module~=P.module or not p or p:isDead() or type(args)~='table' or args.protocol~=P.version then return end
    if not CVPNetwork or not CVPWorldNative then return end
    local now=getTimestampMs();local t=peer(p)
    if name=='sync' then
        if now<(t.nextSync or 0) then return end;t.nextSync=now+1000;publish(p);return
    end
    if name=='body' then
        if now<t.nextBootstrap or not P.id(args.id) then return end
        t.nextBootstrap=now+1000
        local r=S.byID[args.id]
        if not r or P.distance(p,r.body)>P.radius or args.connectionID~=nil and args.connectionID~=r.connection.id then return end
        local payload=CVPNetwork.encode(r.body);local count=math.ceil(#payload/P.partBytes)
        if count>P.maxParts then report('corpse too large to replicate '..args.id);return end
        local transferID=tostring(now)..':'..args.id
        for part=1,count do sendServerCommand(p,P.module,'body',{
            protocol=P.version,epoch=S.epoch,id=args.id,connectionID=r.connection.id,transfer=transferID,part=part,count=count,
            data=payload:sub((part-1)*P.partBytes+1,part*P.partBytes)}) end
        return
    end
    if name~='attach' and name~='chain' and name~='detach' and name~='detachAll' and name~='rewire' then return end
    if not P.integer(args.request) or args.request<1 or args.request<=t.lastRequest or now<t.nextCommand then return end
    t.lastRequest=args.request;t.nextCommand=now+250
    local ok,reason=false,'IGUI_CVP_ActionFailed'
    if name=='rewire' and P.integer(args.vehicle) then ok,reason=S.rewire(p,getVehicleById(args.vehicle),args.selection)
    elseif name=='detachAll' and P.integer(args.vehicle) then ok,reason=S.detachAll(p,getVehicleById(args.vehicle))
    elseif P.id(args.id) then
        local b=CVPNetwork.find(args.id)
        if name=='detach' then ok,reason=S.detach(p,b,nil,args.connectionID)
        elseif (name=='attach' or name=='chain' and P.id(args.source) and type(args.sourceConnection)=='string')
            and P.integer(args.vehicle) and P.integer(args.gear) then
            ok,reason=S.attach(p,b,getVehicleById(args.vehicle),P.item(p:getInventory(),args.gear),args.point,args.finishAt,name=='chain' and CVPNetwork.find(args.source) or nil,args.sourceConnection)
        end
    end
    local attached=ok and (name=='attach' or name=='chain') and S.byID[args.id]
    sendServerCommand(p,P.module,'result',{connectionID=attached and attached.connection.id,protocol=P.version,epoch=S.epoch,request=args.request,ok=ok,message=reason})
end
local nextDiscovery,nextSend,lastTick=0,0,getTimestampMs()
local recoveredPlayers=setmetatable({},{__mode='k'})
function S.discover()
    local players=getOnlinePlayers()
    for i=0,players:size()-1 do local p=players:get(i)
        if not recoveredPlayers[p] then
            local ok,why=require('CVP_Equipment').recover(p)
            recoveredPlayers[p]=true
            if not ok then report('Equipment recovery pending: '..tostring(why)) end
        end
    end
    local cars=Core.loadedVehicles()
    local bodies=CVPNetwork.bodies()
    for i=0,bodies:size()-1 do local b=bodies:get(i);local md=World.data(b)
        if World.valid(md) and not S.byID[CVPNetwork.id(b)] then
            local status,gear,v,parent=Core.restore(b,md,cars,S.registry,transfer)
            if status=='ready' then
                local ok,err=pcall(makeLink,b,v,md,parent)
                if not ok then report(err) end -- Keep the equipment key available for retry.
            elseif status~='waiting' then clear({id=CVPNetwork.id(b),body=b,vehicle=v,md=md}) end
        end
    end
end
function S.tick()
    if not CVPNetwork or not CVPWorldNative then return end
    local now=getTimestampMs();local dt=math.max(0,math.min((now-lastTick)/1000,0.1));lastTick=now
    if now>=nextDiscovery then S.discover();nextDiscovery=now+1000 end
    Rope.separate(S.links)
    Core.prepareChains(S.registry,now,dt)
    local loads={}
    for i=#S.links,1,-1 do local r=S.links[i];local b=r.body
        local ok,err=pcall(function()
            if r.failed then return end
            if b:isBeingGrappled() or World.foreignTowed(b) then clear(r);return end
            if b:getSquare() and grid(r.x,r.y,r.z)==b:getSquare() and b:getStaticMovingObjectIndex()<0 then clear(r);return end
            if not b:getSquare() or grid(r.x,r.y,r.z)~=b:getSquare() or not r.vehicle:getSquare() then forget(r);return end
            if World.gear(b,r.md)~=r.gear then clear(r);return end
            if Core.ended(r) then clear(r);return end
            if r.chainRange then clear(r);return end
            if r.chainWaiting or r.parent and S.registry.byConnection[r.parent.connection.id]~=r.parent then r.taut=false;r.loadMass=0;return end
            if r.failed then return end
            if not World.towingEnabled() then r.taut=false;r.loadMass=0;return end
            Load.refresh(r,now)
            local ax,ay,az=Core.anchor(r)
            if not Core.inRange(r.x,r.y,r.z,ax,ay,az) then clear(r);return end
            ax,ay=Rope.networkAnchor(r,ax,ay,dt,r.vehicle:getCurrentSpeedKmHour())
            if r.chainTick~=now then Core.advance(r,ax,ay,az,dt) end
            if b:getAngle()~=r.angle then b:setForwardDirectionAngle(r.angle);b:invalidateCorpse() end
            local mass=r.chainLoadMass or Load.tension(r,Core.connected(r),dt)
                if mass>0 then loads[r.vehicle]=(loads[r.vehicle] or 0)+mass end
        end)
        if not ok then report(err);r.failed=true;r.taut=false end -- retain original body and gear; allow manual release
    end
    if not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.VehicleDrag~=false then
        for v,mass in pairs(loads) do if v:isLocalPhysicSim() then
            local ok,err=pcall(Load.apply,v,mass,dt);if not ok then report(err) end
        end end
    end
    for id,t in pairs(S.terminal) do if now>t.expires then S.terminal[id]=nil end end
    if now>=nextSend then
        S.sequence=S.sequence+1;nextSend=now+P.interval
        local players=getOnlinePlayers();local states=snapshot()
        for i=0,players:size()-1 do local p=players:get(i);if not p:isDead() then publish(p,states) end end
    end
end
Events.OnClientCommand.Add(function(...) local ok,err=pcall(command,...);if not ok then report(err) end end)
Events.OnTick.Add(function() local ok,err=pcall(S.tick);if not ok then report(err) end end)
