-- Comparable saved fixtures. Corpse Tow is deliberately optional when adopting.
require 'CVP_Benchmark'
local A=require 'PZT_Control'
local B=CVPBenchmark
local profiling
local function profileFunction(owner,key,name,cpu)
    local old=assert(owner[key],name);local row={name=name,calls=0,inclusiveMS=0,selfMS=0}
    if cpu then
        row.cpuScope='current-thread-inclusive';row.cpuAvailable=profiling.cpuAvailable
        cpu=profiling.cpuAvailable
    end
    profiling.rows[#profiling.rows+1]=row
    profiling.restore[#profiling.restore+1]={owner=owner,key=key,old=old}
    owner[key]=function(...)
        local parent=profiling.current;local frame={children=0};profiling.current=frame
        local start=CVPBenchmarkNative.milliseconds()
        local cpuStart=cpu and CVPBenchmarkNative.cpuNanos() or -1
        local a,b,c,d,e,f=old(...)
        if cpuStart>=0 then
            local cpuEnd=CVPBenchmarkNative.cpuNanos()
            if cpuEnd>=cpuStart then
                row.cpuMS=(row.cpuMS or 0)+(cpuEnd-cpuStart)/1000000
                row.cpuSamples=(row.cpuSamples or 0)+1
            end
        end
        local elapsed=CVPBenchmarkNative.milliseconds()-start
        row.calls=row.calls+1;row.inclusiveMS=row.inclusiveMS+elapsed;row.selfMS=row.selfMS+elapsed-frame.children
        profiling.current=parent;if parent then parent.children=parent.children+elapsed end
        return a,b,c,d,e,f
    end
end
local function guard()
    if isClient() or isServer() or not getPlayer() or getWorld():getWorld()~='PZT_VehicleLab'
        or getWorld():getMap()~='PZT_ProvingGround' then return 'isolated proving ground required' end
    if B.sample then return 'measurement active' end
end
A.register('perf.environment',function()
    local grid=getWorld():getMetaGrid()
    return {debug=isDebugEnabled(),gameProfiler=CVPBenchmarkNative.gameProfilerEnabled(),
        mapWidth=grid:getWidth(),mapHeight=grid:getHeight(),mapHeaders=CVPBenchmarkNative.mapHeaderCount(),
        dynamicCorpseMove=CVPDynamicCorpses and CVPDynamicCorpses.canSkipMoveInvalidation() or false}
end,{validate=guard,readonly=true})
A.register('perf.gameprofiler',function(arg)
    if arg~='status' then CVPBenchmarkNative.gameProfiler(arg) end
    return {active=CVPBenchmarkNative.gameProfilerActive(),expired=CVPBenchmarkNative.gameProfilerExpired(),
        firstFrame=CVPBenchmarkNative.gameProfilerFirst(),lastFrame=CVPBenchmarkNative.gameProfilerLast()}
end,{validate=guard})
A.register('perf.profile.begin',function()
    assert(CVPRuntime and (B.perf=='Tow' or B.perf=='On') and not profiling,'adopt enabled mod scene first')
    local cpuAvailable=CVPBenchmarkNative.cpuNanos()>=0
    profiling={rows={},restore={},cpuAvailable=cpuAvailable,start=CVPBenchmarkNative.milliseconds()}
    -- A temporary proxy leaves the exposed Java class untouched. Count attempts,
    -- including failures; no point copies or per-point timers in the probe.
    local native=CVPFreeRopeScene
    if native then
        local uploads={calls=0,points=0,completed=0};profiling.uploads=uploads
        local proxy=setmetatable({}, {__index=function(_,key) return native[key] end})
        proxy.update=function(id,points,chain)
            uploads.calls=uploads.calls+1;uploads.points=uploads.points+#points
            native.update(id,points,chain)
            uploads.completed=uploads.completed+1
        end
        profiling.native=native;profiling.proxy=proxy;CVPFreeRopeScene=proxy
    end
    local stages={CVP_LinkSimulation={'tick','apply','build'},CVP_Core={'advance'},
        CVP_Geometry={'resolve','anchor'},CVP_LinkObstacles={'check'},CVP_Rope={'step','separate'},
        CVP_Load={'refresh','connect','tension'},CVP_World={'move'},CVP_Effects={'committed'},
        CVP_LinkJoints={'place','length'},CVP_LinkRuntime={'removedEnds','samples'},CVP_LinkService={'tick','refresh'}}
    for module,keys in pairs(stages) do for _,key in ipairs(keys) do
        profileFunction(require(module),key,module..'.'..key)
    end end
    if B.perf=='On' or B.perf=='Tow' then
        profileFunction(CVPRuntime.handlers,'OnTick','client.OnTick',true)
        for _,key in ipairs({'players','discover','skeletons'}) do
            profileFunction(CVPRuntime.authority,key,'authority.'..key)
        end
        profileFunction(CVPRuntime.presentation,'update','presentation.update',true)
        profileFunction(CVPRuntime.actions,'update','actions.update')
        profileFunction(require('CVP_Feedback'),'draw','feedback.draw')
    end
    profileFunction(CVPRuntime.authority.host,'sample','host.sample')
    profileFunction(CVPRuntime.authority,'tick','authority.tick',true)
    return 'profiling started'
end,{validate=guard})
A.register('perf.profile.end',function()
    assert(profiling,'profiling not active')
    local result={schema=2,scope='profile-cycle',durationMS=CVPBenchmarkNative.milliseconds()-profiling.start,
        rows=profiling.rows,ropeUploads=profiling.uploads}
    for _,entry in ipairs(profiling.restore) do entry.owner[entry.key]=entry.old end
    if profiling.proxy and CVPFreeRopeScene==profiling.proxy then CVPFreeRopeScene=profiling.native end
    profiling=nil;return result
end,{validate=guard})
A.register('perf.prepare',function(arg)
    local n=tonumber(arg);assert(n==1 or n==32,'supported counts: 1, 32')
    B.reset();B.setup(n,'loose')
    B.vehicle:setCharacterPosition(getPlayer(),0,'outside')
    B.beside(getPlayer(),{x=getPlayer():getX(),y=getPlayer():getY(),z=getPlayer():getZ()})
    local e={count=n,positions={},origin={x=getPlayer():getX(),y=getPlayer():getY(),z=getPlayer():getZ()},version=2}
    for i,b in ipairs(B.bodies) do
        b:getModData().PZTPerfIndex=i
        e.positions[i]={x=b:getX(),y=b:getY(),z=b:getZ(),zombie=b:isZombie()}
    end
    getPlayer():getModData().PZTAcceptance=nil
    getPlayer():getModData().PZTPerformance=e
    save(true);MainScreen.instance:quitToDesktop()
    return e
end,{validate=guard})
local function adopt(arg,restored,topology)
    local mode,preset=arg:match('^(%a+)%s*(%a*)$')
    assert(preset=='' or preset=='quick' or preset=='background','invalid test preset')
    assert(mode=='Off' or mode=='On' or mode=='Tow','invalid performance mode')
    assert((CVPRuntime~=nil)==(mode~='Off'),'loaded mod variant mismatch')
    local p=getPlayer();local e=assert(p:getModData().PZTPerformance,'performance snapshot missing')
    B.bodies={};B.links={};B.gear={};B.origin=e.origin;B.seedReady=true
    for i,pos in ipairs(e.positions) do
        local square=assert(getCell():getGridSquare(math.floor(pos.x),math.floor(pos.y),0),'saved body square missing')
        if restored then B.bodies[i]=restored[i]
        else
            local bodies=square:getDeadBodys()
            for j=0,bodies:size()-1 do local b=bodies:get(j)
                if b:getModData().PZTPerfIndex==i then
                    assert(not B.bodies[i],'duplicate body identity');B.bodies[i]=b
                end
            end
        end
        local b=assert(B.bodies[i],'saved body missing: '..i..' of '..e.count..', restored='..tostring(restored and #restored))
        if restored then assert(b:getStaticMovingObjectIndex()>=0,'restored body not registered') end
        assert(b:isZombie()==pos.zombie and not b:isPlayer(),'body type changed')
        assert(math.abs(b:getX()-pos.x)<.01 and math.abs(b:getY()-pos.y)<.01,'body position changed')
    end
    local vehicles=getCell():getVehicles():iterator();local best,d
    while vehicles:hasNext() do local v=vehicles:next();local dist=(v:getX()-p:getX())^2+(v:getY()-p:getY())^2
        if not d or dist<d then best=v;d=dist end
    end
    assert(best and d<400,'saved vehicle missing')
    B.vehicle=best;B.count=e.count;B.topology=mode=='Tow' and (topology or 'individual') or 'loose';B.perf=mode
    B.perfConfig=preset=='quick' and {warmup=2000,sample=5000,speed=20} or {warmup=10000,sample=20000,speed=8}
    B.acceptanceVehicle={x=best:getX(),y=best:getY()};B.acceptancePositions=e.positions
    best:setForceBrake();best:setPhysicsActive(false)
    p:setGodMod(true);p:setGhostMode(true);getGameTime():setTimeOfDay(12);setGameSpeed(1)
    -- Viewpoint owns the limiter when active; use the same API as its options UI.
    local caps=Viewpoint and Viewpoint.FrameCaps
    local viewpointCaps=caps and caps.active()
    if viewpointCaps then caps.setGameCap(preset=='background' and 60 or 0)
    else getCore():setFramerate(preset=='background' and 60 or 1) end
    if preset=='background' then getCore():setOptionPauseOnFocusloss(false) end
    if CVPRuntime then
        local s=CVPRuntime.authority.service;local h=CVPRuntime.authority.host;h.discover()
        for _ in pairs(s.graph.links) do error('baseline snapshot contains connections') end
        SandboxVars.CorpseProxyLab.BodyWear=false
        SandboxVars.CorpseProxyLab.MaxBodiesPerChain=0
        if mode=='Tow' then
            local car={kind='vehicle',key=h.vehicleKey(best),point='hitch'}
            local previous=car
            for _,body in ipairs(B.bodies) do
                local target=assert(h.resolve({kind='body',native=CVPNetwork.id(body),point='feet'},p))
                local gear=p:getInventory():AddItem('Base.Rope');B.gear[#B.gear+1]=gear:getID()
                local source=B.topology=='chain' and previous or car
                B.beside(p,assert(h.sample(source)));local token=assert(s:prepare(p,source,gear:getID()))
                B.beside(p,target);local ok,id=s:create(p,token,target);assert(ok,id);B.links[#B.links+1]=id
                previous=target
            end
            B.beside(p,e.origin)
        end
    end
    best:setCharacterPosition(p,0,'outside')
    B.beside(p,{x=p:getX(),y=p:getY(),z=p:getZ()})
    return {mode=mode,topology=B.topology,solver=CVPSolverUseLua and 'lua' or CVPSolverNative and 'java' or 'lua',preset=preset=='' and 'benchmark' or preset,targetSpeed=B.perfConfig.speed,
        count=e.count,links=#B.links,zoom=getCore():getZoom(0),
        width=getCore():getScreenWidth(),height=getCore():getScreenHeight(),
        uncapped=(viewpointCaps and caps.gameCap()==0) or (not viewpointCaps and getPerformance():isFramerateUncapped()),
        fpsCap=caps and caps.active() and caps.gameCap() or getPerformance():getFramerate(),
        sandbox=SandboxVars.CorpseProxyLab}
end
A.register('perf.adopt',function(arg) return adopt(arg) end,{validate=guard})
local series
A.register('perf.series.config',function(arg)
    assert(series and not B.vehicle,'configure before restoring scene')
    local variant,preset,warmed,disabled=arg:match('^(%a+) (%a+) ([01])%s*(.*)$')
    assert(variant=='Tow' or variant=='On' or variant=='Off','invalid variant')
    assert((CVPRuntime~=nil)==(variant~='Off'),'loaded variant mismatch')
    assert(preset=='express' or preset=='fast' or preset=='full' or preset=='warm','invalid timing preset')
    local allowed={BodySpread=true,BloodTrails=true,CosmeticWear=true,ClothingWear=true,CarcassWear=true}
    for name in disabled:gmatch('%S+') do
        assert(variant~='Off','cannot configure absent mod')
        if name=='ShowRopes' then
            PZAPI.ModOptions:getOptions('CorpseProxyLab'):getOption(name):setValue(false)
        else
            assert(allowed[name] and type(SandboxVars.CorpseProxyLab[name])=='boolean','unsupported module: '..name)
            SandboxVars.CorpseProxyLab[name]=false
        end
    end
    series.variant=variant
    series.config=preset=='express' and {warmup=1000,sample=3000,speed=8,express=true} or {warmup=(preset=='fast' and warmed=='1') and 0 or 10000,sample=preset=='fast' and 10000 or 20000,speed=8}
    if preset=='warm' then series.config.warmup=30000 end
    return series.config
end,{validate=guard})
A.register('perf.solver',function(arg)
    assert(arg=='lua' or arg=='java','expected lua/java')
    assert(not B.vehicle and not series,'select solver before adopting scene')
    if arg=='java' then assert(CVPSolverNative and CVPSolverNative.version()=='1','Java solver unavailable') end
    CVPSolverUseLua=arg=='lua';return arg
end,{validate=guard})
local function clearSceneDrops()
    local removed={}
    -- Loading the copied seed can also produce loose clothing before the first drive.
    -- Record and clear those drops under the same tether-preservation checks.
    for x=80,160 do for y=120,280 do
        local q=getCell():getGridSquare(x,y,0)
        if q then local items=q:getWorldObjects()
            for i=items:size()-1,0,-1 do local object=items:get(i);local item=object:getItem()
                local kind=item:getFullType()
                assert(kind~='Base.Rope' and kind~='Base.HeavyChain' and kind~='Base.HeavyChain_Hook','unexpected tether on track')
                removed[#removed+1]={id=item:getID(),type=kind,x=x,y=y}
                object:removeFromWorld();object:removeFromSquare();item:setWorldItem(nil)
            end
        end
    end end
    return removed
end
local function originLoaded()
    return getCell():getGridSquare(math.floor(series.origin.x),math.floor(series.origin.y),0)
end
local function returnReady()
    assert(series,'series not captured')
    if not series.returning then return {ready=true} end
    if not originLoaded() then return {ready=false} end
    -- The fast one-body run can stream the start of the track out. Clear its
    -- reloaded chunks too, otherwise saved blood would survive the return.
    local drops=clearSceneDrops()
    local squares=assert(CVPBenchmarkNative.clearSeriesObjects(),'return cleanup failed')
    B.beside(getPlayer(),series.origin);series.returning=false
    return {ready=true,clearedSquares=squares,drops=drops}
end
local function seriesClear()
    assert(series,'series not captured')
    assert(not getPlayer():getVehicle(),'driver must exit before cleanup')
    local n,ropes=#B.bodies,#B.gear
    B.clear() -- Checks original IDs before removing returned ropes.
    if CVPRuntime then
        for _ in pairs(CVPRuntime.authority.service.graph.links) do error('links remain after cleanup') end
    end
    if B.driveKey then
        local inv=getPlayer():getInventory();local key=inv:getItemWithID(B.driveKey)
        if key then inv:Remove(key) end
        B.driveKey=nil
    end
    -- Vanilla can drop items during a drive. All original tether IDs were checked
    -- above; only then clean this exclusive, disposable scene and record its drops.
    local drops=clearSceneDrops()
    local squares=assert(CVPBenchmarkNative.clearSeriesObjects(),'native scene cleanup failed')
    B.vehicle=nil;B.count=nil;B.perf=nil
    if originLoaded() then B.beside(getPlayer(),series.origin)
    else
        series.returning=true
        getPlayer():teleportTo(series.origin.x,series.origin.y,0)
    end
    return {count=n,returned=ropes,drops=drops,clearedSquares=squares,stage=series.returning and 'returning' or 'clean'}
end
A.register('perf.series.begin',function(arg)
    assert(not arg or arg=='' or arg=='seed' or arg=='chain-track' or arg=='packed' or arg=='packed-individual','invalid series layout')
    if UIManager then UIManager.setShowLuaDebuggerOnError(false) end
    assert(not series and not profiling,'series already active')
    local e=getPlayer():getModData().PZTPerformance
    assert(e and e.count==32,'32-body immutable fixture required')
    -- PopulationMultiplier=0 does not stop IsoChunk.AddCorpses on streamed chunks.
    -- These bodies are deserialized, not spawned; keep the track deterministic.
    SandboxVars.Zombies=6;getSandboxOptions():updateFromLua()
    adopt(CVPRuntime and 'On' or 'Off')
    assert(CVPBenchmarkNative.captureSeriesVehicle(B.vehicle),'vehicle capture failed')
    for i,body in ipairs(B.bodies) do assert(CVPBenchmarkNative.captureSeriesBody(body)==i,'body capture failed: '..i) end
    local t=getGameTime()
    series={origin=e.origin,positions=e.positions,day=t:getDay(),month=t:getMonth(),year=t:getYear(),
        compareTopology=arg=='chain-track' or arg=='packed',spacing=arg=='packed' and .25 or 1.2,
        packedIndividuals=arg=='packed-individual'}
    series.climate={}
    if getClimateManager then
        local cm=getClimateManager()
        for _,id in ipairs({ClimateManager.FLOAT_FOG_INTENSITY,ClimateManager.FLOAT_PRECIPITATION_INTENSITY,
            ClimateManager.FLOAT_WIND_INTENSITY,ClimateManager.FLOAT_CLOUD_INTENSITY,ClimateManager.FLOAT_TEMPERATURE}) do
            local value=cm:getClimateFloat(id):getFinalValue()
            series.climate[#series.climate+1]={id=id,value=value}
        end
    end
    local result=seriesClear()
    -- Chunk streaming must not resurrect the loose corpses from the input save.
    -- Native snapshots stay in memory; the working save becomes the empty track.
    save(true)
    return result
end,{validate=guard})
A.register('perf.series.scene',function(arg)
    local count,topology=arg:match('^(%d+)%s*(%a*)$')
    local n=tonumber(count);assert(n==0 or n==1 or n==2 or n==8 or n==32,'supported counts: 0, 1, 2, 8, 32')
    topology=topology=='' and 'individual' or topology
    assert(topology=='individual' or topology=='chain','invalid topology')
    assert(series and not series.returning and not B.vehicle and #B.bodies==0,'clear previous scene first')
    series.topology=topology
    local p=getPlayer();local t=getGameTime()
    t:setYear(series.year);t:setMonth(series.month);t:setDay(series.day);t:setTimeOfDay(12)
    for _,entry in ipairs(series.climate) do
        local value=getClimateManager():getClimateFloat(entry.id)
        value:setAdminValue(entry.value);value:setEnableAdmin(true)
    end
    p:getBodyDamage():RestoreToFullHealth();p:getStats():resetStats()
    B.beside(p,series.origin)
    B.vehicle=assert(CVPBenchmarkNative.restoreSeriesVehicle(),'native vehicle restoration returned nil')
    local e={count=n,positions={},origin=series.origin,version=2}
    for i=1,n do
        B.bodies[i]=assert(CVPBenchmarkNative.restoreSeriesBody(i),'native body restoration returned nil: '..i)
        e.positions[i]=series.positions[i]
        if series.compareTopology and topology=='chain' and (series.variant or 'Tow')=='Tow' then
            local b=B.bodies[i];local point=CVPRuntime.authority.host.bodyPoint(b,'feet')
            local x=b:getX()+B.vehicle:getX()+.1-point.x
            local y=b:getY()+B.vehicle:getY()+3+(i-1)*series.spacing-point.y
            local q=assert(getCell():getGridSquare(math.floor(x),math.floor(y),0),'chain fixture cell unloaded')
            require('CVP_World').move(b,x,y,0,q)
            e.positions[i]={x=x,y=y,zombie=b:isZombie()}
        elseif series.packedIndividuals and topology=='individual' and (series.variant or 'Tow')=='Tow' then
            local b=B.bodies[i];local point=CVPRuntime.authority.host.bodyPoint(b,'feet')
            local x=b:getX()+B.vehicle:getX()+((i-1)%8-3.5)*.09-point.x
            local y=b:getY()+B.vehicle:getY()+3+math.floor((i-1)/8)*.09-point.y
            local q=assert(getCell():getGridSquare(math.floor(x),math.floor(y),0),'packed fixture cell unloaded')
            require('CVP_World').move(b,x,y,0,q)
            e.positions[i]={x=x,y=y,zombie=b:isZombie()}
        end
    end
    p:getModData().PZTPerformance=e
    series.prepared=true
    series.hasRun=true
    return {stage='restored',count=n}
end,{validate=guard})
A.register('perf.series.adopt',function()
    assert(series and series.prepared,'restore scene before adoption')
    -- The engine publishes newly added vehicles to the cell on its next tick.
    local it=getCell():getVehicles():iterator();local registered=false
    while it:hasNext() do if it:next()==B.vehicle then registered=true end end
    if not registered then return {ready=false} end
    local variant=series.variant or 'Tow'
    local result=adopt(variant,B.bodies,series.topology);result.series=true;result.ready=true
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    if options then result.showRopes=options:getOption('ShowRopes'):getValue() end
    result.background=PZTPresentedFrames and PZTPresentedFrames.backgroundMode() or false
    if result.background then getCore():setOptionPauseOnFocusloss(false) end
    if series.config then B.perfConfig=series.config end
    result.sampleSeconds=B.perfConfig.sample/1000
    if CVPRuntime then
        local sim=CVPRuntime.authority.simulation;sim:build(CVPRuntime.authority.service.graph,CVPRuntime.authority.service.index)
        result.groups=#sim.groups
        local expected=variant=='Tow' and (#B.bodies>0 and series.topology=='chain' and 1 or #B.bodies) or 0
        assert(result.groups==expected,'wrong group topology')
    end
    result.layout=series.packedIndividuals and series.topology=='individual' and 'packed-individual'
        or series.compareTopology and series.topology=='chain' and (series.spacing==.25 and 'packed-feet-025' or 'chain-feet-120') or 'seed'
    local length=0;if CVPRuntime then for _,link in pairs(CVPRuntime.authority.service.graph.links) do length=length+link.length end end
    result.totalLength=length
    series.prepared=false
    return result
end,{validate=guard})
A.register('perf.series.clear',seriesClear,{validate=guard})
A.register('perf.series.ready',returnReady,{validate=guard})
A.register('perf.series.inspect',function()
    local rows={};local total=0
    for x=80,160 do for y=120,280 do
        local q=getCell():getGridSquare(x,y,0)
        if q then local bodies=q:getDeadBodys()
            for i=0,bodies:size()-1 do local b=bodies:get(i);local sq=b:getSquare();total=total+1
                if #rows<128 then rows[#rows+1]={cellX=x,cellY=y,x=b:getX(),y=b:getY(),
                    squareX=sq and sq:getX(),squareY=sq and sq:getY(),fixture=b:getModData().PZTFixture,
                    index=b:getModData().PZTPerfIndex,fakeDead=b:isFakeDead(),
                    native=CVPNetwork and CVPNetwork.id(b),
                    nativeFound=CVPNetwork and CVPNetwork.find(CVPNetwork.id(b))==b,
                    resolved=CVPRuntime and CVPRuntime.authority.host.body({key=b:getModData().CVPBodyKey})==b} end
            end
        end
    end end
    return {count=total,bodies=rows}
end,{validate=guard,readonly=true})
A.register('perf.series.quit',function()
    assert(series and not series.returning and not B.vehicle and #B.bodies==0,'clear series before quitting')
    save(true);MainScreen.instance:quitToDesktop();return 'closed'
end,{validate=guard})
A.register('perf.finish',function()
    assert(B.perf,'performance scene not adopted')
    if CVPRuntime then assert(not CVPRuntime.error and not CVPRuntime.visualError,'mod runtime failed') end
    local count=#B.bodies;local ropes=#B.gear
    B.clear() -- verifies original returned item IDs before removing fixture items
    save(true);MainScreen.instance:quitToDesktop()
    return {count=count,returned=ropes,stage='passed'}
end,{validate=guard})
