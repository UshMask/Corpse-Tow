-- Gameplay acceptance scenes, separate from frame sampling and production code.
require 'CVP_Benchmark'
local A=require 'PZT_Control'
local B=CVPBenchmark
local function runtime()
    assert(CVPRuntime and not CVPRuntime.error and not CVPRuntime.visualError,'runtime error or unavailable')
    local r=CVPRuntime.authority;r.host.discover();return r.service,r.host
end
local function count(rows) local n=0;for _ in pairs(rows) do n=n+1 end;return n end
local function expectation() return assert(getPlayer():getModData().PZTAcceptance,'scene not prepared') end
local function validate(rebound)
    local e=expectation();local s,h=runtime()
    if getWorld():getWorld()=='PZT_VehicleLab' then
        assert(getWorld():getMap()=='PZT_ProvingGround','wrong map loaded')
        assert(e.map=='PZT_ProvingGround','old scene snapshot rejected')
    end
    assert(count(s.graph.links)==e.count,'unexpected link count')
    local v=assert(h.vehicle(e.vehicle),'saved vehicle missing')
    local bodies={}
    for i,id in ipairs(e.links) do
        local row=assert(s.graph.links[id],'saved link missing')
        local expected=e.rows[i]
        for _,side in ipairs({'a','b'}) do
            local a,b=row[side],expected[side]
            assert(a.kind==b.kind and a.key==b.key and a.point==b.point,'attachment changed')
        end
        assert(row.equipment==expected.equipment and row.material=='Base.Rope','rope identity changed')
        if rebound and i==1 then
            -- Binding retensions the root to its current endpoint distance.
            -- The stored item must be unchanged and its capacity respected.
            assert(row.length>=.1 and row.length<=require('CVP_LinkGraph').capacityFor(row),'rebound rope exceeds capacity')
        else assert(math.abs(row.length-expected.length)<.001,'rope length changed') end
        local item=assert(require('CVP_Equipment').get(row.equipment),'stored rope missing')
        assert(item:getID()==e.gear[i],'original rope item lost')
        assert(not getPlayer():getInventory():getItemWithID(e.gear[i]),'rope duplicated into inventory')
        bodies[i]=assert(h.body({kind='body',key=e.bodyKeys[i]}),'saved body missing')
        if getWorld():getWorld()=='PZT_VehicleLab' then
            assert(bodies[i]:isZombie()==(e.count==1 or i%2==1),'saved body type changed')
            assert(not bodies[i]:isPlayer(),'player body in fixture')
        end
        assert(bodies[i]:getStaticMovingObjectIndex()>=0,'body not registered in square')
    end
    return e,s,h,v,bodies
end
local function guard()
    if isClient() or isServer() or not getPlayer() or (getWorld():getWorld()~='CVP_QuickTest' and getWorld():getWorld()~='PZT_VehicleLab') then return 'isolated SP world required' end
    if B.sample then return 'sampling is active' end
    if not CVPRuntime then return 'Corpse Tow required' end
end
A.register('scene.initialize',function(arg)
    local n=tonumber(arg);assert(n==1 or n==4,'supported scenes: 1 or 4 bodies')
    if getWorld():getWorld()=='PZT_VehicleLab' then
        assert(not getPlayer():getModData().PZTAcceptance,'scene already prepared')
        assert(getWorld():getMap()=='PZT_ProvingGround','wrong map loaded')
        local square=assert(getCell():getGridSquare(n==1 and 120 or 144,220,0),'lab square missing')
        assert(square:getFloor() and square:getFloor():getSprite():getName()=='blends_street_01_86','proving ground floor missing')
        assert(not square:isSolid() and not square:isSolidTrans(),'lab vehicle square obstructed')
        local v=assert(addVehicleDebug('Base.SUV',IsoDirections.N,nil,square),'lab vehicle spawn failed')
        v:repair();v:setForceBrake();v:setPhysicsActive(false)
    end
    return {stage='spawned',map=getWorld():getMap()}
end,{validate=guard})
A.register('scene.prepare',function(arg)
    local n=tonumber(arg);assert(n==1 or n==4,'supported scenes: 1 or 4 bodies')
    B.reset();B.setup(n,'chain')
    local s,h=runtime()
    local e={version=2,map=getWorld():getMap(),count=n,links={},gear={},rows={},bodyKeys={},positions={},origin=B.origin,
        vehicle={kind='vehicle',key=h.vehicleKey(B.vehicle),point='hitch'},carOrigin=B.carOrigin}
    for i,id in ipairs(B.links) do
        local row=assert(s.graph.links[id]);local body=B.bodies[i]
        e.links[i]=id;e.gear[i]=B.gear[i];e.bodyKeys[i]=body:getModData().CVPBodyKey
        e.positions[i]={x=body:getX(),y=body:getY()}
        e.rows[i]=require('CVP_LinkGraph').copy(row)
    end
    getPlayer():getModData().PZTAcceptance=e
    validate();save(true)
    MainScreen.instance:quitToDesktop()
    return {stage='prepared',map=e.map,count=n,links=e.links,gear=e.gear,bodyKeys=e.bodyKeys,vehicle=e.vehicle}
end,{validate=guard})
A.register('scene.stop',function()
    local e,s,h,v=validate()
    -- Movement is prescribed by the fixture, so clear its synthetic speed too.
    v:setForceBrake();v:setPhysicsActive(false);v:setSpeedKmHour(0)
    return {speed=v:getCurrentSpeedKmHour()}
end,{validate=guard})
A.register('scene.adopt',function()
    local e,s,h,v,bodies=validate()
    B.bodies=bodies;B.links=e.links;B.gear=e.gear;B.origin=e.origin;B.carOrigin=e.carOrigin
    B.vehicle=v;B.count=e.count;B.topology='chain';B.seedReady=true
    v:setForceBrake();v:setPhysicsActive(false)
    B.acceptancePositions={}
    for i,b in ipairs(bodies) do B.acceptancePositions[i]={x=b:getX(),y=b:getY()} end
    B.acceptanceVehicle={x=v:getX(),y=v:getY()}
    return {stage='reloaded',count=e.count,links=e.links,gear=e.gear,bodyKeys=e.bodyKeys}
end,{validate=guard})
A.register('scene.verify',function()
    local e,s,h,v,bodies=validate();local moved=0;local distances={}
    for i,b in ipairs(bodies) do local p=assert(B.acceptancePositions,'adopt scene before movement')[i]
        distances[i]=math.sqrt((b:getX()-p.x)^2+(b:getY()-p.y)^2)
        if distances[i]>.1 then moved=moved+1 end
    end
    assert(moved==e.count,'not all bodies moved under towing')
    local start=assert(B.acceptanceVehicle)
    local carDistance=math.sqrt((v:getX()-start.x)^2+(v:getY()-start.y)^2)
    assert(carDistance>.5,'vehicle did not move')
    local p=getPlayer();local root=s.graph.links[e.links[1]]
    B.beside(p,assert(h.sample(root.a)))
    local ok,why=s:command(p,{id=root.id,revision=root.revision,side='a',op='release'});assert(ok,why)
    assert(count(s.graph.links)==e.count,'detach lost links')
    root=s.graph.links[e.links[1]]
    B.beside(p,assert(h.sample(e.vehicle)))
    ok,why=s:command(p,{id=root.id,revision=root.revision,side='a',op='bind',target=e.vehicle});assert(ok,why)
    validate(true)
    for i=#e.links,1,-1 do
        local row=s.graph.links[e.links[i]]
        B.beside(p,assert(h.sample(row.a)))
        ok,why=s:command(p,{id=row.id,revision=row.revision,side='a',op='remove'});assert(ok,why)
    end
    assert(count(s.graph.links)==0,'connections remain after dismantling')
    for _,id in ipairs(e.gear) do assert(p:getInventory():getItemWithID(id),'original rope not returned') end
    -- clear() removes only this scene's returned items and registered bodies.
    B.clear()
    for _,body in ipairs(bodies) do assert(body:getStaticMovingObjectIndex()<0,'fixture body remains registered') end
    p:getModData().PZTAcceptance=nil
    save(true);MainScreen.instance:quitToDesktop()
    return {stage='passed',count=e.count,moved=moved,distances=distances,vehicleDistance=carDistance,reconnected=true,returned=#e.gear,remainingLinks=0}
end,{validate=guard})
