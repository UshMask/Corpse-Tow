-- Actual driver actions and pedal-controlled Bullet physics; never move transforms.
require 'CVP_Benchmark'
require 'Vehicles/ISUI/ISVehicleMenu'
require 'Vehicles/TimedActions/ISStartVehicleEngine'
local A=require 'PZT_Control'
local B=CVPBenchmark
local drive
local function mark(d,phase)
    -- Six boundary calls; the Java event is inert when no JFR recording is active.
    CVPBenchmarkNative.phase(d.id,phase)
end
local function clock() return CVPBenchmarkNative.milliseconds() end
local function write(name,lines)
    local f=getFileWriter(name,true,false)
    if not f then return false end
    f:write(table.concat(lines,'\n'));f:close();return true
end
function B.stopBenchmark()
    PZTDrivingInput.stop()
    local caps=Viewpoint and Viewpoint.FrameCaps
    if caps and caps.active() then caps.setGameCap(60) end
    getCore():setFramerate(60)
    if PZTPresentedFrames then PZTPresentedFrames.cancel() end
end
local function finish(ok,why)
    local d=drive;drive=nil;PZTDrivingInput.stop()
    if not ok then B.stopBenchmark() end
    mark(d,ok and 'done' or 'failed')
    if not write('PZTDrive-'..d.id..'.txt',d.frames) then
        B.stopBenchmark();A.complete(d.id,false,'could not save driving samples');return
    end
    if not ok then A.complete(d.id,false,why);return end
    if B.perf and not write('PZTDrive-'..d.id..'-present.txt',{d.present}) then
        B.stopBenchmark();A.complete(d.id,false,'could not save presented frames');return
    end
    PZTDrivingInput.release()
    A.complete(d.id,true,{stage='driven',frames=#d.frames-1,seconds=(d.stopAt-d.sampleAt)/1000,
        count=#B.bodies,allBodiesMoving=d.moved==#B.bodies,movedBodies=d.moved,tautFrames=d.tautFrames,driverSeated=true,
        engineRunning=true,vehicleDistance=d.carDistance,bodyDistances=d.distances,
        warmupSeconds=(d.sampleAt-d.driveAt)/1000,rotation=d.rotation,settling=d.settling,
        stopWindow=d.stopWindow,solverProbe=d.solverProbe,spreadProbe=d.spreadProbe,mode=d.mode})
end
A.register('perf.series.abort',function()
    B.stopBenchmark()
    if drive then finish(false,'benchmark aborted') end
    return 'stopped; FPS limited to 60; scene preserved'
end,{interrupt=true,validate=function()
    if getWorld():getWorld()~='PZT_VehicleLab' or getWorld():getMap()~='PZT_ProvingGround' then return 'proving ground required' end
end})
local ownerStopped=false
Events.OnTick.Add(function()
    if not ownerStopped and CVPBenchmarkNative.benchmarkOwnerLost() then
        B.stopBenchmark();ownerStopped=true
        if drive then finish(false,'benchmark controller exited') end
    end
end)
A.register('scene.drive',function(arg,id)
    local mode=arg and arg~='' and arg or 'acceptance'
    assert(mode=='fps' or mode=='diagnostic' or mode=='acceptance','invalid driving mode')
    local p=getPlayer();local v=B.vehicle
    local config=B.perfConfig or {warmup=10000,sample=20000,speed=8}
    PZTDrivingInput.setTargetSpeed(config.speed)
    v:repair()
    local fuel=assert(v:getPartById('GasTank'),'fuel tank missing')
    fuel:setContainerContentAmount(fuel:getContainerCapacity())
    local key=p:getInventory():AddItem(v:createVehicleKey());B.driveKey=key:getID()
    v:setPhysicsActive(true)
    ISVehicleMenu.processEnter(p,v,0)
    ISTimedActionQueue.add(ISStartVehicleEngine:new(p))
    drive={id=id,start=clock(),phase='enter',frames={'frame_ms,vehicle_x,vehicle_y,speed_kmh,root_distance,root_length,min_body_distance,tick_ms,heap_mb'},
        tautFrames=0,distances={},config=config,mode=mode}
    mark(drive,'enter')
    return 'walking to driver seat and starting engine',true
end,{validate=function()
    if drive or B.sample then return 'operation active' end
    if not getPlayer() or getPlayer():getVehicle() then return 'driver must start outside vehicle' end
    if getWorld():getWorld()~='PZT_VehicleLab' or getWorld():getMap()~='PZT_ProvingGround' then return 'proving ground required' end
    if not PZTDrivingInput or not B.vehicle or not B.acceptancePositions then return 'adopt saved scene and install driving helper first' end
end})
Events.OnRenderTick.Add(function()
    CVPBenchmarkNative.gameProfilerTick()
    local d=drive;if not d then return end
    if B.perf and d.phase=='sample' and not PZTPresentedFrames.valid() then
        finish(false,'framebuffer unavailable or capture display changed');return
    end
    local now=clock();local p=getPlayer();local v=B.vehicle
    if getGameSpeed()~=1 or (MainScreen.instance.inGame and MainScreen.instance:isVisible()) then
        finish(false,'game paused during driver cycle');return
    end
    if now-d.start>100000 then finish(false,'driver cycle timed out at '..d.phase);return end
    if CVPRuntime and (CVPRuntime.error or CVPRuntime.visualError) then finish(false,'mod runtime failed');return end
    if d.stopWindow and not d.stopWindow.complete and now-(d.stopObservedAt or 0)>=250 then
        d.stopObservedAt=now
        local vx,vy=v:getX()-d.stopVehicle.x,v:getY()-d.stopVehicle.y
        d.stopWindow.maxVehicleDisplacement=math.max(d.stopWindow.maxVehicleDisplacement,math.sqrt(vx*vx+vy*vy))
        for i,b in ipairs(B.bodies) do
            local start=d.stopBodies[i];local dx,dy=b:getX()-start.x,b:getY()-start.y
            d.stopWindow.maxDisplacement=math.max(d.stopWindow.maxDisplacement,math.sqrt(dx*dx+dy*dy))
            d.stopWindow.maxRelativeDisplacement=math.max(d.stopWindow.maxRelativeDisplacement,
                math.sqrt((dx-vx)^2+(dy-vy)^2))
        end
        d.stopWindow.samples=d.stopWindow.samples+1
        d.stopWindow.elapsedSeconds=(now-d.stoppedAt)/1000
        if now-d.stoppedAt>=5000 then d.stopWindow.complete=true end
    end
    if d.phase=='enter' then
        if p:getVehicle()==v and v:isDriver(p) and v:isEngineRunning() then
            PZTDrivingInput.begin(v,p);d.phase='tension';d.driveAt=now
            mark(d,'warmup')
        end
        return
    end
    if d.phase=='exit' then
        if not p:getVehicle() then
            if d.mode~='acceptance' then finish(true);return end
            d.phase='settle';d.settleAt=now
        end
        return
    end
    if d.phase=='settle' then
        if now-d.settleAt<5000 then return end
        if not d.settling then
            d.settling={seconds=15,maxSpeed=0,maxTurn=0,maxOrbit=0};d.settleBodies={};d.settleLast=now
            for i,b in ipairs(B.bodies) do d.settleBodies[i]={x=b:getX(),y=b:getY(),angle=b:getAngle(),
                orbit=math.atan2(b:getY()-v:getY(),b:getX()-v:getX()),turn=0,orbitTurn=0} end
        elseif now-d.settleLast>=250 then
            local dt=(now-d.settleLast)/1000;d.settleLast=now
            local function wrap(a) local t=a+math.pi;return t-math.floor(t/(2*math.pi))*(2*math.pi)-math.pi end
            for i,b in ipairs(B.bodies) do
                if not b:getSquare() or b:getStaticMovingObjectIndex()<0 then finish(false,'body unloaded while settling');return end
                local r=d.settleBodies[i];local x,y,angle=b:getX(),b:getY(),b:getAngle()
                local orbit=math.atan2(y-v:getY(),x-v:getX())
                r.turn=r.turn+wrap(angle-r.angle);r.orbitTurn=r.orbitTurn+wrap(orbit-r.orbit)
                d.settling.maxSpeed=math.max(d.settling.maxSpeed,math.sqrt((x-r.x)^2+(y-r.y)^2)/dt)
                d.settling.maxTurn=math.max(d.settling.maxTurn,math.abs(r.turn))
                d.settling.maxOrbit=math.max(d.settling.maxOrbit,math.abs(r.orbitTurn))
                r.x=x;r.y=y;r.angle=angle;r.orbit=orbit
            end
        end
        if now-d.settleAt>=15000 then
            if d.settling.maxSpeed>1 or d.settling.maxTurn>math.pi or d.settling.maxOrbit>math.pi then
                finish(false,string.format('unstable stopped group: speed=%.3f turn=%.3f orbit=%.3f',
                    d.settling.maxSpeed,d.settling.maxTurn,d.settling.maxOrbit));return
            end
            finish(true)
        end
        return
    end
    if d.phase=='brake' then
        if math.abs(v:getCurrentSpeedKmHour())<.2 then
            if d.mode=='acceptance' then
                d.stoppedAt=now;d.stopBodies={};d.stopVehicle={x=v:getX(),y=v:getY()}
                d.stopWindow={maxDisplacement=0,maxVehicleDisplacement=0,maxRelativeDisplacement=0,samples=0,complete=false}
                for i,b in ipairs(B.bodies) do d.stopBodies[i]={x=b:getX(),y=b:getY()} end
            end
            PZTDrivingInput.release();ISVehicleMenu.onExit(p,0);d.phase='exit'
        end
        return
    end
    if p:getVehicle()~=v or not v:isEngineRunning() then finish(false,'driver or running engine lost');return end
    -- Keep pedal control per frame; scene telemetry needs only four samples/sec.
    if d.observeAt and now-d.observeAt<250 and not (d.phase=='sample' and now-d.sampleAt>=d.config.sample) then return end
    d.observeAt=now
    local minDistance=#B.bodies==0 and 0 or math.huge
    for i,b in ipairs(B.bodies) do
        local origin=B.acceptancePositions[i]
        d.distances[i]=math.sqrt((b:getX()-origin.x)^2+(b:getY()-origin.y)^2)
        minDistance=math.min(minDistance,d.distances[i])
    end
    local length,rootLength,taut=0,0,false
    local towing=(not B.perf or B.perf=='Tow') and #B.bodies>0
    if towing then
        local h=CVPRuntime.authority.host
        local root=CVPRuntime.authority.service.graph.links[B.links[1]]
        if not root then finish(false,'root connection lost');return end
        local a,b=h.sample(root.a),h.sample(root.b)
        if not a or not b then finish(false,'tether endpoint lost');return end
        length=math.sqrt((a.x-b.x)^2+(a.y-b.y)^2);rootLength=root.length
        taut=length>=rootLength*.9
    end
    if taut then d.tautFrames=d.tautFrames+1 end
    local origin=B.acceptanceVehicle
    local startDistance=d.config.express and .1 or 2
    local vehicleMoved=(v:getX()-origin.x)^2+(v:getY()-origin.y)^2>startDistance^2
    local ready=B.perf and now-d.driveAt>=d.config.warmup and vehicleMoved and (not towing or minDistance>startDistance)
        or (not B.perf and minDistance>2 and taut)
    if B.perf and d.phase=='tension' and now-d.driveAt>=40000 and not ready then
        local origin=B.acceptanceVehicle
        finish(false,string.format('load did not move after 40s: minBody=%.3f vehicle=%.3f speed=%.3f',
            minDistance,math.sqrt((v:getX()-origin.x)^2+(v:getY()-origin.y)^2),v:getCurrentSpeedKmHour()))
        return
    end
    if d.phase=='tension' and d.config.express then
        if not vehicleMoved or (towing and minDistance<=startDistance) then d.stableAt=nil
        else d.stableAt=d.stableAt or now end
        ready=d.stableAt and now-d.stableAt>=1000
    end
    if d.phase=='tension' and ready then
        d.phase='sample';d.sampleAt=now;d.last=now;d.sampleBodyStart=minDistance
        d.sampleVehicle={x=v:getX(),y=v:getY()}
        if B.perf then PZTPresentedFrames.begin() end
        d.samplePositions={};d.rotation={maxTurn=0,maxOrbit=0};d.rotationAt=now;d.rotationBodies={}
        for i,b in ipairs(B.bodies) do d.samplePositions[i]={x=b:getX(),y=b:getY()} end
        for i,b in ipairs(B.bodies) do d.rotationBodies[i]={angle=b:getAngle(),
            orbit=math.atan2(b:getY()-v:getY(),b:getX()-v:getX()),turn=0,orbitTurn=0} end
        mark(d,'sample')
        return
    end
    if d.phase=='sample' then
        if d.mode=='acceptance' and towing then
            local authority=CVPRuntime.authority;local sim=authority.simulation
            local probe=d.solverProbe or {samples=0,movingSamples=0,zeroForceSamples=0,zeroConnectedSamples=0,maxFallbackTicks=0,maxResidual=0}
            local fallback,connected=0,0
            for _,group in ipairs(sim.groups) do
                fallback=fallback+(group.fallbackTicks or 0)
                probe.maxResidual=math.max(probe.maxResidual,group.solverResidual or 0)
                for _,record in ipairs(group.records) do if record.loadConnected then connected=connected+1 end end
            end
            probe.samples=probe.samples+1;probe.maxFallbackTicks=math.max(probe.maxFallbackTicks,fallback)
            if math.abs(v:getCurrentSpeedKmHour())>.5 then
                probe.movingSamples=probe.movingSamples+1
                local force=authority.loads and authority.loads[v] or 0
                if force<=0 then
                    probe.zeroForceSamples=probe.zeroForceSamples+1
                    if connected>0 then probe.zeroConnectedSamples=probe.zeroConnectedSamples+1 end
                end
                probe.maxForceN=math.max(probe.maxForceN or 0,force)
            end
            d.solverProbe=probe
        end
        if d.mode=='acceptance' and B.topology=='individual' and #B.bodies>=8 then
            local dx,dy=v:getX()-d.sampleVehicle.x,v:getY()-d.sampleVehicle.y
            local distance=math.sqrt(dx*dx+dy*dy)
            if distance>1 then
                local nx,ny=-dy/distance,dx/distance
                local values,sorted={},{}
                for i,b in ipairs(B.bodies) do
                    values[i]=b:getX()*nx+b:getY()*ny;sorted[i]=values[i]
                end
                table.sort(sorted)
                local low=math.floor(#sorted*.25)+1;local high=math.floor(#sorted*.75)
                local width=sorted[high]-sorted[low]
                local probe=d.spreadProbe or {samples=0,minWidth=width,maxWidth=width,orderChanges=0}
                if d.spreadPrevious then
                    for i=1,#values-1 do for j=i+1,#values do
                        local before=d.spreadPrevious[i]-d.spreadPrevious[j]
                        local after=values[i]-values[j]
                        if before*after<0 then probe.orderChanges=probe.orderChanges+1 end
                    end end
                end
                d.spreadPrevious=values;probe.samples=probe.samples+1
                probe.minWidth=math.min(probe.minWidth,width);probe.maxWidth=math.max(probe.maxWidth,width)
                d.spreadProbe=probe
            end
        end
        -- Straight-track acceptance: moving bodies alone does not prove stable towing.
        -- Four observations per second suffice for the bounded 3 rad/s turn rate.
        if now-d.rotationAt>=250 then
            d.rotationAt=now
            local function wrap(a) local t=a+math.pi;return t-math.floor(t/(2*math.pi))*(2*math.pi)-math.pi end
            for i,b in ipairs(B.bodies) do
                local r=d.rotationBodies[i];local angle=b:getAngle()
                local orbit=math.atan2(b:getY()-v:getY(),b:getX()-v:getX())
                r.turn=r.turn+wrap(angle-r.angle);r.orbitTurn=r.orbitTurn+wrap(orbit-r.orbit)
                r.angle=angle;r.orbit=orbit
                d.rotation.maxTurn=math.max(d.rotation.maxTurn,math.abs(r.turn))
                d.rotation.maxOrbit=math.max(d.rotation.maxOrbit,math.abs(r.orbitTurn))
            end
        end
        d.frames[#d.frames+1]=string.format('%.4f,%.4f,%.4f,%.3f,%.4f,%.4f,%.4f,%.6f,%.3f',
            now-d.last,v:getX(),v:getY(),v:getCurrentSpeedKmHour(),length,rootLength,minDistance,
            B.tickMS or 0,CVPBenchmarkNative.heapMB())
        d.last=now
        if now-d.sampleAt>=d.config.sample then
            mark(d,'brake')
            if (v:getX()-d.sampleVehicle.x)^2+(v:getY()-d.sampleVehicle.y)^2<=(d.config.express and .01 or 25) then
                finish(false,'vehicle did not travel during FPS sampling');return
            end
            if towing and (d.rotation.maxTurn>2*math.pi+.1 or d.rotation.maxOrbit>2*math.pi+.1) then
                finish(false,string.format('unstable straight towing: body turn=%.3f orbit=%.3f radians',
                    d.rotation.maxTurn,d.rotation.maxOrbit));return
            end
            d.moved=0
            for i,b in ipairs(B.bodies) do local start=d.samplePositions[i]
                if (b:getX()-start.x)^2+(b:getY()-start.y)^2>(d.config.express and .01 or 25) then d.moved=d.moved+1 end
            end
            if towing and d.moved~=#B.bodies then finish(false,'bodies did not travel during FPS sampling');return end
            local origin=B.acceptanceVehicle
            d.carDistance=math.sqrt((v:getX()-origin.x)^2+(v:getY()-origin.y)^2)
            d.stopAt=now;PZTDrivingInput.stop();d.phase='brake'
            if B.perf then d.present=PZTPresentedFrames.finish() end
        end
    end
end)
