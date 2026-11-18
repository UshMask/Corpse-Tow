-- Dedicated disposable stand only; never shipped with Corpse Tow.
if not isServer() then return end
local marker=getFileReader('CVPMPTest-enabled.txt',false)
if not marker then return end
local enabled=marker:readLine()=='ecea4c1b';marker:close()
if not enabled then return end
local T={};CVPMPTestServer=T
local TAG='CVPMPTest'
local function owned(o) return o and o:getModData()[TAG]==true end
local function state() return ModData.getOrCreate(TAG) end
local function authority()
    assert(CVPMPServer and CVPMPServer.authority.started and not CVPMPServer.error,'Corpse Tow not ready')
    local r=CVPMPServer.authority
    assert(not r.saveJob and #r.saveQueue==0,'wait for pending material operations')
    r.host.discover();return r
end
local function admin(p)
    return p and tostring(p:getAccessLevel()):lower()=='admin' and not p:isDead()
end
local function items(inv,fn)
    local list=inv:getItems()
    for i=0,list:size()-1 do
        local item=list:get(i);fn(item)
        if instanceof(item,'InventoryContainer') then items(item:getInventory(),fn) end
    end
end
local function objects()
    local bodies,vehicles={},{}
    local all=CVPNetwork.bodies()
    for i=0,all:size()-1 do local b=all:get(i)
        if owned(b) then
            assert(not b:isPlayer(),'player corpse cannot be a fixture')
            assert(b:getSquare() and b:getStaticMovingObjectIndex()>=0,'fixture body unloaded')
            bodies[#bodies+1]=b
        end
    end
    local cars=getCell():getVehicles():iterator()
    while cars:hasNext() do local v=cars:next()
        if owned(v) then vehicles[#vehicles+1]=v end
    end
    local saved=state()
    assert(#bodies==(saved.count or 0) and #vehicles==(saved.vehicle and 1 or 0),
        'fixture objects missing: return to the scene; no reset was performed')
    return bodies,vehicles
end
local function links(r,bodies,vehicles)
    local keys={}
    for _,b in ipairs(bodies) do keys['body:'..tostring(b:getModData().CVPBodyKey)]=true end
    for _,v in ipairs(vehicles) do keys['vehicle:'..tostring(r.host.vehicleKey(v))]=true end
    local ends={}
    for id,link in pairs(r.service.graph.links) do
        local a=keys[link.a.kind..':'..tostring(link.a.key)]
        local b=keys[link.b.kind..':'..tostring(link.b.key)]
        local gear=require('CVP_Equipment').get(link.equipment)
        if a or b or owned(gear) then
            assert(owned(gear),'non-fixture material attached; detach it manually first')
            for _,e in ipairs({link.a,link.b}) do
                if e.kind=='body' or e.kind=='vehicle' or e.kind=='horse' then
                    assert(keys[e.kind..':'..tostring(e.key)],'fixture connected to a foreign object')
                end
            end
            ends[#ends+1]={id=id,revision=link.revision,side=a and 'a' or 'b'}
        end
    end
    table.sort(ends,function(a,b) return a.id<b.id end);return ends
end
function T.plan(p,count)
    assert(admin(p),'admin required')
    assert(count==0 or count==1 or count==32,'count must be 0, 1 or 32')
    assert(not p:getVehicle(),'leave the vehicle first')
    local r=authority();local bodies,vehicles=objects()
    return {count=count,ends=links(r,bodies,vehicles)}
end
function T.reset(p,count)
    local plan=T.plan(p,count)
    assert(#plan.ends==0,'detach fixture links before resetting')
    assert(math.abs(p:getX()-128)<35 and math.abs(p:getY()-220)<35 and p:getZ()==0,'stand near 128,220,0')
    local bodies,vehicles=objects()
    for _,b in ipairs(bodies) do items(b:getContainer(),function(i) assert(owned(i),'foreign loot in fixture body') end) end
    for _,v in ipairs(vehicles) do
        assert(math.abs(v:getCurrentSpeedKmHour())<1,'stop fixture vehicle')
        for seat=0,v:getMaxPassengers()-1 do assert(not v:getCharacter(seat),'fixture vehicle occupied') end
        for i=0,v:getPartCount()-1 do local c=v:getPartByIndex(i):getItemContainer()
            if c then items(c,function(item) assert(owned(item),'foreign items in vehicle') end) end
        end
    end
    local squares={}
    local carSquare=assert(getCell():getGridSquare(128,240,0),'vehicle square unloaded')
    for i=1,count do
        local x=128;local y=235-math.floor((i-1)*1.25)
        local sq=assert(getCell():getGridSquare(x,y,0),'fixture square unloaded')
        assert(not sq:isSolid() and not sq:isSolidTrans(),'fixture square blocked');squares[i]=sq
    end
    -- Validation above completes before deleting any disposable object.
    for _,b in ipairs(bodies) do b:getSquare():removeCorpse(b,false) end
    for _,v in ipairs(vehicles) do v:permanentlyRemove() end
    local saved=state();saved.count=0;saved.vehicle=false
    local oldGear={};items(p:getInventory(),function(item) if owned(item) and item:getFullType()=='Base.Rope' then oldGear[#oldGear+1]=item end end)
    for _,item in ipairs(oldGear) do
        local c=item:getContainer();sendRemoveItemFromContainer(c,item);c:Remove(item)
    end
    local vehicle=assert(addVehicleDebug('Base.SUV',IsoDirections.S,nil,carSquare),'vehicle creation failed')
    vehicle:getModData()[TAG]=true;saved.vehicle=true;vehicle:repair();vehicle:setHotwired(true)
    for i=0,vehicle:getPartCount()-1 do local part=vehicle:getPartByIndex(i)
        if part:getDoor() then part:getDoor():setLocked(false);vehicle:transmitPartDoor(part) end
        if part:getContainerContentType()=='Gasoline' then part:setContainerContentAmount(part:getContainerCapacity()) end
        local c=part:getItemContainer();if c then items(c,function(item) item:getModData()[TAG]=true end) end
    end
    local players=getOnlinePlayers()
    for i=0,players:size()-1 do local player=players:get(i)
        local key=vehicle:createVehicleKey();key:getModData()[TAG]=true
        player:getInventory():AddItem(key);sendAddItemToContainer(player:getInventory(),key)
    end
    local spawned,refs,gear={},{},{}
    for _,sq in ipairs(squares) do
        local b=assert(createRandomDeadBody(sq,0),'corpse creation failed')
        b:getModData()[TAG]=true;saved.count=saved.count+1
        b:setFakeDead(false);b:setReanimateTime(-1)
        items(b:getContainer(),function(item) item:getModData()[TAG]=true end)
        local watch=b:getContainer():AddItem('Base.WristWatch_Right_DigitalBlack');watch:getModData()[TAG]=true
        spawned[#spawned+1]=b
    end
    local h=CVPMPServer.authority.host
    if #spawned>0 then h.discover() end -- One trusted fixture scan after all corpses exist.
    for _,b in ipairs(spawned) do
        local native=CVPNetwork.id(b)
        local ref=assert(h.resolve({kind='body',native=native,point='feet'},p))
        ref.native=native;refs[#refs+1]=ref;sendCorpse(b)
        local rope=p:getInventory():AddItem('Base.Rope');rope:getModData()[TAG]=true
        sendAddItemToContainer(p:getInventory(),rope);gear[#gear+1]=rope:getID()
    end
    saved.count=count;saved.owner=p:getUsername()
    print('[CVP MPTest] scene count='..count..' vehicle='..vehicle:getId())
    return {count=count,vehicle=vehicle:getId(),targets=refs,gear=gear}
end
Events.OnClientCommand.Add(function(module,command,p,args)
    if module~='CVPMPTest' or not admin(p) or type(args)~='table' then return end
    if command~='plan' and command~='reset' then return end
    local ok,result=pcall(T[command],p,args.count)
    sendServerCommand(p,'CVPMPTest',command,{ok=ok,result=ok and result or nil,error=not ok and tostring(result) or nil})
end)
-- Only loaded on the explicitly marked disposable server. Reapply after reconnect.
local safetyAt=0
Events.OnTick.Add(function()
    local now=getTimestampMs();if now<safetyAt then return end;safetyAt=now+1000
    local players=getOnlinePlayers()
    for i=0,players:size()-1 do local p=players:get(i)
        p:setGodMod(true)
        sendServerCommand(p,'CVPMPTest','safety',{ok=true})
    end
end)
print('[CVP MPTest] enabled; admin scene commands ready')
