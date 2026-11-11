-- SP towing: one persistent world corpse, no inventory carrier or serialized copy.
if isClient() or isServer() then return end
local Connection=require 'CVP_Connection'
local Rope=require 'CVP_Rope'
local Load=require 'CVP_Load'
local ViewCompat=require 'CVP_Viewpoint'
local AttachAction=require 'CVP_AttachAction'
local Tie=require 'CVP_TieSequence'
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Batch=require 'CVP_Batch'
local Menu=require 'CVP_Menu'
local Audio=require 'CVP_Audio'
local Core=require 'CVP_Core'
local Rewire=require 'CVP_Rewire'
local RewireAction=require 'CVP_RewireAction'
-- Reject incomplete hot reloads before replacing any live state or callbacks.
assert(type(Menu)=='table' and type(Menu.begin)=='function', 'CVP_Menu is unavailable; keeping previous client handlers')
assert(type(Audio)=='table' and type(Audio.stop)=='function' and type(Audio.update)=='function',
    'CVP_Audio is unavailable; keeping the previous client handlers')
assert(type(Tie)=='table' and type(Tie.start)=='function',
    'CVP_TieSequence is unavailable; keeping the previous client handlers')
assert(type(Core)=='table' and type(Core.attach)=='function' and type(Core.release)=='function'
    and type(Core.advance)=='function','CVP_Core is unavailable; keeping the previous client handlers')
-- Stable state and dispatchers survive the development bridge's Lua reloads.
local Runtime=CVPRuntime or {schema=2,links={},pending={},nextID=0,dispatchers={},generation=0}
assert(Runtime.schema==2,'CVP runtime schema changed; reload the save')
local registry=Core.registry(Runtime.links)
Runtime.registry=registry
local links=registry.links
local pendingHandlers={}
local function bind(name,fn) pendingHandlers[name]=fn end
local materials={['Base.Rope']='IGUI_CVP_Rope',['Base.HeavyChain']='IGUI_CVP_Chain',['Base.HeavyChain_Hook']='IGUI_CVP_HookChain'}
local function tell(s,key,...)
    Runtime.lastMessage=s
    print('[CVP] '..s)
    local p=getPlayer()
    if p and key then p:Say(getText(key,...)) end
end
local function snapshot(c,excluded)
    local rows={}
    local function walk(inv,path)
        local items=inv:getItems()
        for i=0,items:size()-1 do local a=items:get(i);if a~=excluded then local key=path..'/'..tostring(a:getID())
            rows[#rows+1]=key..':'..a:getFullType()..':'..a:getCondition()
            if instanceof(a,'InventoryContainer') then walk(a:getInventory(),key) end
            end
        end
    end
    walk(c,'root');table.sort(rows);return table.concat(rows,'|')
end
local function square(x,y,z) return getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(z)) end
local function distance(x,y,a,b) return math.sqrt((x-a)^2+(y-b)^2) end
local anchor=Geometry.anchor
local function vehicleName(v)
    local name=v:getScript():getName()
    return (getTextOrNull and getTextOrNull('IGUI_VehicleName'..name)) or name
end

local function removeLink(r)
    Audio.stop(r.body)
    ViewCompat.untrack(r.body)
    r.proxySquare=nil
    Core.unregister(registry,r)
end
local function restoreWeight(item)
    local md=item:getModData().CVPRecovery
    if md and md.weight then item:setActualWeight(md.weight);item:setCustomWeight(md.customWeight==true) end
end
local function releaseBody(r)
    local destination=r.owner and not r.owner:isDead() and r.owner:getInventory() or nil
    local ok,err=Core.release(r.body,r.gear,destination)
    if not ok then error(err) end
end
local function finish(r,reason)
    if r.finishing then return end
    r.finishing=true
    local ok,err=pcall(function()
        if r.movePending and r.body:getStaticMovingObjectIndex()<0 then
            local previous=r.movePending
            World.position(r.body,previous.x,previous.y,previous.z,previous.square)
            previous.square:addCorpse(r.body,false)
            assert(r.body:getStaticMovingObjectIndex()>=0,'world rollback still pending')
        end
        releaseBody(r)
        Core.endTail(r)
        Runtime.pending[r.body]=nil
        removeLink(r)
        local tails={}
        for _,tail in ipairs(links) do if Core.ended(tail) then tails[#tails+1]=tail end end
        for _,tail in ipairs(tails) do
            if registry.byBody[tail.body]==tail then finish(tail,'upstream released') end
        end
        tell('Released ('..reason..'); inventory '..(snapshot(r.body:getContainer())==r.baseline and 'MATCH' or 'CHANGED'),'IGUI_CVP_Released')
    end)
    r.finishing=false
    if not ok then r.failed=true;tell('Release failed: '..tostring(err),'IGUI_CVP_ReleaseFailed') end
end
local function alreadyAttached(body)
    return registry.byBody[body]~=nil
end
local function attachReason(p,b,v,gear,approaching,parent)
    if not World.towingEnabled() then return getText('IGUI_CVP_TowingDisabled') end
    if not CVPWorldNative or not CVPItemNative or not CVPEquipmentPersistence then return getText('IGUI_CVP_NativeMissing') end
    if not World.towable(b) then return getText('IGUI_CVP_NeedCorpse') end
    if not b:isZombie() and not World.playerBodiesAllowed() then return getText('IGUI_CVP_PlayerBodiesDisabled') end
    if p:isDead() then return getText('IGUI_CVP_Dead') end
    if p:getVehicle() then return getText('IGUI_CVP_LeaveVehicle') end
    if alreadyAttached(b) or World.data(b) or World.foreignTowed(b) then return getText('IGUI_CVP_AlreadyAttached') end
    if b:getStaticMovingObjectIndex()<0 then return getText('IGUI_CVP_BodyMoved') end
    if b:isBeingGrappled() then return getText('IGUI_CVP_LetGo') end
    if b:isFakeDead() then return getText('IGUI_CVP_Alive') end
    if math.floor(p:getZ())~=math.floor(b:getZ()) then return getText('IGUI_CVP_BodyFloor') end
    local pd=distance(p:getX(),p:getY(),b:getX(),b:getY())
    if pd>4 and not approaching then return getText('IGUI_CVP_BodyDistance',string.format('%.1f',pd)) end
    if not v or not v:getSquare() then return getText('IGUI_CVP_ParkNearby') end
    local ax,ay,az
    if parent then ax,ay,az=Core.anchor({parent=parent}) else ax,ay,az=anchor(v) end
    if math.floor(az)~=math.floor(b:getZ()) then return getText('IGUI_CVP_VehicleFloor') end
    local vd=distance(ax,ay,b:getX(),b:getY())
    if vd>8 then return getText('IGUI_CVP_VehicleDistance',string.format('%.1f',vd)) end
    if math.abs(v:getCurrentSpeedKmHour())>1 then return getText('IGUI_CVP_StopVehicle') end
    local count=0
    count=#(registry.byVehicle[v] or {})
    if parent and Connection.chainSize(v:getModData().CVPConnections or {},parent.connection.id)>=World.maxChain() then return getText('IGUI_CVP_VehicleLimit') end
    local source=gear and gear:getContainer()
    if not source or p:getInventory():getItemWithIDRecursiv(gear:getID())~=gear then return getText('IGUI_CVP_NeedGear') end
end
local function makeLink(p,b,v,gear,md,parent)
    Runtime.nextID=Runtime.nextID+1
    local r=Core.link(b,v,gear,md,parent)
    r.id=Runtime.nextID;r.owner=p;r.storage=p:getInventory()
    r.baseline=md.baseline;r.proxySquare=b:getSquare()
    Core.register(registry,r);ViewCompat.track(b)
    Runtime.pending[b]=nil
    return r
end
local function attach(p,b,v,gear,point,atVehicle,parent)
    if atVehicle and not Geometry.nearAnchor(p,v) then return end
    if parent and (registry.byBody[parent.body]~=parent or not Core.canFollow(parent)) then return end
    local reason=attachReason(p,b,v,gear,atVehicle,parent)
    if reason then tell(reason,'IGUI_CVP_AttachRejected',reason);return end
    point=point or Geometry.nearestPoint(b,v)
    local inv=b:getContainer()
    if inv:getItemWithID(gear:getID()) then tell('Body already contains tether ID','IGUI_CVP_AttachFailed');return end
    local slot=1;local used={}
    for _,other in ipairs(registry.byVehicle[v] or {}) do used[other.slot]=true end
    while used[slot] do slot=slot+1 end
    local md=parent and Core.childMetadata(parent,b,gear,slot,point) or Core.metadata(World.vehicleKey(v),gear,slot,point=='neck' and 'neck' or 'feet',b)
    local observed,observeError=Core.observeVehicle(v)
    if not observed then tell('Cannot preserve vehicle membership: '..tostring(observeError),'IGUI_CVP_AttachFailed');return end
    md.baseline=snapshot(inv)
    local fitted,fitError=pcall(Core.fitLength,b,v,gear,md,parent)
    if not fitted then tell('Cannot prepare attachment: '..tostring(fitError),'IGUI_CVP_AttachFailed');return end
    local ok,err=Core.attach(b,gear,md,function()
        return makeLink(p,b,v,gear,md,parent)
    end,function()
        for i=#links,1,-1 do if links[i].body==b then Core.endTail(links[i]);removeLink(links[i]) end end
    end)
    if not ok then
        tell('Attach failed: '..tostring(err),'IGUI_CVP_AttachFailed');return
    end
    tell('Attached '..gear:getFullType()..'; bodies='..#links..'; world-owned','IGUI_CVP_Attached',tostring(#links))
end
local function queueChain(p,b,parent,gear,after)
    local function check()
        if registry.byBody[parent.body]~=parent or not Core.canFollow(parent) then return 'changed' end
        return attachReason(p,b,parent.vehicle,gear,true,parent)
    end
    if check() then return end
    return Tie.chain(p,b,parent.body,parent.vehicle,gear,parent.point,'feet',check,function(done)
        attach(p,b,parent.vehicle,gear,'feet',false,parent)
        local md=World.data(b);done(md~=nil and md.gearID==gear:getID(),md and md.connection.id)
    end,after)
end
local function discover(sq)
    if not sq then return end
    local bodies=sq:getStaticMovingObjects()
    for i=0,bodies:size()-1 do local b=bodies:get(i)
        if instanceof(b,'IsoDeadBody') and World.valid(World.data(b)) and not alreadyAttached(b) then
            Runtime.pending[b]=true
        end
    end
end
local function resumePending()
    local p=getPlayer();if not p or p:isDead() then return end
    local cars=Core.loadedVehicles()
    for b in pairs(Runtime.pending) do
        local md=World.data(b);local sq=b:getSquare()
        if not World.valid(md) or not sq or square(b:getX(),b:getY(),b:getZ())~=sq or b:getStaticMovingObjectIndex()<0 then
            Runtime.pending[b]=nil
        elseif alreadyAttached(b) then Runtime.pending[b]=nil
        elseif distance(p:getX(),p:getY(),b:getX(),b:getY())<=30 or (md.parentConnection and cars[md.rootVehicle] and distance(p:getX(),p:getY(),cars[md.rootVehicle]:getX(),cars[md.rootVehicle]:getY())<=30) then
            local status,gear,v,parent=Core.restore(b,md,cars,registry)
            if status=='missing' or status=='range' then
                local released,err=Core.release(b,gear,p:getInventory())
                if released then
                    Core.endTail({md=md,vehicle=v});Runtime.pending[b]=nil
                    tell('Saved connection ended; equipment returned')
                else tell('Saved equipment return pending: '..tostring(err)) end
            elseif status=='ready' then
                local ok,err=pcall(makeLink,p,b,v,gear,md,parent)
                if ok then tell('Restored world tether; bodies='..#links)
                else
                    local r=registry.byBody[b];if r then removeLink(r) end
                    tell('Saved connection retained for retry: '..tostring(err))
                end
            end -- vehicle not loaded: retain metadata and wait, never spawn anything
        end
    end
end
local function detachDormant(p,b)
    if p:isDead() or p:getVehicle() or distance(p:getX(),p:getY(),b:getX(),b:getY())>4 then return end
    local md=World.data(b);if not World.valid(md) then return end
    -- The car owns saved tail membership; releasing without it strands descendants.
    local v=Core.loadedVehicles()[Core.vehicleKey(md)]
    if not v then tell(getText('IGUI_CVP_VehicleUnavailable'),'IGUI_CVP_VehicleUnavailable');return end
    local gear=World.gear(b,md)
    releaseBody({owner=p,body=b,gear=gear})
    Core.endTail({md=md,vehicle=v})
    Runtime.pending[b]=nil
    tell('Dormant tether released','IGUI_CVP_Released')
end
local function queueAttach(p,b,v,gear,point,after,approaching,mode)
    local reason=attachReason(p,b,v,gear,approaching)
    if reason then tell(reason,'IGUI_CVP_AttachRejected',reason);return end
    point=point or Geometry.nearestPoint(b,v)
    return Tie.start(p,b,v,gear,point,attachReason,function(endpoint,done)
        attach(p,b,v,gear,point,endpoint=='vehicle')
        local md=World.data(b);done(md~=nil and md.gearID==gear:getID(),md and md.connection.id)
    end,after,mode)
end
local function queueDetach(p,b,record,after,approaching)
    local md=World.data(b);if not md then return end
    local v=record and record.vehicle or Core.loadedVehicles()[Core.vehicleKey(md)]
    local gear=World.gear(b,md)
    local function check(who,body,vehicle,item,approach)
        if who:isDead() or who:getVehicle() then return getText('IGUI_CVP_LeaveVehicle') end
        if not body:getSquare() or distance(who:getX(),who:getY(),body:getX(),body:getY())>(approach and 24 or 4) then return getText('IGUI_CVP_NoPath') end
        if World.data(body)~=md or World.gear(body,md)~=gear then return getText('IGUI_CVP_LetGo') end
        if not v or not v:getSquare() then return getText('IGUI_CVP_VehicleUnavailable') end
        if math.abs(v:getCurrentSpeedKmHour())>1 then return getText('IGUI_CVP_StopVehicle') end
    end
    local reason=check(p,b,v,gear,approaching)
    if reason then tell(reason);p:Say(reason);return end
    if not luautils.walkAdj(p,b:getSquare()) then tell('No path to body','IGUI_CVP_NoPath');return end
    ISTimedActionQueue.add(AttachAction:new(p,b,v,gear,check,function()
        if record then finish(record,'manual') else detachDormant(p,b) end
    end,true,md.connection.b.point,after and function(ok) after(ok and World.data(b)==nil) end))
    return true
end
local function equipment(inv,found,seen)

    seen=seen or {};if seen[inv] then return end;seen[inv]=true

    local items=inv:getItems()

    for i=0,items:size()-1 do local item=items:get(i);local t=item:getFullType()

        if materials[t] and not found[t] then found[t]=item end

        if instanceof(item,'InventoryContainer') then equipment(item:getInventory(),found,seen) end

    end

end

bind('OnFillWorldObjectContextMenu',function(player,context,objects,test)
    if test then return end
    local p=getSpecificPlayer(player);if not p then return end
    local scope=Menu.begin(p,context,objects)
    Batch.menu(p,context,queueAttach,function(v)
        local count=0;count=math.max(#(registry.byVehicle[v] or {}),Core.memberCount(v));return count
    end,nil,{queue=queueChain,resolve=function(b) return registry.byBody[b] end},scope)
    for _,r in ipairs(links) do
        if r.owner==p and scope:allows(r.body) and (not scope.vehicle or scope.vehicle==r.vehicle) then
            local reason=p:getVehicle() and getText('IGUI_CVP_LeaveVehicle')
                or distance(p:getX(),p:getY(),r.body:getX(),r.body:getY())>4 and getText('IGUI_CVP_BodyDistance',string.format('%.1f',distance(p:getX(),p:getY(),r.body:getX(),r.body:getY())))
                or math.abs(r.vehicle:getCurrentSpeedKmHour())>1 and getText('IGUI_CVP_StopVehicle') or nil
            local target=scope.bodyClick and scope:bodyMenu(r.body,r.id) or scope:detachMenu(r.vehicle)
            local opt=target:addOption(getText('IGUI_CVP_DetachNumber',tostring(r.id)),p,queueDetach,r.body,r)
            Menu.reason(opt,reason)
            ISWorldObjectContextMenu.initWorldItemHighlightOption(opt,r.body)
        end
    end
    local cars={}
    for _,r in ipairs(links) do if r.owner==p then cars[r.vehicle]=(cars[r.vehicle] or 0)+1 end end
    for v,count in pairs(cars) do
        if not scope.bodyClick and (not scope.vehicle or scope.vehicle==v) and v:getSquare() and distance(p:getX(),p:getY(),v:getX(),v:getY())<=4 then
            local reason=p:getVehicle() and getText('IGUI_CVP_LeaveVehicle')
                or math.abs(v:getCurrentSpeedKmHour())>1 and getText('IGUI_CVP_StopVehicle') or nil
            local opt=scope:vehicleMenu(v):addOption(getText('IGUI_CVP_DetachAllMenu',tostring(count)),nil,function()
                if p:getVehicle() or not v:getSquare() or math.abs(v:getCurrentSpeedKmHour())>1
                    or distance(p:getX(),p:getY(),v:getX(),v:getY())>4 then return end
                local rows={};for _,r in ipairs(links) do if r.vehicle==v and r.owner==p then
                    rows[#rows+1]={body=r.body,record=r,md=World.data(r.body)}
                end end
                Batch.release(p,v,rows,function(r,after)
                    if not World.data(r.body) then after(true);return true end
                    if World.data(r.body)~=r.md then return end
                    return queueDetach(p,r.body,r.record,after,true)
                end)
            end)
            Menu.reason(opt,reason)
            local selected={}
            for _,r in ipairs(links) do if r.vehicle==v and r.owner==p then selected[#selected+1]=r.body end end
            Menu.highlight(opt,selected)
            local order,why=Rewire.plan(v,registry.byVehicle[v] or {})
            why=why or order and Rewire.validate(registry,v,order,p)
            local rewire=scope:vehicleMenu(v):addOption(getText('IGUI_CVP_Rewire'),nil,function()
                if not order then return end
                RewireAction.start(p,v,order,function() return Rewire.validate(registry,v,order,p) end,function(done)
                    local ok,err=Rewire.apply(registry,v,order,p)
                    done(ok,not ok and err or nil)
                end)
            end)
            Menu.reason(rewire,reason or why and getText(why))
            Menu.hint(rewire,getText('IGUI_CVP_RewireHint'))
            if order then local bodies={};for _,r in ipairs(order) do bodies[#bodies+1]=r.body end;Menu.highlight(rewire,bodies,v,true) end
        end
    end
    if p:getVehicle() then
        local opt=context:addOption(getText('IGUI_CVP_ExitToAttach'),nil,nil);opt.notAvailable=true;return
    end
    local found={};for _,item in ipairs(Batch.equipment(p)) do
        local t=item:getFullType();if not found[t] then found[t]=item end
    end
    local seen={};local candidates={}
    local function collect(sq)
        if sq then local bodies=sq:getStaticMovingObjects()
            for i=0,bodies:size()-1 do local b=bodies:get(i)
                if World.towable(b) and scope:allows(b) and not alreadyAttached(b) and not seen[b] then
                    seen[b]=true;candidates[#candidates+1]=b
                end
            end
        end
    end
    -- Prefer the clicked tile; a corpse sprite commonly extends into adjacent tiles.
    if scope.bodyClick then
        for b in pairs(scope.clicked) do collect(b:getSquare()) end
    else
        for _,o in ipairs(objects) do collect(o:getSquare()) end
    end
    if #candidates==0 then
        for _,o in ipairs(objects) do local sq=o:getSquare()
            if sq then for dx=-1,1 do for dy=-1,1 do collect(square(sq:getX()+dx,sq:getY()+dy,sq:getZ())) end end end
        end
    end
    -- Also allow right-clicking nearby ground or the vehicle, without pixel hunting.
    if #candidates==0 then
        for dx=-4,4 do for dy=-4,4 do collect(square(p:getX()+dx,p:getY()+dy,p:getZ())) end end
    end
    table.sort(candidates,function(a,b)
        return distance(p:getX(),p:getY(),a:getX(),a:getY())<distance(p:getX(),p:getY(),b:getX(),b:getY())
    end)
    for index,b in ipairs(candidates) do
        local context=scope:bodyMenu(b,index)
        if World.data(b) then
            local option=context:addOption(getText('IGUI_CVP_Detach'),p,queueDetach,b)
            option.notAvailable=distance(p:getX(),p:getY(),b:getX(),b:getY())>4
            ISWorldObjectContextMenu.initWorldItemHighlightOption(option,b)
        else
        local vehicles={};local cars=getCell():getVehicles():iterator()
        while cars:hasNext() do local v=cars:next()
            if (not scope.vehicle or scope.vehicle==v) and v:getSquare() then local x,y,z=anchor(v)
                local d=distance(x,y,b:getX(),b:getY())
                if math.floor(z)==math.floor(b:getZ()) and d<=12 then vehicles[#vehicles+1]={v=v,d=d} end
            end
        end
        table.sort(vehicles,function(a,b) return a.d<b.d end)
        local attachMenu=context
        local function option(v,gear,label)
            local reason=attachReason(p,b,v,gear)
            local target=attachMenu

            local opt=target:addOption(label,p,queueAttach,b,v,gear)
            Menu.reason(opt,reason)
            Menu.hint(opt,getText('IGUI_CVP_HintBodyFirst'))
            ISWorldObjectContextMenu.initWorldItemHighlightOption(opt,b)
            Menu.highlight(opt,{b},v,false)
        end
        local tailMenu
        for _,t in ipairs({'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}) do local gear=t==scope.material and found[t]
            if gear then
                local parent=Batch.nearest(b,links,function(r)
                    return r.owner==p and (not scope.vehicle or r.vehicle==scope.vehicle)
                        and Core.canFollow(r) and not attachReason(p,b,r.vehicle,gear,true,r)
                end)
                if parent then
                    tailMenu=context
                    local opt=tailMenu:addOption(getText('IGUI_CVP_QuickTail',getText(materials[t])),p,queueChain,b,parent,gear)
                    Menu.highlight(opt,{b,parent.body})
                end
            end
        end
        if #vehicles==0 then option(nil,nil,getText('IGUI_CVP_Attach')) else
            for _,entry in ipairs(vehicles) do
                local any=false
                for _,t in ipairs({'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}) do local gear=t==scope.material and found[t]
                    if gear then any=true;option(entry.v,gear,getText('IGUI_CVP_AttachGear',vehicleName(entry.v),getText(materials[t]))) end
                end
                if not any then option(entry.v,nil,getText('IGUI_CVP_AttachVehicle',vehicleName(entry.v))) end
            end
        end
        scope:materialMenu()
        end
    end
end)
bind('RenderOpaqueObjectsInWorld',function() end)
bind('LoadGridsquare',discover)
local lastTick=getTimestampMs()
local loadFailed=false
local nextDiscovery=0
bind('OnTick',function()
    Batch.update()
    local now=getTimestampMs();local dt=math.max(0,math.min((now-lastTick)/1000,0.1));lastTick=now
    if now>=nextDiscovery then resumePending();nextDiscovery=now+1000 end
    local loads={}
    Rope.separate(links)
    Core.prepareChains(registry,now,dt)
    for i=#links,1,-1 do local r=links[i]
        if r and not r.failed then
            local ok,err=pcall(function()
                -- Death must release active links even during a simultaneous unload.
                if r.owner:isDead() then finish(r,'owner died');return end
                if r.body:isBeingGrappled() or World.foreignTowed(r.body) then
                    finish(r,'body taken by another interaction');return
                end
                local loaded=square(r.x,r.y,r.z)==r.body:getSquare()
                if not loaded or not r.vehicle:getSquare() or distance(r.owner:getX(),r.owner:getY(),r.parent and r.vehicle:getX() or r.x,r.parent and r.vehicle:getY() or r.y)>30 then
                    Runtime.pending[r.body]=true;removeLink(r);return
                end
                if r.body:getStaticMovingObjectIndex()<0 then
                    finish(r,'body removed');return
                end
                if Core.ended(r) then finish(r,'upstream released');return end
                if r.chainRange then finish(r,'tether overstretched');return end
                if r.chainWaiting or r.parent and registry.byConnection[r.parent.connection.id]~=r.parent then r.taut=false;r.loadMass=0;return end
                if World.gear(r.body,r.md)~=r.gear then finish(r,'tether changed');return end
                if not World.towingEnabled() then r.taut=false;r.loadMass=0;r.last=now;Audio.stop(r.body);return end
                local ax,ay,az=Core.anchor(r)
                if not Core.inRange(r.x,r.y,r.z,ax,ay,az) then finish(r,'трос растянут');return end
                Load.refresh(r,now)
                local stepdt=math.max(0,math.min((now-r.last)/1000,0.1));r.last=now
                if r.chainTick~=now then r.proxySquare=Core.advance(r,ax,ay,az,stepdt) end
                local fx,fy,fz=Rope.feet(r)
                r.tensionRatio=math.sqrt((ax-fx)^2+(ay-fy)^2+((az+Rope.anchorHeight-fz)*3)^2)/r.length
                Rope.shape(r,ax,ay,az,stepdt)
                ViewCompat.track(r.body)
                if r.drawAngle~=r.angle then r.body:setForwardDirectionAngle(r.angle);r.body:invalidateCorpse();r.drawAngle=r.angle end
                ViewCompat.rope(r)
                local mass=r.chainLoadMass or Load.tension(r,Core.connected(r),stepdt)
                if mass>0 then loads[r.vehicle]=(loads[r.vehicle] or 0)+mass end
            end)
            if not ok then tell('tick failed: '..tostring(err),'IGUI_CVP_AttachFailed');finish(r,'ошибка') end
        end
    end
    Audio.update(links)
    if not loadFailed and (not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.VehicleDrag~=false) then
        for v,mass in pairs(loads) do
            local ok,err=pcall(Load.apply,v,mass,dt)
            if not ok then loadFailed=true;tell('Vehicle load disabled: '..tostring(err),'IGUI_CVP_LoadFailed');break end
        end
    end
end)
bind('OnSave',function()
    for i=#links,1,-1 do if links[i].failed and links[i].movePending then finish(links[i],'movement rollback') end end
    tell('Saving '..#links..' world tethers; no body copies created')
end)
bind('OnGameStart',function()
    Audio.clear()
    ViewCompat.clear()
    tell('Local stock visuals loaded; native ground-work actions and scene materials; SP path')
    local p=getPlayer();if not p then return end
    local recovered,why=require('CVP_Equipment').recover(p)
    if not recovered then tell('Equipment recovery pending: '..tostring(why)) end
    local items=p:getInventory():getItems()
    for i=0,items:size()-1 do local item=items:get(i)
        if item:getModData().CVPRecovery then restoreWeight(item);tell('Legacy recovery item preserved; no body spawned','IGUI_CVP_RecoveryPresent') end
    end
    for dx=-32,32 do for dy=-32,32 do discover(square(p:getX()+dx,p:getY()+dy,p:getZ())) end end
    resumePending()
end)
local Overlay=require 'CVP_Overlay'
Overlay.install(links,anchor)
-- Commit new callbacks only after all modules and the overlay have initialized.
for name in pairs(pendingHandlers) do
    if not Runtime.dispatchers[name] then
        local eventName=name
        local dispatcher=function(...)
            local rt=CVPRuntime
            if rt and rt.handlers[eventName] then return rt.handlers[eventName](...) end
        end
        Events[name].Add(dispatcher)
        Runtime.dispatchers[name]=dispatcher
    end
end
Runtime.handlers=pendingHandlers
Runtime.generation=Runtime.generation+1
CVPRuntime=Runtime
if isDebugEnabled() then
    CVPTest={attach=attach,stop=finish,links=function() return links end,
        chain=queueChain,reason=attachReason,anchor=anchor,snapshot=snapshot,equipment=equipment,
        discover=discover,resume=resumePending,world=World,rope=Rope,
        generation=function() return Runtime.generation end,
        lastMessage=function() return Runtime.lastMessage end}
end
