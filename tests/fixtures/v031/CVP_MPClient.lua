if not isClient() then return end
local P=require 'CVP_Protocol'
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Rope=require 'CVP_Rope'
local Load=require 'CVP_Load'
local View=require 'CVP_Viewpoint'
local Motion=require 'CVP_Motion'
local AttachAction=require 'CVP_AttachAction'
local Tie=require 'CVP_TieSequence'
local Batch=require 'CVP_Batch'
local Menu=require 'CVP_Menu'
local Audio=require 'CVP_Audio'
local Connection=require 'CVP_Connection'
local Rewire=require 'CVP_Rewire'
local RewireAction=require 'CVP_RewireAction'
local C={links={},parts={},pending={},retiredEpochs={},mirrors=setmetatable({},{__mode='k'}),sequence=-1,request=0,nextBody=0,lastState=0}
CVPMPClient=C
local started=getTimestampMs()
-- Missing capability is not proof that the server is outdated.
function C.connectionReason(feature)
    if not CVPNetwork or not CVPWorldNative then return 'IGUI_CVP_NativeMissing' end
    if C.protocolMismatch then return 'IGUI_CVP_ProtocolMismatch' end
    if not C.epoch then
        return getTimestampMs()-started<10000 and 'IGUI_CVP_SyncWaiting' or 'IGUI_CVP_ServerUnavailable'
    end
    if getTimestampMs()-C.lastState>10000 then return 'IGUI_CVP_SyncLost' end
    if feature and not C[feature] then return 'IGUI_CVP_ServerUpdateRequired' end
end
local function vehicleName(v)
    local name=v:getScript():getName()
    return (getTextOrNull and getTextOrNull('IGUI_VehicleName'..name)) or name
end
local function send(name,args,p)
    args.protocol=P.version;sendClientCommand(p or getPlayer(),P.module,name,args)
end
function C.requestAction(name,p,b,v,gear,point,after,finishAt,connectionID,source,sourceConnection)
    if (name=='attach' or name=='chain' or name=='rewire') and not World.towingEnabled() then
        p:Say(getText('IGUI_CVP_TowingDisabled'));if after then after(false,nil,'IGUI_CVP_TowingDisabled') end;return
    end
    local unavailable=C.connectionReason()
    if unavailable then
        p:Say(getText(unavailable))
        if after then after(false,nil,unavailable) end
        return
    end
    C.request=C.request+1
    if after then C.pending[C.request]={fn=after,time=getTimestampMs(),epoch=C.epoch} end
    send(name,{request=C.request,id=CVPNetwork.id(b),connectionID=connectionID,
        source=source and CVPNetwork.id(source),sourceConnection=sourceConnection,
        vehicle=v and v:getId(),gear=gear and gear:getID(),point=point,finishAt=finishAt},p)
end
function C.queueChain(p,b,parent,gear,after)
    local captured=parent.target.connection.id
    local source=parent.body;local v=getVehicleById(parent.target.vehicle)
    local function valid()
        if not World.towingEnabled() then return 'IGUI_CVP_TowingDisabled' end
        local current=C.links[CVPNetwork.id(source)]
        if not current or current.target.connection.id~=captured or World.data(b)
            or not World.canDetach(p,current.target) or not v or not gear
            or P.item(p:getInventory(),gear:getID())~=gear or b:isBeingGrappled() or source:isBeingGrappled()
            or math.floor(b:getZ())~=math.floor(source:getZ()) or P.distance(b,source)>8 then return 'changed' end
        for _,r in pairs(C.links) do if r.target.parentConnection==captured then return 'occupied' end end
    end
    if valid() then return end
    return Tie.chain(p,b,source,v,gear,parent.target.point,'feet',valid,function(done)
        C.requestAction('chain',p,b,v,gear,'feet',done,'body',nil,source,captured)
    end,after)
end
function C.queueAction(name,p,b,v,gear,point,after,approaching,mode)
    local unavailable=C.connectionReason()
    if unavailable then p:Say(getText(unavailable));if after then after(false,nil,unavailable) end;return end
    local id=CVPNetwork and CVPNetwork.id(b);if not id then return end
    -- Preview the automatic endpoint for facing; the server selects it on commit.
    local automatic=point==nil
    if name=='attach' and not point and v then point=C.neckAttach and Geometry.nearestPoint(b,v) or 'feet' end
    if name=='attach' and point=='neck' and not C.neckAttach then p:Say(getText('IGUI_CVP_ServerUpdateRequired'));return end
    local r=C.links[id]
    local md=(r and r.target) or World.data(b)
    if name=='detach' then
        if not md then return end
        v=type(md.vehicle)=='number' and getVehicleById(md.vehicle) or nil
        gear=World.gear(b,World.data(b))
        point=md.connection.b.point
    end
    local function check(who,body,vehicle,item,approach)
        if name~='detach' and not World.towingEnabled() then return 'IGUI_CVP_TowingDisabled' end
        if who:isDead() or who:getVehicle() or not P.near(who,body,approach and 24 or 4) or not body:getSquare() then return 'IGUI_CVP_NoPath' end
        if v and (not v:getSquare() or math.abs(v:getCurrentSpeedKmHour())>1) then return 'IGUI_CVP_StopVehicle' end
        local current=C.links[id];local data=(current and current.target) or World.data(body)
        if name=='detach' then
            if not data or data.gearID~=md.gearID or data.vehicle~=md.vehicle
                or not Connection.matches(md.connection,data.connection) or not World.canDetach(who,data) then return 'IGUI_CVP_LetGo' end
        else
            if data or not v or not gear or P.item(who:getInventory(),gear:getID())~=gear then return 'IGUI_CVP_NeedGear' end
            local ax,ay,az=Geometry.anchor(v)
            if math.floor(az)~=math.floor(body:getZ()) or (ax-body:getX())^2+(ay-body:getY())^2>64 then return 'IGUI_CVP_ParkNearby' end
        end
    end
    local reason=check(p,b,v,gear,approaching);if reason then p:Say(getText(reason));return end
    if name=='attach' then
        if not C.twoPointAttach then p:Say(getText('IGUI_CVP_ServerUpdateRequired'));return end
        return Tie.start(p,b,v,gear,point,check,function(endpoint,done)
            C.requestAction(name,p,b,v,gear,not automatic and point or nil,done,endpoint)
        end,after,mode)
    end
    if not luautils.walkAdj(p,b:getSquare()) then p:Say(getText('IGUI_CVP_NoPath'));return end
    ISTimedActionQueue.add(AttachAction:new(p,b,v,gear,check,function()
        C.requestAction(name,p,b,v,gear,not automatic and point or nil,after,nil,md.connection and md.connection.id)
    end,name=='detach',point,after and function(ok) if not ok then after(false) end end))
    return true
end
function C.requestDetachAll(p,v)
    if not C.bulkDetach then return end
    local rows={};local selected={};local ancestry={}
    for _,r in pairs(C.links) do
        if r.target.connection then ancestry[r.target.connection.id]=r.target.parentConnection end
        if r.body and r.target.vehicle==v:getId() and World.canDetach(p,r.target) then
            rows[#rows+1]={body=r.body,gearID=r.target.gearID,connection=r.target.connection}
            if r.target.connection then selected[r.target.connection.id]=true end
        end
    end
    -- The server releases descendants with their ancestor. Do not queue stale
    -- child requests while waiting for the next state broadcast after the ACK.
    local independent={}
    for _,r in ipairs(rows) do
        local parent=r.connection and ancestry[r.connection.id];local covered=false
        local seen={}
        while parent and not seen[parent] do
            seen[parent]=true
            if selected[parent] then covered=true;break end
            parent=ancestry[parent]
        end
        if not covered then independent[#independent+1]=r end
    end
    rows=independent
    Batch.release(p,v,rows,function(r,after)
        local current=C.links[CVPNetwork.id(r.body)]
        if not current and not World.data(r.body) then after(true);return true end
        if not current or current.target.vehicle~=v:getId() or current.target.gearID~=r.gearID
            or not Connection.matches(r.connection,current.target.connection) then return end
        return C.queueAction('detach',p,r.body,v,nil,nil,after,true)
    end)
end
local function untrack(id)
    local r=C.links[id];if r and r.body then Audio.stop(r.body);View.untrack(r.body) end
    C.links[id]=nil;C.parts[id]=nil
end
local function grid(s) return getCell():getGridSquare(math.floor(s.x),math.floor(s.y),math.floor(s.z)) end
local function place(b,s)
    local sq=grid(s);if not sq or b:getStaticMovingObjectIndex()<0 or b:isBeingGrappled() or World.foreignTowed(b) then return false end
    World.move(b,s.x,s.y,s.z,sq)
    if b:getAngle()~=s.angle then b:setForwardDirectionAngle(s.angle);b:invalidateCorpse() end
    return true
end
function C.receive(name,args)
    if type(args)=='table' and name=='state' and P.integer(args.protocol) and args.protocol~=P.version then
        if C.protocolMismatch~=args.protocol then
            print('[CVP MP client] Protocol mismatch: client='..P.version..', server='..args.protocol)
        end
        C.protocolMismatch=args.protocol;return
    end
    if not CVPNetwork or type(args)~='table' or args.protocol~=P.version then return end
    if name=='state' then
        if type(args.epoch)~='string' or not P.integer(args.sequence) or type(args.rows)~='table' then return end
        for _,s in ipairs(args.rows) do if not P.row(s) then return end end
        if C.retiredEpochs[args.epoch] then return end
        if C.epoch~=args.epoch then
            local previous=C.epoch
            if previous then C.retiredEpochs[previous]=true end
            -- Only discard metadata installed by this client session. Native
            -- chunk data may replace it while a dormant body is untracked.
            for body,md in pairs(C.mirrors) do
                if body:getModData().CVPTether==md then body:getModData().CVPTether=nil end
            end
            C.mirrors=setmetatable({},{__mode='k'})
            for id in pairs(C.links) do untrack(id) end
            C.epoch=args.epoch;C.sequence=-1;C.parts={}
            if previous then
                local pending=C.pending;C.pending={}
                for _,entry in pairs(pending) do entry.fn(false,nil,'IGUI_CVP_QueueStopped') end
            end
        end
        if args.sequence<=C.sequence then return end
        C.protocolMismatch=nil
        C.sequence=args.sequence;C.lastState=getTimestampMs();C.bulkDetach=args.bulkDetach==true;C.neckAttach=args.neckAttach==true;C.twoPointAttach=args.twoPointAttach==true;C.rewire=args.rewire==true
        local seen={}
        for _,s in ipairs(args.rows) do
            if s.active then
                local r=C.links[s.id]
                if r and not Connection.matches(r.target.connection,s.connection) then untrack(s.id);r=nil end
                r=r or {id=s.id}
                Motion.push(r,s,C.lastState)
                r.target=s;r.received=C.lastState;C.links[s.id]=r;seen[s.id]=true
            else
                local r=C.links[s.id]
                if r and not Connection.matches(s.connection,r.target.connection) then
                    seen[s.id]=true -- a terminal for an earlier connection cannot release its replacement
                else
                    local b=CVPNetwork.find(s.id)
                    if b then
                        -- A terminal packet can arrive after timeout/range untracking.
                        -- Clear its saved marker, but do not replay old positions on a free body.
                        if r then place(b,s) end
                        local md=World.data(b)
                        if md and md.gearID==s.gearID
                            and (md.connection.a.kind=='vehicle' and md.connection.a.key or md.rootVehicle)==s.vehicleKey
                            and Connection.matches(s.connection,md.connection) then
                            b:getModData().CVPTether=nil
                        end
                    end
                    untrack(s.id)
                end
            end
        end
        for id in pairs(C.links) do if not seen[id] then untrack(id) end end
    elseif name=='body' then
        if args.epoch~=C.epoch or not P.id(args.id) or not C.links[args.id]
            or args.connectionID~=C.links[args.id].target.connection.id
            or type(args.transfer)~='string' or #args.transfer>80
            or not P.integer(args.count) or args.count<1 or args.count>P.maxParts
            or not P.integer(args.part) or args.part<1 or args.part>args.count
            or type(args.data)~='string' or #args.data>P.partBytes then return end
        local t=C.parts[args.id]
        if not t or t.transfer~=args.transfer then t={transfer=args.transfer,count=args.count,parts={},time=getTimestampMs()};C.parts[args.id]=t end
        if t.count~=args.count then return end
        t.parts[args.part]=args.data
        for i=1,t.count do if not t.parts[i] then return end end
        local b=CVPNetwork.receive(args.id,table.concat(t.parts))
        C.parts[args.id]=nil
        if b then C.links[args.id].body=b end
    elseif name=='result' then
        if args.epoch~=C.epoch then return end
        if type(args.message)=='string' and #args.message<300 then
            local message
            if args.message:match('^IGUI_CVP_') then message=getText(args.message)
            else
                print('[CVP MP result] '..args.message)
                message=getText(args.ok and 'IGUI_CVP_ActionDone' or 'IGUI_CVP_ActionFailed')
            end
            local p=getPlayer();if p then p:Say(message) end
            C.lastResult=args
        end
        local pending=C.pending[args.request]
        if pending and pending.epoch==args.epoch then C.pending[args.request]=nil;pending.fn(args.ok==true,args.connectionID,args.ok~=true and (type(args.message)=='string' and args.message:match('^IGUI_CVP_') and args.message or 'IGUI_CVP_ActionFailed') or nil) end
    end
end
local last=getTimestampMs()
function C.tick()
    Batch.update()
    if not CVPNetwork then return end
    for id,pending in pairs(C.pending) do
        if getTimestampMs()-pending.time>10000 then C.pending[id]=nil;pending.fn(false,nil,'IGUI_CVP_QueueTimeout') end
    end
    local now=getTimestampMs();local dt=math.max(0,math.min((now-last)/1000,0.1));last=now
    local loads={}
    for _,r in ipairs(Motion.ordered(C.links)) do
        local id=r.id
        local s=r.target
        if now-r.received>3000 then untrack(id)
        elseif grid(s) then
            local b=CVPNetwork.find(id);local v=getVehicleById(s.vehicle)
            if b and v and v:getSquare() then
                if r.body and r.body~=b then View.untrack(r.body) end
                r.body=b;r.vehicle=v;r.length=s.length;r.slot=s.slot;r.angle=b:getAngle()
                r.footLocalX=s.footX;r.footLocalY=s.footY
                -- Rendering uses server material metadata, never creates an inventory item.
                r.gear={getFullType=function() return s.gearType end}
                local ax,ay,az=Geometry.anchor(v)
                local source=s.source and CVPNetwork.find(s.source)
                if s.connection.a.kind=='body' then
                    ax,ay,az=s.anchorX,s.anchorY,s.z;r.anchorHeight=Rope.floorHeight
                    if source then
                        local c,sn=math.cos(source:getAngle()),math.sin(source:getAngle())
                        ax=source:getX()+c*s.sourceX-sn*s.sourceY
                        ay=source:getY()+sn*s.sourceX+c*s.sourceY;az=source:getZ()
                    end
                else r.anchorHeight=nil end
                local pose=Motion.pose(r,now,ax,ay,az)
                if place(b,pose) then
                    r.initialized=true;r.x=b:getX();r.y=b:getY();r.z=b:getZ();r.angle=b:getAngle()
                    b:getModData().CVPTether={version=2,gearID=s.gearID,
                        gearType=s.gearType,length=s.length,slot=s.slot,owner=s.owner,parentConnection=s.parentConnection,
                        rootVehicle=s.connection.a.kind=='body' and s.vehicleKey or nil,
                        connection=Connection.copy(s.connection)}
                    C.mirrors[b]=b:getModData().CVPTether
                    if s.connection then
                        b:getModData().CVPBodyKey=s.connection.b.key
                        r.connection=Connection.bind(s.connection,b,source or v)
                        r.sourceBody=source;r.sourceX=s.sourceX;r.sourceY=s.sourceY
                    end
                    Rope.shape(r,ax,ay,az,dt);View.track(b);View.rope(r)
                    local mass=s.loadMass~=nil and s.loadMass or s.mass
                    if s.taut and P.finite(mass) and mass>0 then loads[v]=(loads[v] or 0)+mass end
                end
            elseif not b and now>=C.nextBody then
                C.nextBody=now+1100;send('body',{id=id,connectionID=s.connection.id})
            elseif r.body then View.untrack(r.body) end
        elseif r.body then View.untrack(r.body) end
    end
    Audio.update(C.links)
    for id,t in pairs(C.parts) do if now-t.time>5000 then C.parts[id]=nil end end
    if not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.VehicleDrag~=false then
        -- Exactly the native vehicle physics authority applies resistance, including driver handoff.
        for v,mass in pairs(loads) do if v:isLocalPhysicSim() then Load.apply(v,mass,dt) end end
    end
end
Events.OnServerCommand.Add(function(module,name,args)
    if module==P.module then local ok,err=pcall(C.receive,name,args);if not ok then print('[CVP MP client] '..tostring(err)) end end
end)
Events.OnTick.Add(function() local ok,err=pcall(C.tick);if not ok then print('[CVP MP client] '..tostring(err)) end end)
Events.OnGameStart.Add(function()
    Audio.clear()
    View.clear()
    if not CVPNetwork or not CVPWorldNative then
        local p=getPlayer();if p then p:Say(getText('IGUI_CVP_NativeMissing')) end
    else send('sync',{}) end
end)
Events.OnFillWorldObjectContextMenu.Add(function(player,context,objects,test)
    if test or not CVPNetwork then return end
    local p=getSpecificPlayer(player);if not p or p:isDead() then return end
    local scope=Menu.begin(p,context,objects)
    Batch.menu(p,context,function(who,b,v,gear,point,after,approach,mode)
        return C.queueAction('attach',who,b,v,gear,point,after,approach,mode)
    end,function(v)
        local count=0;for _,r in pairs(C.links) do if r.target.vehicle==v:getId() then count=count+1 end end;return count
    end,C.connectionReason('twoPointAttach') and getText(C.connectionReason('twoPointAttach')) or nil,
        {queue=C.queueChain,resolve=function(b) local r=C.links[CVPNetwork.id(b)];return r and r.body==b and r or nil end},scope)
    local targetContext=context
    local function option(label,reason,fn,b)
        local opt=targetContext:addOption(label,p,fn)
        Menu.reason(opt,reason and getText(reason))
        if b then ISWorldObjectContextMenu.initWorldItemHighlightOption(opt,b) end
        return opt
    end
    local members={}
    for _,r in pairs(C.links) do
        local c=r.target.connection
        if c then members[c.id]=r.target.parentConnection or true end
    end
    local counts={}
    for _,r in pairs(C.links) do local id=r.target.vehicle;counts[id]=(counts[id] or 0)+1 end
    local cars=getCell():getVehicles():iterator()
    while cars:hasNext() do local v=cars:next();local count=counts[v:getId()] or 0
        if not scope.bodyClick and (not scope.vehicle or scope.vehicle==v) and count>0 and v:getSquare() and P.near(p,v,4) then
            local reason=C.connectionReason('bulkDetach')
                or p:getVehicle() and 'IGUI_CVP_LeaveVehicle'
                or math.abs(v:getCurrentSpeedKmHour())>1 and 'IGUI_CVP_StopVehicle' or nil
            targetContext=scope:vehicleMenu(v)
            local selected={}
            for _,r in pairs(C.links) do
                if r.body and r.target.vehicle==v:getId() and World.canDetach(p,r.target) then selected[#selected+1]=r.body end
            end
            local opt=option(getText('IGUI_CVP_DetachAllMenu',tostring(count)),reason,function(who) C.requestDetachAll(who,v) end)
            Menu.highlight(opt,selected)
            local rows,byConnection={},{}
            for _,r in pairs(C.links) do if r.body and r.target.vehicle==v:getId()
                and Connection.valid(r.target.connection) then
                local row={body=r.body,connection=r.target.connection,point=r.target.point or 'feet',target=r.target}
                rows[#rows+1]=row;byConnection[row.connection.id]=row
            end end
            for _,r in ipairs(rows) do r.parent=byConnection[r.target.parentConnection] end
            local order,why=Rewire.plan(v,rows)
            why=C.connectionReason('rewire') or why or #rows~=count and 'IGUI_CVP_RewireUnloaded' or nil
            local function check()
                if not World.towingEnabled() then return 'IGUI_CVP_TowingDisabled' end
                if not C.epoch then return 'IGUI_CVP_QueueStopped' end
                if C.connectionReason('rewire') then return C.connectionReason('rewire') end
                if p:getVehicle() then return 'IGUI_CVP_LeaveVehicle' end
                for _,r in ipairs(order or {}) do local current=C.links[CVPNetwork.id(r.body)]
                    if not current or not Connection.valid(current.target.connection)
                        or current.target.connection.id~=r.connection.id or not World.canDetach(p,current.target) then return 'IGUI_CVP_LetGo' end
                end
            end
            why=why or check()
            local rewire=option(getText('IGUI_CVP_Rewire'),reason or why,function(who)
                if not order or check() then return end
                RewireAction.start(who,v,order,check,function(done)
                    local selection={};for _,r in ipairs(order) do selection[#selection+1]={id=CVPNetwork.id(r.body),connection=r.connection.id} end
                    C.request=C.request+1
                    C.pending[C.request]={time=getTimestampMs(),epoch=C.epoch,fn=function(ok,id,why) done(ok,why) end}
                    send('rewire',{request=C.request,vehicle=v:getId(),selection=selection},who)
                end)
            end)
            Menu.hint(rewire,getText('IGUI_CVP_RewireHint'))
            if order then local bodies={};for _,r in ipairs(order) do bodies[#bodies+1]=r.body end;Menu.highlight(rewire,bodies,v,true) end
        end
    end
    local bodies={};local seen={}
    local function collect(sq)
        if not sq then return end;local rows=sq:getStaticMovingObjects()
        for i=0,rows:size()-1 do local b=rows:get(i)
            local r=C.links[CVPNetwork.id(b)]
            if World.towable(b) and (not scope.vehicle or not r or r.target.vehicle==scope.vehicle:getId()) and scope:allows(b) and not seen[b] and P.near(p,b,4) then
                bodies[#bodies+1]=b;seen[b]=true
            end
        end
    end
    if scope.bodyClick then
        for b in pairs(scope.clicked) do collect(b:getSquare()) end
    else
        for _,o in ipairs(objects) do collect(o:getSquare()) end
    end
    if #bodies==0 then for dx=-4,4 do for dy=-4,4 do collect(getCell():getGridSquare(math.floor(p:getX())+dx,math.floor(p:getY())+dy,math.floor(p:getZ()))) end end end
    table.sort(bodies,function(a,b) return P.distance(p,a)<P.distance(p,b) end)
    local gear={}
    local function equipment(inv)
        local rows=inv:getItems()
        for i=0,rows:size()-1 do local item=rows:get(i);local t=item:getFullType()
            if P.materials[t] and not gear[t] and p:getPrimaryHandItem()~=item and p:getSecondaryHandItem()~=item then gear[t]=item end
            if instanceof(item,'InventoryContainer') then equipment(item:getInventory()) end
        end
    end
    equipment(p:getInventory())
    for index,b in ipairs(bodies) do
        local attached=C.links[CVPNetwork.id(b)]
        local bodyContext
        if scope.vehicle and attached then bodyContext=scope:detachMenu(scope.vehicle)
        else bodyContext=scope:bodyMenu(b,index) end
        targetContext=bodyContext
        if World.data(b) or C.links[CVPNetwork.id(b)] then
            local r=C.links[CVPNetwork.id(b)]
            local md=(r and r.target) or World.data(b)
            local reason=C.connectionReason() or p:getVehicle() and 'IGUI_CVP_LeaveVehicle' or not World.canDetach(p,md) and 'IGUI_CVP_OtherOwner' or nil
            option(scope.vehicle and getText('IGUI_CVP_DetachNumber',tostring(index)) or getText('IGUI_CVP_Detach'),reason,function(who) C.queueAction('detach',who,b) end,b)
        else
            local found=false
            local attachMenu=bodyContext
            local function attachOption(v,item,label)
                local reason=not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
                    or C.connectionReason('twoPointAttach')
                    or p:getVehicle() and 'IGUI_CVP_LeaveVehicle'
                    or not b:isZombie() and not World.playerBodiesAllowed() and 'IGUI_CVP_PlayerBodiesDisabled'
                    or not v and 'IGUI_CVP_ParkNearby'
                    or v and math.abs(v:getCurrentSpeedKmHour())>1 and 'IGUI_CVP_StopVehicle'
                    or not item and 'IGUI_CVP_NeedGear'
                    or b:isBeingGrappled() and 'IGUI_CVP_LetGo'
                    or World.foreignTowed(b) and 'IGUI_CVP_AlreadyAttached'
                    or item and (p:getPrimaryHandItem()==item or p:getSecondaryHandItem()==item) and 'IGUI_CVP_StowGear' or nil
                -- Tie.start approaches first; immediate reach is checked by the timed action.
                targetContext=attachMenu

                local opt=option(label,reason,function(who) C.queueAction('attach',who,b,v,item) end,b)
                Menu.hint(opt,getText('IGUI_CVP_HintBodyFirst'))
                Menu.highlight(opt,{b},v,false)
            end
            local vehicles=getCell():getVehicles():iterator()
            while vehicles:hasNext() do local v=vehicles:next()
                if (not scope.vehicle or scope.vehicle==v) and v:getSquare() then local ax,ay,az=Geometry.anchor(v)
                    if math.floor(az)==math.floor(b:getZ()) and (ax-b:getX())^2+(ay-b:getY())^2<=64 then
                        found=true;local any=false
                        for _,t in ipairs({'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}) do local item=t==scope.material and gear[t]
                            if item then
                                any=true;attachOption(v,item,getText('IGUI_CVP_AttachGear',vehicleName(v),item:getDisplayName()))
                            end
                        end
                        if not any then attachOption(v,nil,getText('IGUI_CVP_AttachVehicle',vehicleName(v))) end
                    end
                end
            end
            local tailMenu
            for _,t in ipairs({'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}) do local item=t==scope.material and gear[t]
            local parent=Batch.nearest(b,C.links,function(r)
                local v=getVehicleById(r.target.vehicle)
                if Connection.chainSize(members,r.target.connection.id)>=World.maxChain() or not item or (scope.vehicle and v~=scope.vehicle) or not World.canDetach(p,r.target) or not v or not v:getSquare()
                    or math.abs(v:getCurrentSpeedKmHour())>1 then return false end
                for _,child in pairs(C.links) do if child.target.parentConnection==r.target.connection.id then return false end end
                return true
            end)
            if parent then
                tailMenu=bodyContext
                targetContext=tailMenu
                local opt=option(getText('IGUI_CVP_QuickTail',item:getDisplayName()),
                p:getVehicle() and 'IGUI_CVP_LeaveVehicle' or nil,
                function(who) C.queueChain(who,b,parent,item) end,parent.body)
                Menu.highlight(opt,{b,parent.body}) end
            end
            if not found then attachOption(nil,nil,getText('IGUI_CVP_Attach')) end
            scope:materialMenu()
        end
    end

end)
