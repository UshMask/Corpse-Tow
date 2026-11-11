-- Loaded-world adapter for the authoritative link service. No caller coordinates
-- become attachment coordinates, and no lookup creates a corpse or vehicle.
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Rope=require 'CVP_Rope'
local P=require 'CVP_Protocol'
local Horse=require 'CVP_Horse'
local H={}
local function key(s) return type(s)=='string' and #s>0 and #s<=256 end
local function sameObjects(a,b)
    if not a then return false end
    for id,value in pairs(a) do if b[id]~=value then return false end end
    for id,value in pairs(b) do if a[id]~=value then return false end end
    return true
end
function H.new()
    local h={bodies={},vehicles={},players={},poses=setmetatable({},{__mode='k'}),confirmed=setmetatable({},{__mode='k'})}
    function h.now() return getTimestampMs() end
    function h.uuid() return getRandomUUID() end
    h.enabled=World.towingEnabled;h.maxBodies=World.maxChain
    function h.path(a,b,cache)
        local O=require 'CVP_LinkObstacles'
        return O.check(cache or O.new(),a,b)
    end
    function h.vehicleKey(v)
        local sql=v:getSqlId();return sql and sql>0 and ('sql:'..tostring(sql)) or v:getModData().CVPVehicleKey
    end
    function h.actor(p)
        if not p then return end
        -- Permission ownership follows the same account-name policy as 0.3.
        -- Native inventory checkpoints retain their separate character identity.
        local name=p:getUsername();if not key(name) then return end
        h.players[name]=p
        return {key=name,x=p:getX(),y=p:getY(),z=p:getZ(),alive=not p:isDead(),onFoot=p:getVehicle()==nil and not Horse.mounted(p),
            allowOthers=not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.AllowDetachOthers~=false}
    end
    function h.inventory(p) return p:getInventory() end
    function h.item(p,id)
        if not P.integer(id) then return end
        local item=P.item(p:getInventory(),id)
        if item==p:getPrimaryHandItem() or item==p:getSecondaryHandItem() then return end
        return item
    end
    function h.transfer(item,source,destination)
        local ok,err=require('CVP_Core').transfer(item,source,destination)
        if ok and isServer() then sendRemoveItemFromContainer(source,item);sendAddItemToContainer(destination,item) end
        return ok,err
    end
    function h.discoverIfDue()
        if not h.nextDiscovery or h.now()>=h.nextDiscovery then h.discover() end
    end
    -- Only graph dependencies invalidate prepared simulation data.
    function h.generationFor(index)
        if h.dependencyIndex~=index or h.dependencyRegistry~=h.generation then
            local objects={}
            for id in pairs(index.byBody) do objects['b:'..id]=h.availableBodies and h.availableBodies[id] or false end
            for id in pairs(index.byVehicle) do objects['v:'..id]=h.vehicles[id] or false end
            for id in pairs(index.byHorse) do objects['h:'..id]=h.horses and h.horses[id] or false end
            if not sameObjects(h.dependencies,objects) then h.linkGeneration=(h.linkGeneration or 0)+1 end
            h.dependencies=objects;h.dependencyIndex=index;h.dependencyRegistry=h.generation
        end
        return h.linkGeneration
    end
    function h.discover()
        h.nextDiscovery=h.now()+1000
        local bodies,cars,horses={},{},{}
        for _,horse in ipairs(Horse.all()) do if horse:getSquare() then
            local id=Horse.key(horse)
            if horses[id]~=nil and horses[id]~=horse then horses[id]=false else horses[id]=horse end
        end end
        for id,horse in pairs(horses) do Horse.remember(id,horse) end
        if CVPNetwork then local all=CVPNetwork.bodies()
            for i=0,all:size()-1 do local b=all:get(i);local id=b:getModData().CVPBodyKey
                if key(id) then
                    if bodies[id]~=nil and bodies[id]~=b then bodies[id]=false else bodies[id]=b end
                end
            end
        end
        local vehicles=getCell():getVehicles():iterator()
        while vehicles:hasNext() do local v=vehicles:next()
            if v:getSquare() then
                local id=v:getModData().CVPVehicleKey
                if key(id) then if cars[id]~=nil and cars[id]~=v then cars[id]=false else cars[id]=v end end
                -- Native database IDs survive reload; new links need no extra
                -- vehicle-modData write just to establish an identity.
                local sql=v:getSqlId()
                if sql and sql>0 then local name='sql:'..tostring(sql)
                    if cars[name]~=nil and cars[name]~=v then cars[name]=false else cars[name]=v end
                end
            end
        end
        -- Discovery runs periodically even when membership is unchanged. Keep
        -- simulation paths and skeleton clocks until identity/availability changes.
        -- Availability needs its own snapshot: the same native body can unload
        -- or leave its square's corpse list without changing object identity.
        local available={}
        for id,b in pairs(bodies) do
            available[id]=b and World.towable(b) and b:getSquare()~=nil
                and b:getStaticMovingObjectIndex()>=0 and b or false
        end
        if not sameObjects(h.horses or {},horses) or not sameObjects(h.bodies,bodies) or not sameObjects(h.vehicles,cars)
            or not sameObjects(h.availableBodies,available) then
            h.generation=(h.generation or 0)+1
        end
        h.bodies=bodies;h.vehicles=cars;h.horses=horses;h.availableBodies=available
    end
    function h.horse(ref)
        local horse=h.horses and h.horses[ref.key]
        if horse==false then return end
        if horse and Horse.key(horse)==ref.key and horse:getSquare() then return horse end
        return Horse.dead(ref.key)
    end
    function h.body(ref,readPass)
        local b;if key(ref.key) then b=h.bodies[ref.key] end
        if b==false then return nil,'body identity ambiguous' end -- Never bypass with a native ID.
        -- A chunk reload can replace the cached object before periodic discovery.
        -- Keep the native fallback subject to the same persistent-key checks below.
        if not World.towable(b) or not World.present(b,readPass) then
            if not P.id(ref.native) or not CVPNetwork then
                return nil,not b and 'body not found' or not World.towable(b) and 'body not towable' or 'body unloaded'
            end
            b=CVPNetwork.find(ref.native)
            if not b then return nil,'body not found' end
            if not World.towable(b) then return nil,'body not towable' end
            if not World.present(b,readPass) then return nil,'body unloaded' end
        end
        local bodyKey=b:getModData().CVPBodyKey
        if h.bodies[bodyKey]==false then return nil,'body identity ambiguous' end
        if ref.key and bodyKey~=ref.key then return nil,'body identity mismatch' end
        return b
    end
    -- Only actions retry discovery; simulation/render lookups stay bounded.
    function h.retryBody(ref)
        local b,reason=h.body(ref)
        if not b and (reason=='body not found' or reason=='body unloaded') then
            h.discover()
            b,reason=h.body(ref)
        end
        return b,reason
    end
    -- The caller owns this transient reference, never a persisted graph endpoint.
    function h.actionBody(ref)
        local b,reason=h.retryBody(ref)
        if b then
            local id=b:getModData().CVPBodyKey
            if key(id) then ref.key=id end
            ref.native=CVPNetwork.id(b)
        end
        return b,reason
    end
    -- Preparation replies are authoritative, but may only name the selected body.
    function h.confirmBody(ref,confirmed)
        if not key(confirmed.key) or not P.id(confirmed.native)
            or ref.key and ref.key~=confirmed.key
            or not ref.key and ref.native~=confirmed.native then return false,'body identity mismatch' end
        h.discover()
        local b,reason=h.body(ref);if not b then return false,reason end
        local existing=h.bodies[confirmed.key]
        if existing==false or existing and existing~=b then return false,'body identity ambiguous' end
        local data=b:getModData()
        if data.CVPBodyKey and data.CVPBodyKey~=confirmed.key then return false,'body identity mismatch' end
        data.CVPBodyKey=confirmed.key;h.bodies[confirmed.key]=b
        ref.key=confirmed.key;ref.native=CVPNetwork.id(b)
        return true
    end
    function h.vehicle(ref)
        local v;if key(ref.key) then v=h.vehicles[ref.key] end
        if v==false then return end
        if not v and P.integer(ref.native) then
            local all=getCell():getVehicles():iterator()
            while all:hasNext() do local candidate=all:next()
                if candidate:getId()==ref.native then v=candidate;break end
            end
        end
        if not v or not v:getSquare() then return end
        local sql=v:getSqlId();local id=sql and sql>0 and ('sql:'..tostring(sql)) or nil
        local vehicleKey=v:getModData().CVPVehicleKey
        if h.vehicles[id]==false or h.vehicles[vehicleKey]==false then return end
        if ref.key and ref.key~=id and ref.key~=vehicleKey then return end
        return v
    end
    function h.bodyPoint(b,point)
        local poses=h.poses[b]
        if not poses then poses={};h.poses[b]=poses end
        local r=poses[point]
        if not r then r={body=b,point=point};Geometry.capture(r);poses[point]=r end
        r.x=b:getX();r.y=b:getY();r.z=b:getZ();r.angle=b:getAngle()
        local x,y,z=Rope.feet(r)
        return {kind='body',key=b:getModData().CVPBodyKey,point=point,x=x,y=y,z=z}
    end
    function h.canReach(p,e)
        local square=getCell():getGridSquare(math.floor(e.x),math.floor(e.y),math.floor(e.z))
        return square and p:getSquare() and p:getSquare():canReachTo(square) or false
    end
    function h.ground(e) return {x=e.x,y=e.y,z=math.floor(e.z)+Rope.floorHeight} end
    function h.resolve(ref,p)
        if type(ref)~='table' then return nil,'invalid target' end
        if ref.kind=='ground' then
            if not p:getSquare() then return nil,'unloaded endpoint' end
            return {kind='ground',x=p:getX(),y=p:getY(),z=math.floor(p:getZ())+Rope.floorHeight}
        elseif ref.kind=='body' then
            if ref.point~=nil and ref.point~='feet' and ref.point~='neck' then return nil,'invalid attachment point' end
            local b,reason=h.actionBody(ref);if not b then return nil,reason end
            if World.foreignTowed(b) or b:isBeingGrappled() then return nil,'body in use' end
            if b:getModData().CVPTether then return nil,'legacy attachment pending migration' end
            if b:isPlayer() and not World.playerBodiesAllowed() then return nil,'player bodies disabled' end
            local data=b:getModData()
            if not key(data.CVPBodyKey) then data.CVPBodyKey=h.uuid();h.confirmed[b]=false end
            h.bodies[data.CVPBodyKey]=b
            ref.key=data.CVPBodyKey
            return h.bodyPoint(b,ref.point or 'feet')
        elseif ref.kind=='horse' then
            if not Horse.enabled() then return nil,'IGUI_CVP_HorseDisabled' end
            local horse=h.horse(ref)
            if not horse then return nil,'unloaded endpoint' end
            if not Horse.stopped(horse) then return nil,'IGUI_CVP_StopHorse' end
            return Horse.sample(horse)
        elseif ref.kind=='vehicle' then
            if ref.point~=nil and ref.point~='hitch' and ref.point~='front' then return nil,'invalid attachment point' end
            local v=h.vehicle(ref);if not v then return nil,'vehicle unavailable' end
            if math.abs(v:getCurrentSpeedKmHour())>1 then return nil,'stop vehicle' end
            local sql=v:getSqlId();if not sql or sql<=0 then return nil,'vehicle not saved yet' end
            local id=ref.key or ('sql:'..tostring(sql));h.vehicles[id]=v
            local point=ref.point or 'hitch'
            local x,y,z=Geometry.anchor(v,point)
            return {kind='vehicle',key=id,point=point,x=x,y=y,z=z+Rope.anchorHeight}
        end
        return nil,'invalid target'
    end
    function h.ensure(e)
        if e.kind~='body' then return true end
        local b,reason=h.retryBody(e);if not b then return false,reason end
        if h.confirmed[b]~=true then
            local ok,confirmed=require('CVP_SaveJobs').call('checkpointSquare',b:getSquare())
            if not ok or confirmed~=true then return false,'body identity save not confirmed' end
            h.confirmed[b]=true
        end
        return true
    end
    function h.actionSample(e)
        if e.kind~='body' then return h.sample(e) end
        local b,reason=h.actionBody(e)
        if b then return h.bodyPoint(b,e.point) end
        return nil,reason
    end
    function h.sample(e)
        if e.kind=='horse' then return Horse.sample(h.horse(e))
        elseif e.kind=='body' then
            local b,reason=h.body(e)
            if b then return h.bodyPoint(b,e.point) end;return nil,reason
        elseif e.kind=='vehicle' then local v=h.vehicle(e);if v then local x,y,z=Geometry.anchor(v,e.point)
            return {kind='vehicle',key=e.key,point=e.point or 'hitch',x=x,y=y,z=z+Rope.anchorHeight} end
        elseif e.kind=='held' then local p=h.players[e.holder]
            if p and not p:isDead() and not p:getVehicle() and not Horse.mounted(p) and p:getSquare() then
                return {kind='held',holder=e.holder,x=p:getX(),y=p:getY(),z=math.floor(p:getZ())+Rope.floorHeight}
            end
        elseif e.kind=='joint' then return h.joints and h.joints[e.key] or e
        elseif e.kind=='ground' then return h.freeEnds and h.freeEnds[e] or {kind='ground',x=e.x,y=e.y,z=e.z} end
        return nil,'unloaded endpoint'
    end
    function h.samples(graph)
        local samples,holders={},{}
        -- Post-movement snapshot only. Resolve every reference (including native
        -- fallback and ambiguous IDs), but read each object's attachment once.
        -- Never reuse these coordinates in simulation or the next snapshot.
        local points={}
        local function sample(e)
            if e.kind~='body' and e.kind~='vehicle' then return h.sample(e) end
            local object
            if e.kind=='body' then object=h.body(e) else object=h.vehicle(e) end
            if not object then return end
            local rows=points[object];if not rows then rows={};points[object]=rows end
            local point=e.point or (e.kind=='vehicle' and 'hitch')
            local p=rows[point]
            if not p then
                if e.kind=='body' then p=h.bodyPoint(object,point)
                else local x,y,z=Geometry.anchor(object,point);p={x=x,y=y,z=z+Rope.anchorHeight} end
                rows[point]=p
            end
            -- Distinct result rows preserve the existing snapshot ownership contract.
            return {kind=e.kind,key=e.kind=='body' and p.key or e.key,point=point,x=p.x,y=p.y,z=p.z}
        end
        for id,link in pairs(graph.links) do
            samples[id]={a=sample(link.a),b=sample(link.b)}
            for _,side in ipairs({'a','b'}) do local e=link[side]
                if e.kind=='held' then holders[e.holder]=samples[id][side]~=nil end
            end
        end
        return samples,holders
    end
    return h
end
return H
