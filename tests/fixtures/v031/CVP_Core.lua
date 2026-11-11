-- Authoritative SP/server operations. No menus, RPCs or rendering.
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Rope=require 'CVP_Rope'
local Load=require 'CVP_Load'
local Connection=require 'CVP_Connection'
local Core={}

-- Shared active-link indexes. The ordered list also defines solver iteration order.
function Core.register(reg,r)
    local id=r.connection.id
    assert(not reg.byConnection[id] and not reg.byBody[r.body],'duplicate connection')
    if r.parent then assert(not reg.child[r.parent.connection.id],'body already has a follower') end
    reg.byConnection[id]=r;reg.byBody[r.body]=r
    if r.parent then reg.child[r.parent.connection.id]=r end
    local follower=reg.child[id]
    if follower then follower.parent=r;follower.connection.a.object=r.body end
    local data=r.vehicle:getModData()
    data.CVPConnections=data.CVPConnections or {}
    data.CVPConnections[id]=r.md.parentConnection or true
    local group=reg.byVehicle[r.vehicle]
    if not group then group={};reg.byVehicle[r.vehicle]=group end
    group[#group+1]=r;reg.links[#reg.links+1]=r
end

function Core.unregister(reg,r)
    -- A delayed removal must not remove a replacement record's indexes.
    if reg.byConnection[r.connection.id]~=r then return end
    reg.byConnection[r.connection.id]=nil;reg.byBody[r.body]=nil
    if r.parent and reg.child[r.parent.connection.id]==r then reg.child[r.parent.connection.id]=nil end
    local group=reg.byVehicle[r.vehicle]
    for i=#group,1,-1 do if group[i]==r then table.remove(group,i);break end end
    if #group==0 then reg.byVehicle[r.vehicle]=nil end
    for i=#reg.links,1,-1 do if reg.links[i]==r then table.remove(reg.links,i);break end end
end

function Core.registry(links)
    local reg={links={},byConnection={},byBody={},byVehicle={},child={}}
    for _,r in ipairs(links or {}) do Core.register(reg,r) end
    -- Preserve the list used by existing development reload callbacks.
    if links then reg.links=links end
    return reg
end

function Core.metadata(vehicleKey,gear,slot,point,b)
    return {version=3,connection=Connection.create(b,vehicleKey,point),
        gearID=gear:getID(),gearType=gear:getFullType(),slot=slot,length=1}
end

function Core.vehicleKey(md)
    return md.connection.a.kind=='vehicle' and md.connection.a.key or md.rootVehicle
end

function Core.link(b,v,gear,md,parent)
    local connection=Connection.bind(md.connection,b,parent and parent.body or v)
    local ax,ay
    if not parent then ax,ay=Geometry.anchor(v) else ax,ay=Rope.feet(parent) end
    local r={connection=connection,body=b,vehicle=v,md=md,gear=gear,mass=Load.mass(b:getContainer()),
        parent=parent,anchorHeight=parent and Rope.floorHeight or nil,
        x=b:getX(),y=b:getY(),z=b:getZ(),angle=b:getAngle(),slot=md.slot,length=md.length,
        point=connection.b.point,ax=ax,ay=ay,vx=0,vy=0,last=getTimestampMs()}
    Geometry.capture(r)
    return r
end

-- Fix the working length once, at authoritative attachment; restored links keep theirs.
function Core.fitLength(b,v,gear,md,parent)
    local r=Core.link(b,v,gear,md,parent)
    local ax,ay,az=Core.anchor(r)
    local bx,by,bz=Rope.feet(r)
    local height=(az+(r.anchorHeight or Rope.anchorHeight)-bz)*3
    -- The constraint solver has a 10 cm minimum horizontal reach.
    md.length=math.sqrt(math.max(0.01,(ax-bx)^2+(ay-by)^2)+height*height)
end

function Core.connection(r)
    return r.connection
end

function Core.anchor(r)
    if r.parent then
        local x,y=Rope.feet(r.parent)
        return x,y,r.parent.z
    end
    return Geometry.anchor(Core.connection(r).a.object)
end

function Core.childMetadata(parent,b,gear,slot,point)
    local md=Core.metadata(World.vehicleKey(parent.vehicle),gear,slot,point,b)
    md.rootVehicle=World.vehicleKey(parent.vehicle)
    md.parentConnection=parent.connection.id
    md.connection.a={kind='body',key=parent.connection.b.key,point=parent.point}
    return md
end

function Core.canFollow(parent)
    if parent.failed or World.foreignTowed(parent.body) or not World.data(parent.body) then return false end
    local members=parent.vehicle:getModData().CVPConnections or {}
    for _,id in pairs(members) do if id==parent.connection.id then return false end end
    return true
end

function Core.memberCount(v)
    if not v:getModData().CVPVehicleKey then return 0 end
    local n=0;for _ in pairs(v:getModData().CVPConnections or {}) do n=n+1 end
    return n
end

-- Membership is saved on the car, including sleeping descendants. Removing a
-- middle link invalidates its whole tail even if those corpses are not loaded.
function Core.endTail(r)
    local saved,err=require('CVP_Equipment').endTail(r.md)
    if not saved then return false,err end
    local members=r.vehicle and r.vehicle:getModData().CVPConnections
    if not members then return true end
    local children={}
    for id,parent in pairs(members) do
        if type(parent)=='string' then children[parent]=children[parent] or {};table.insert(children[parent],id) end
    end
    local queue={r.md.connection.id};local seen={};local i=1
    while i<=#queue do
        local id=queue[i];i=i+1
        if not seen[id] then
            seen[id]=true;members[id]=nil
            for _,child in ipairs(children[id] or {}) do queue[#queue+1]=child end
        end
    end
    return true
end

function Core.ended(r)
    if r.md.ended then return true end
    if not r.parent then return false end
    local members=r.vehicle:getModData().CVPConnections
    return not members or members[r.connection.id]~=r.md.parentConnection
end

function Core.connected(r)
    local current=r
    local seen={}
    while current and not seen[current] do
        seen[current]=true
        if not current or not current.taut or current.failed then return false end
        if not current.parent then return true end
        current=current.parent
    end
    return false
end

-- Chains advance together at bounded substeps. Each child's anchor uses its
-- parent's collision-resolved pose from the same substep, not the previous tick.
-- Standalone links keep their existing integration path.
function Core.prepareChains(reg,now,dt)
    if not World.towingEnabled() then return end
    for _,r in ipairs(reg.links) do r.chainWaiting=nil;r.chainTick=nil;r.chainLoadMass=nil;r.chainRange=false end
    for _,root in ipairs(reg.links) do
        local members=root.vehicle:getModData().CVPConnections or {}
        local hasChild=false
        for _,id in pairs(members) do if id==root.connection.id then hasChild=true;break end end
        if not root.parent and hasChild then
            local rows={root};local r=reg.child[root.connection.id]
            local seen={[root]=true}
            while r and not seen[r] do seen[r]=true;rows[#rows+1]=r;r=reg.child[r.connection.id] end
            local ready=true
            local last=rows[#rows]
            for _,id in pairs(members) do if id==last.connection.id then ready=false end end
            for _,link in ipairs(rows) do
                local b=link.body
                if link.failed or Core.ended(link) or (link.owner and link.owner:isDead()) or not b:getSquare()
                    or b:getStaticMovingObjectIndex()<0 or not link.vehicle:getSquare()
                    or b:isBeingGrappled() or World.foreignTowed(b) or World.gear(b,link.md)~=link.gear
                    or not World.data(b) then ready=false end
            end
            local ok,err=true,nil
            if ready then
                ok,err=pcall(function()
                    local steps=math.max(1,math.ceil(dt*120-1e-9));local h=dt/steps
                    local tension={};local external={}
                    -- Keep contacts with other groups, but refresh this chain's
                    -- own contacts at the same rate as its constraints.
                    for _,link in ipairs(rows) do external[link]={link.pushX or 0,link.pushY or 0} end
                    Rope.separate(rows)
                    for _,link in ipairs(rows) do
                        local push=external[link]
                        push[1]=push[1]-link.pushX;push[2]=push[2]-link.pushY
                        link.chainLoadMass=0
                    end
                    -- Spread hitch travel over the frame: giving the first substep
                    -- the whole displacement creates a false velocity spike.
                    local startAX,startAY=root.ax,root.ay
                    local targetAX,targetAY=Core.anchor(root)
                    targetAX,targetAY=Rope.networkAnchor(root,targetAX,targetAY,dt,root.vehicle:getCurrentSpeedKmHour())
                    for step=1,steps do
                        Rope.separate(rows)
                        for _,link in ipairs(rows) do
                            local push=external[link]
                            link.pushX=link.pushX+push[1];link.pushY=link.pushY+push[2]
                            local force=math.sqrt(link.pushX^2+link.pushY^2)
                            if force>60 then link.pushX=link.pushX*60/force;link.pushY=link.pushY*60/force end
                            local ax,ay,az=Core.anchor(link)
                            if not Core.inRange(link.x,link.y,link.z,ax,ay,az) then
                                -- Expected overstretch is a lifecycle event, not a solver failure.
                                -- Adapters release this segment and its descendants normally.
                                link.chainRange=true
                                for _,row in ipairs(rows) do row.chainLoadMass=0 end
                                return
                            end
                            if not link.parent then
                                ax=startAX+(targetAX-startAX)*step/steps
                                ay=startAY+(targetAY-startAY)*step/steps
                            end
                            Core.advance(link,ax,ay,az,h)
                            tension[link]=tension[link] or link.taut
                        end
                        local pathTaut=true
                        for _,link in ipairs(rows) do
                            pathTaut=pathTaut and link.taut and not link.failed
                            Load.refresh(link,now)
                            -- Integrate only simultaneous tension along the whole path.
                            link.chainLoadMass=link.chainLoadMass+Load.tension(link,pathTaut,h)/steps
                        end
                    end
                    for _,link in ipairs(rows) do link.taut=tension[link] or false end
                end)
            end
            for _,link in ipairs(rows) do
                link.chainTick=now;link.chainWaiting=not ready
                if not ok then link.failed=true;link.taut=false;link.chainError=tostring(err) end
            end
        end
    end
end

-- Transfer the original item. The server wraps this to replicate successful moves.
function Core.transfer(item,source,destination)
    if item:getContainer()~=source or not source:getItems():contains(item) then return false,'IGUI_CVP_ItemConflict' end
    if destination:getItemWithID(item:getID()) then return false,'IGUI_CVP_ItemConflict' end
    local ok,err=pcall(function()
        source:Remove(item)
        -- Another mod may refuse removal or move the item elsewhere.
        assert(not source:getItems():contains(item) and not item:getContainer(),'source did not release tether')
        destination:AddItem(item)
        assert(destination:getItems():contains(item),'inventory rejected tether')
    end)
    if not ok then
        if destination:getItems():contains(item) then destination:Remove(item) end
        if not item:getContainer() then source:AddItem(item) end
        return false,tostring(err)
    end
    return true
end

-- Keep a failed transfer addressable until the equipment store confirms its
-- owner. Both normal attachment and schema-2 migration use the original item.
local function hold(b,gear,md,transfer)
    local previousVersion=md.version
    md.version=3
    local key,err=require('CVP_Equipment').hold(gear,transfer,{body=b,metadata=md})
    if key then
        md.version=3;md.equipmentKey=key;b:getModData().CVPTether=md
    else md.version=previousVersion end
    return key,err
end

-- Adapters own runtime registration/cleanup and inventory replication.
function Core.attach(b,gear,md,activate,rollback,transfer)
    transfer=transfer or Core.transfer
    local source=gear and gear:getContainer()
    local key,err=hold(b,gear,md,transfer)
    if not key or err then return false,err end
    local made,result=pcall(activate)
    if not made then
        local undone,why=true,nil
        if rollback then undone,why=pcall(rollback) end
        if not undone then return false,tostring(result)..'; rollback: '..tostring(why) end
        local returned,reason=require('CVP_Equipment').release(key,source,transfer,{body=b,metadata=md})
        if returned then b:getModData().CVPTether=nil
        else return false,tostring(result)..'; return: '..tostring(reason) end
        return false,tostring(result)
    end
    if CVPSkeletonNative then CVPSkeletonNative.sync(b) end
    return true,result
end

-- A nil destination asks the equipment store for an explicit world-ground
-- return. A rejected return keeps the saved link available for retry.
function Core.release(b,gear,destination,transfer)
    local md=b:getModData().CVPTether
    if md and md.version==2 and gear then
        local key,err=hold(b,gear,md,transfer)
        if not key or err then return false,err end
    end
    if md and md.version==3 then
        local ok,err=require('CVP_Equipment').release(md.equipmentKey,destination,transfer,{body=b,metadata=md})
        if not ok then return false,err end
    end
    b:getModData().CVPTether=nil
    if CVPSkeletonNative then CVPSkeletonNative.sync(b) end
    return true
end

local vehicleRevisions=setmetatable({},{__mode='k'})
function Core.observeVehicle(v)
    local md=v:getModData();local key=md.CVPVehicleKey
    if not key then return true end
    local members,err,revision=require('CVP_Equipment').members(key,md.CVPConnections)
    if not members then return false,err end
    local seen=vehicleRevisions[v]
    if seen and seen.revision==revision and seen.members==md.CVPConnections then return true end
    local same=type(md.CVPConnections)=='table'
    if same then
        for id,parent in pairs(members) do if md.CVPConnections[id]~=parent then same=false;break end end
        if same then for id,parent in pairs(md.CVPConnections) do if members[id]~=parent then same=false;break end end end
    end
    if not same then
        local restored={};for id,parent in pairs(members) do restored[id]=parent end
        md.CVPConnections=restored
    end
    vehicleRevisions[v]={revision=revision,members=md.CVPConnections}
    return true
end

function Core.loadedVehicles()
    local cars={};local it=getCell():getVehicles():iterator()
    while it:hasNext() do local v=it:next();local key=v:getModData().CVPVehicleKey
        if key and v:getSquare() and Core.observeVehicle(v) then cars[key]=v end
    end
    return cars
end

function Core.inRange(x,y,z,ax,ay,az)
    return math.floor(az)==math.floor(z) and (ax-x)^2+(ay-y)^2<=324
end

-- Restore only after both endpoints are loaded. Legacy corpse equipment moves
-- once into the store; unavailable recovery records wait without losing keys.
function Core.restore(b,md,cars,reg,transfer)
    local vehicleKey=Core.vehicleKey(md)
    local gear=World.gear(b,md);local v=cars[vehicleKey]
    if not Connection.bodyMatches(b,md.connection) then return 'waiting',gear,v end
    -- Invalidating a saved parent also needs the car's sleeping-tail membership.
    if not v then return 'waiting',gear,v end
    if not Core.observeVehicle(v) then return 'waiting',gear,v end
    if not gear then return md.version==3 and 'waiting' or 'missing',gear,v end
    if md.ended then return 'missing',gear,v end
    if World.foreignTowed(b) then return 'missing',gear,v end
    local parent
    if md.connection.a.kind=='body' then
        local members=v:getModData().CVPConnections
        if not members or members[md.connection.id]~=md.parentConnection then return 'missing',gear,v end
        local cursor=md.connection.id;local seen={}
        while true do
            if seen[cursor] then return 'missing',gear,v end
            seen[cursor]=true
            local nextID=members[cursor]
            if nextID==true then break end
            if type(nextID)~='string' then return 'missing',gear,v end
            cursor=nextID
        end
        parent=reg and reg.byConnection[md.parentConnection]
        if not parent then return 'waiting',gear,v end
        if parent.connection.b.key~=md.connection.a.key then return 'missing',gear,v end
    end
    local ax,ay,az
    if parent then ax,ay=Rope.feet(parent);az=parent.z else ax,ay,az=Geometry.anchor(v) end
    if not Core.inRange(b:getX(),b:getY(),b:getZ(),ax,ay,az) then return 'range',gear,v end
    if md.version==2 then
        local key,err=hold(b,gear,md,transfer)
        if not key or err then return 'waiting',gear,v end
    end
    return 'ready',gear,v,parent
end

-- Adapters retain their own tick clocks, network anchor smoothing, lifecycle
-- guards, error handling, orientation invalidation and presentation timing.
function Core.advance(r,ax,ay,az,dt,pathCache)
    local b=Core.connection(r).b.object
    if not r.footprint then Geometry.capture(r) end
    local oldAngle=r.angle
    local x,y,taut=Rope.step(r,r.x,r.y,ax,ay,dt,az)
    x,y,r.angle,r.blocked=Geometry.resolve(r,x,y,r.angle,oldAngle)
    r.ropeBlocked=nil
    if pathCache then
        local bx,by=Rope.feet(r,x,y)
        r.ropeBlocked=require('CVP_LinkObstacles').check(pathCache,{x=ax,y=ay,z=az},{x=bx,y=by,z=r.z})
        if r.ropeBlocked then x=r.x;y=r.y;r.angle=oldAngle;r.blocked=true;taut=false end
    end
    if r.blocked then r.vx=0;r.vy=0 end
    local sq=getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(r.z))
    r.movePending={square=b:getSquare(),x=r.x,y=r.y,z=r.z}
    World.move(b,x,y,r.z,sq)
    r.movePending=nil
    r.x=x;r.y=y;r.taut=taut
    return sq
end
return Core
