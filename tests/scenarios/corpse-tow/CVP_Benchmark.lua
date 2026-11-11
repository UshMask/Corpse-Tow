-- Development-only control and frame sampling; installed in isolated profiles.
local r=getFileReader('CVPBenchmark-mode.txt',false)
if not r then return end
local variant=r:readLine();r:close()
if variant~='On' and variant~='Off' then return end
local A=require 'PZT_Control'
local B={bodies={},links={},gear={}};CVPBenchmark=B
local function clock() return CVPBenchmarkNative.milliseconds() end
local function write(name,text)
    local f=getFileWriter(name,true,false)
    if not f then return false,'cannot open benchmark output: '..name end
    f:write(text);f:close();return true
end
local function reply(id,ok,text) A.complete(id,ok,text) end
local function guard()
    assert(not isClient() and not isServer() and (getWorld():getWorld()=='CVP_QuickTest' or getWorld():getWorld()=='PZT_VehicleLab'),'isolated single-player profile required')
    assert(getPlayer() and CVPBenchmarkNative,'world or benchmark native helper unavailable')
end
local function beside(p,e)
    local z=math.floor(e.z)
    p:setX(e.x);p:setY(e.y);p:setZ(z)
    local square=assert(getCell():getGridSquare(math.floor(e.x),math.floor(e.y),z),'fixture square unloaded')
    p:setCurrent(square)
end
local function removableBody(body)
    return body:isZombie() or (getWorld():getWorld()=='PZT_VehicleLab'
        and body:getModData().PZTFixture==true and not body:isPlayer())
end
local function resetSeed()
    guard();assert(not B.sample,'measurement already running')
    local p=getPlayer();local v=p:getVehicle()
    if v then local seat=v:getSeat(p);v:exit(p);v:setCharacterPosition(p,seat,'outside');triggerEvent('OnExitVehicle',p) end
    local origin={x=p:getX(),y=p:getY(),z=p:getZ()}
    if CVPRuntime then
        SandboxVars.CorpseProxyLab.BodyWear=false
        -- This adapter only loads in the disposable benchmark world. Recover old
        -- connections through the normal service before removing their bodies.
        local s=CVPRuntime.authority.service;local h=CVPRuntime.authority.host
        local rows={};local equipment={}
        for id,row in pairs(s.graph.links) do
            rows[#rows+1]=id
            local item=require('CVP_Equipment').get(row.equipment)
            assert(item,'saved tether item unavailable')
            equipment[row.equipment]=item:getID()
        end
        table.sort(rows)
        for _,id in ipairs(rows) do local row=s.graph.links[id]
            local endpoint=h.sample(row.a);local side='a'
            if not endpoint then endpoint=h.sample(row.b);side='b' end
            beside(p,assert(endpoint,'saved tether endpoint unavailable'))
            assert(s:command(p,{id=id,revision=row.revision,side=side,op='remove'}))
        end
        for _,id in pairs(equipment) do
            assert(p:getInventory():getItemWithID(id),'saved tether not returned')
        end
    end
    beside(p,origin)
    local removed=0
    for x=math.floor(origin.x)-40,math.floor(origin.x)+40 do
        for y=math.floor(origin.y)-40,math.floor(origin.y)+40 do
            local square=getCell():getGridSquare(x,y,math.floor(origin.z))
            if square then local bodies=square:getDeadBodys()
                for i=bodies:size()-1,0,-1 do local b=bodies:get(i)
                    assert(removableBody(b),'unowned human corpse in fixture; refusing cleanup')
                    square:removeCorpse(b,false);removed=removed+1
                end
            end
        end
    end
    B.bodies={};B.links={};B.gear={};B.origin=origin;B.count=nil;B.seedReady=true
    return 'seed cleared bodies='..removed
end
local function clear()
    if CVPRuntime then local s=CVPRuntime.authority.service;local h=CVPRuntime.authority.host
        for _,id in ipairs(B.links) do local row=s.graph.links[id]
            if row then beside(getPlayer(),assert(h.sample(row.a)))
                assert(s:command(getPlayer(),{id=id,revision=row.revision,side='a',op='remove'})) end
        end
    end
    B.links={}
    for _,id in ipairs(B.gear) do
        local inventory=getPlayer():getInventory()
        local gear=assert(inventory:getItemWithID(id),'fixture tether not returned')
        inventory:Remove(gear)
    end
    B.gear={}
    for _,b in ipairs(B.bodies) do
        local square=b:getSquare()
        if square and b:getStaticMovingObjectIndex()>=0 then square:removeCorpse(b,false) end
    end
    B.bodies={}
end
local function setup(count,topology)
    guard();assert(B.seedReady,'reset the copied seed before preparing measurements')
    assert(not B.sample,'measurement already running');assert(count>=0 and count<=128)
    B.count=nil -- A partially prepared scene must never be measured.
    local p=getPlayer();B.origin=B.origin or {x=p:getX(),y=p:getY(),z=p:getZ()}
    clear();beside(p,B.origin);p:setGodMod(true);p:setGhostMode(true)
    getGameTime():setTimeOfDay(12);setGameSpeed(1)
    local vehicles=getCell():getVehicles():iterator();local best,d
    while vehicles:hasNext() do local v=vehicles:next()
        local dist=(v:getX()-p:getX())^2+(v:getY()-p:getY())^2
        if not d or dist<d then best=v;d=dist end
    end
    assert(best and d<400,'park a saved vehicle near the fixture');B.vehicle=best
    best:setForceBrake();best:setPhysicsActive(false)
    B.carOrigin=B.carOrigin or {x=best:getX(),y=best:getY()}
    local resetX,resetY=best:getX(),best:getY()
    for _=1,100 do local dx,dy=B.carOrigin.x-resetX,B.carOrigin.y-resetY
        if math.abs(dx)+math.abs(dy)<.01 then break end
        local f=math.min(1,.5/(math.abs(dx)+math.abs(dy)))
        CVPBenchmarkNative.moveVehicle(best,dx*f,dy*f)
        resetX=resetX+dx*f;resetY=resetY+dy*f
    end
    local v=Vector3f.new()
    if best:attachmentExist('trailer') then best:getAttachmentWorldPos('trailer',v)
    else best:getWorldPos(0,0,-best:getScript():getExtents():z()/2,v) end
    local ax,ay=v:x(),v:y()
    -- Identical fixture layout for the mod-off profile, based on the saved vehicle.
    B.anchor=B.anchor or {x=ax,y=ay}
    local sx,sy=math.floor(B.anchor.x)-4,math.floor(B.anchor.y)+2
    for i=1,count do
        local x,y=sx+(i-1)%8,sy+math.floor((i-1)/8)*.4
        local square=assert(getCell():getGridSquare(math.floor(x),math.floor(y),0),'fixture square unloaded')
        assert(not square:isSolid() and not square:isSolidTrans(),'fixture obstructed')
        local b
        if getWorld():getWorld()=='PZT_VehicleLab' then
            if count>1 and i%2==0 then
                b=assert(createRandomDeadBody(square,0),'fixture human corpse factory returned nil')
                assert(not b:isZombie() and not b:isPlayer(),'expected non-player human corpse')
            else
                local spawned=addZombiesInOutfit(math.floor(x),math.floor(y),0,1,nil,50)
                assert(spawned and spawned:size()==1,'fixture zombie spawn failed')
                b=assert(square:createCorpse(spawned:get(0),false),'fixture corpse factory returned nil')
                assert(b:isZombie(),'expected zombie corpse')
            end
            b:getModData().PZTFixture=true
        else b=assert(square:createCorpse(false)) end
        b:setFakeDead(false);b:setReanimateTime(-1)
        local old=b:getSquare();if old and b:getStaticMovingObjectIndex()>=0 then old:removeCorpse(b,false) end
        b:setX(x+.1);b:setY(y+.1);b:setZ(0);b:setSquare(square);square:addCorpse(b,false)
        B.bodies[#B.bodies+1]=b
    end
    if topology~='loose' then
        assert(CVPRuntime and not CVPRuntime.error,'Corpse Tow unavailable')
        SandboxVars.CorpseProxyLab.MaxBodiesPerChain=0
        local h=CVPRuntime.authority.host;local s=CVPRuntime.authority.service;h.discover()
        local car={kind='vehicle',key=h.vehicleKey(best),point='hitch'};local previous=car
        for _,body in ipairs(B.bodies) do
            local target=assert(h.resolve({kind='body',native=CVPNetwork.id(body),point='feet'},p))
            local source=topology=='chain' and previous or car
            local gear=p:getInventory():AddItem('Base.Rope')
        B.gear[#B.gear+1]=gear:getID()
            beside(p,assert(h.sample(source)));local token=assert(s:prepare(p,source,gear:getID()))
            beside(p,target);local ok,id=s:create(p,token,target);assert(ok,id)
            B.links[#B.links+1]=id;previous=target
        end
    end
    beside(p,B.origin);B.count=count;B.topology=topology
end
local function finish()
    local s=B.sample;B.sample=nil
    if B.perf then assert(write('CVPBenchmark-'..s.id..'-present.txt',PZTPresentedFrames.finish())) end
    local lines={'frame_ms,tick_ms,heap_mb'}
    for _,row in ipairs(s.frames) do lines[#lines+1]=string.format('%.6f,%.6f,%.3f',row[1],row[2],row[3]) end
    local ok,why=write('CVPBenchmark-'..s.id..'-frames.txt',table.concat(lines,'\n'))
    if not ok then reply(s.id,false,why);return end
    local moved=0
    for i,b in ipairs(B.bodies) do local p=s.positions[i]
        if (b:getX()-p.x)^2+(b:getY()-p.y)^2>.01 then moved=moved+1 end
    end
    ok,why=write('CVPBenchmark-'..s.id..'-meta.txt',table.concat({
        'variant='..variant,'count='..B.count,'topology='..B.topology,'motion='..s.motion,
        'frames='..#s.frames,'movedBodies='..moved,'links='..#B.links,
        'zoom='..getCore():getZoom(0),'width='..getCore():getScreenWidth(),'height='..getCore():getScreenHeight(),
        'vehicleStartX='..s.vehicleX,'vehicleEndX='..B.vehicle:getX(),
        'clock=System.nanoTime','frameEvent=OnRenderTick'},'\n'))
    if not ok then reply(s.id,false,why);return end
    reply(s.id,true,'done frames='..#s.frames..' variant='..variant..' count='..B.count..' topology='..B.topology..' motion='..s.motion)
end
B.reset=resetSeed;B.setup=setup;B.clear=clear;B.beside=beside
local function command(id,op,arg,topology,motion)
    if op=='status' then return 'variant='..variant..' world='..tostring(getPlayer()~=nil)..' native='..tostring(CVPBenchmarkNative~=nil)..' active='..tostring(B.sample~=nil)..' error='..tostring(CVPRuntime and CVPRuntime.error) end
    guard()
    if op=='close' then
        MainScreen.instance:quitToDesktop()
        return 'client closing normally'
    end
    if op=='seal' then
        resetSeed();setup(0,'loose')
        save(true)
        local ok,why=write('CVPBenchmark-seed.txt','version=1\nworld=CVP_QuickTest\nbodies=0\nlinks=0\nvehicle=true\nsession='..A.session)
        assert(ok,why)
        MainScreen.instance:quitToDesktop()
        return 'clean seed saved; client closing'
    end
    if op=='reset' then return resetSeed() end
    if op=='escape' then ToggleEscapeMenu(getCore():getKey(KeybindId.MAIN_MENU));return 'escape menu toggled' end
    if op=='pause' or op=='resume' then
        local visible=MainScreen.instance and MainScreen.instance.inGame and MainScreen.instance:isVisible()
        if visible~=(op=='pause') then ToggleEscapeMenu(getCore():getKey(KeybindId.MAIN_MENU)) end
        return 'paused='..tostring(MainScreen.instance:isVisible())
    end
    if op=='scene' then setup(assert(tonumber(arg)),topology or 'loose');return 'scene ready' end
    if op=='measure' then
        assert(not B.sample and B.count,'prepare a scene first')
        assert(not MainScreen.instance:isVisible() and getGameSpeed()==1,'resume normal game speed before measuring')
        assert(motion=='idle' or motion=='moving','invalid motion')
        local now=clock();local positions={}
        for i,b in ipairs(B.bodies) do positions[i]={x=b:getX(),y=b:getY()} end
        B.sample={id=id,start=now+10000,stop=now+30000,last=nil,frames={},motion=motion,origin=now,
            positions=positions,vehicleX=B.vehicle:getX()}
        return 'warming up 10s; sampling 20s',true
    end
    error('unknown command')
end
local function reject(op,arg,topology,motion)
    if op=='status' then return end
    if isClient() or isServer() or not getPlayer() or (getWorld():getWorld()~='CVP_QuickTest' and getWorld():getWorld()~='PZT_VehicleLab') then
        return 'load the isolated single-player test world first'
    end
    if op~='close' and op~='seal' and op~='reset' and op~='escape' and op~='pause' and op~='resume' and op~='scene' and op~='measure' then return 'unknown command' end
    if B.sample and (op=='seal' or op=='reset' or op=='scene' or op=='measure') then return 'measurement already running' end
    if op=='reset' or op=='seal' then
        if CVPRuntime then
            local h=CVPRuntime.authority.host
            for _,row in pairs(CVPRuntime.authority.service.graph.links) do
                if not h or not (h.sample(row.a) or (row.b and h.sample(row.b))) then return 'saved tether endpoint unavailable; seed cannot be cleaned' end
                if not require('CVP_Equipment').get(row.equipment) then return 'saved tether item unavailable; seed cannot be cleaned' end
            end
        end
        -- Validate the whole cleanup area before removing the first body.
        local p=getPlayer()
        for x=math.floor(p:getX())-40,math.floor(p:getX())+40 do
            for y=math.floor(p:getY())-40,math.floor(p:getY())+40 do
                local square=getCell():getGridSquare(x,y,math.floor(p:getZ()))
                if square then local bodies=square:getDeadBodys()
                    for i=0,bodies:size()-1 do if not removableBody(bodies:get(i)) then return 'player corpse in fixture; refusing cleanup' end end
                end
            end
        end
    elseif op=='scene' then
        local n=tonumber(arg)
        if not n or n~=math.floor(n) or n<0 or n>128 then return 'body count must be an integer from 0 to 128' end
        if topology~='loose' and topology~='chain' and topology~='individual' then return 'invalid topology' end
        if topology~='loose' and not CVPRuntime then return 'Corpse Tow required for attached bodies' end
        if not B.seedReady then return 'reset the copied seed before preparing measurements' end
    elseif op=='measure' then
        local writable,why=write('CVPBenchmark-write-check.txt','ready')
        if not writable then return why end
        if B.count==nil then return 'prepare a complete scene first' end
        if motion~='idle' and motion~='moving' then return 'invalid motion' end
        if MainScreen.instance:isVisible() or getGameSpeed()~=1 then return 'resume normal game speed before measuring' end
    end
end
for _,name in ipairs({'status','reset','seal','close','escape','pause','resume','scene','measure'}) do
    local op=name
    local function args(text)
        return text:match('^(%S+) (%S+) (%S+)$')
    end
    A.register('benchmark.'..op,function(text,id)
        local count,topology,motion=args(text)
        return command(id,op,count,topology,motion)
    end,{readonly=op=='status',validate=function(text)
        local count,topology,motion=args(text)
        return reject(op,count,topology,motion)
    end})
end
Events.OnRenderTick.Add(function()
    if not CVPBenchmarkNative then return end
    local now=clock()
    local s=B.sample;if not s then return end
    if MainScreen.instance:isVisible() or getGameSpeed()~=1 then
        B.sample=nil;reply(s.id,false,'measurement interrupted by pause or changed game speed');return
    end
    if CVPRuntime and (CVPRuntime.error or CVPRuntime.visualError) then
        B.sample=nil;reply(s.id,false,CVPRuntime.error or CVPRuntime.visualError);return
    end
    if now>=s.stop then
        local ok,why=pcall(finish)
        if not ok then B.sample=nil;reply(s.id,false,why) end
        return
    end
    if now>=s.start then
        if not s.last and B.perf then PZTPresentedFrames.begin() end
        if s.last then s.frames[#s.frames+1]={now-s.last,B.tickMS or 0,CVPBenchmarkNative.heapMB()} end
        s.last=now
    end
end)
Events.OnTick.Add(function()
    local s=B.sample
    if s and s.motion=='moving' then
        local target=B.carOrigin.x+5*math.sin((clock()-s.origin)/2500)
        local dx=math.max(-.2,math.min(.2,target-B.vehicle:getX()))
        local ok,why=pcall(CVPBenchmarkNative.moveVehicle,B.vehicle,dx,0)
        if not ok then B.sample=nil;reply(s.id,false,why) end
    end
end)
Events.OnGameStart.Add(function()
    -- Legacy interactive timing only; clean FPS/JFR uses no authority wrapper.
    if isDebugEnabled() and CVPRuntime then
        local old=CVPRuntime.authority.tick
        CVPRuntime.authority.tick=function(self,...)
            local start=clock();local ok,err=old(self,...);B.tickMS=clock()-start;return ok,err
        end
    end
end)
