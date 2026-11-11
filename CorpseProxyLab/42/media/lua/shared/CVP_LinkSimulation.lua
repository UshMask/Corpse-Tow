-- Orient each connected path from its vehicle. A body-only or carried group is
-- stationary: carrying an end never turns the player into a towing vehicle.
local G=require 'CVP_LinkGraph'
local Core=require 'CVP_Core'
local Geometry=require 'CVP_Geometry'
local Rope=require 'CVP_Rope'
local GroupConstraints=require 'CVP_GroupConstraints'
local Load=require 'CVP_Load'
local Obstacles=require 'CVP_LinkObstacles'
local World=require 'CVP_World'
local Effects=require 'CVP_Effects'
local Horse=require 'CVP_Horse'
local Joints=require 'CVP_LinkJoints'
local BodySpread=require 'CVP_BodySpread'
local Trajectory=require 'CVP_VehicleTrajectory'
local sides={'a','b'}
local Sim={};Sim.__index=Sim
function Sim.new(host,store)
    return setmetatable({host=host,store=store,records={},groups={},obstacles={},wearPending={},trajectories={}},Sim)
end
local function other(side) return side=='a' and 'b' or 'a' end
-- Keep Lua recovery fields and native history invalidation together.
local function resetMotion(r)
    r.vx=0;r.vy=0;r.angularVelocity=0;r.nativeResetMotion=true
end
local function resetConstraint(r)
    resetMotion(r)
    r.ax=nil;r.ay=nil;r.ropeConstraintReady=nil;r.nativeResetConstraint=true
end
local function readPose(body,out)
    out=out or {}
    out.x=body:getX();out.y=body:getY();out.z=body:getZ();out.angle=body:getAngle();out.square=body:getSquare()
    return out
end
local function matchesPose(body,p)
    return body:getX()==p.x and body:getY()==p.y and body:getZ()==p.z
        and body:getAngle()==p.angle and body:getSquare()==p.square
end
local function recoverRecord(r)
    r.x=r.body:getX();r.y=r.body:getY();r.z=r.body:getZ();r.angle=r.body:getAngle()
    resetConstraint(r);r.taut=false;r.loadMass=0
end
local function releaseNative(groups)
    for _,group in ipairs(groups) do
        if group.nativeState then CVPSolverNative.release(group.nativeState) end
    end
end
local function clearNativeResets(records)
    for _,r in pairs(records) do r.nativeResetMotion=nil;r.nativeResetConstraint=nil end
end
local function useLuaHistory(sim)
    releaseNative(sim.groups)
    -- Publish Java history before discarding reset commands already owned by Lua.
    clearNativeResets(sim.records)
end
local function diagnostic(reason,link,side,gap,n)
    return string.format('reason=%s link=%s side=%s gap=%.2f jump=%.2f anchorIdleMs=%.0f tickMs=%.0f speedKmh=%.1f',
        reason,link.id,side,gap or -1,n and n.jump or 0,n and n.interval or 0,n and n.tick or 0,(n and n.speed or 0)*3.6)
end
function Sim:build(graph,index)
    local generation=self.host.generationFor and self.host.generationFor(index) or self.host.generation
    if self.index==index and self.generation==generation then return end
    -- A failed rebuild must never make the old groups look current.
    self.index=nil
    releaseNative(self.groups)
    local complete=true
    local records,groups={},{}
    local vehicleKeys={};for key in pairs(index.byVehicle) do vehicleKeys[#vehicleKeys+1]='vehicle:'..key end
    for key in pairs(index.byHorse) do vehicleKeys[#vehicleKeys+1]='horse:'..key end;table.sort(vehicleKeys)
    for _,vehicleKey in ipairs(vehicleKeys) do
        local kind,key=vehicleKey:match('^(%w+):(.*)$');local isHorse=kind=='horse'
        local vehicle=isHorse and self.host.horse({key=key}) or not isHorse and self.host.vehicle({key=key})
        if vehicle then
            local roots={};for _,edge in ipairs((isHorse and index.byHorse or index.byVehicle)[key]) do roots[#roots+1]=edge end
            table.sort(roots,function(a,b) return a.id<b.id end)
            for _,root in ipairs(roots) do
                local group={vehicle=vehicle,horse=isHorse,root=root,edges={},records={},spans={}};groups[#groups+1]=group
                local queue={{edge=root,path={}}};local at=1
                while at<=#queue do
                    local entry=queue[at];local edge=entry.edge;at=at+1;local link=graph.links[edge.id]
                    local path={};for _,e in ipairs(entry.path) do path[#path+1]=e end;path[#path+1]=edge
                    group.edges[#group.edges+1]=edge
                    local target=link[other(edge.side)]
                    if target.kind=='body' then
                        local body=self.host.body(target);local gear=self.store.linkReady(link)
                        if body and gear then
                            local r=self.records[link.id]
                            if not r or r.vehicle~=vehicle or r.horse~=isHorse
                                or r.body~=body or r.point~=target.point or r.edge.side~=edge.side
                                or r.link.revision~=link.revision then
                                r={body=body,point=target.point,x=body:getX(),y=body:getY(),z=body:getZ(),angle=body:getAngle(),
                                    vx=0,vy=0,anchorHeight=0,slot=1,connection={b={object=body}}}
                                Geometry.capture(r)
                            end
                            r.horse=isHorse;r.vehicle=vehicle;r.gear=gear;r.path=path;r.length=Joints.length(path,graph)
                            r.source=graph.links[path[1].id][path[1].side];r.link=link;r.edge=edge
                            records[link.id]=r;group.records[#group.records+1]=r
                        elseif not body then
                            complete=false -- Rebuild the group when its omitted body returns.
                            -- Retain only the same attachment's history while its body is unavailable.
                            local r=self.records[link.id]
                            if r and r.vehicle==vehicle and r.horse==isHorse and r.point==target.point
                                and r.edge.side==edge.side and r.link.revision==link.revision
                                and r.link[other(edge.side)].key==target.key then records[link.id]=r end
                        end
                    end
                    if target.kind=='body' or target.kind=='joint' then
                        local nextNode=index.nodes[edge.other];local children=0
                        for _,child in ipairs(nextNode.edges) do if child.id~=edge.id then
                            children=children+1;queue[#queue+1]={edge=child,path=target.kind=='joint' and path or {}}
                        end end
                        if (#path>1 and target.kind=='body') or (target.kind=='joint' and children==0) then
                            group.spans[#group.spans+1]=path
                        end
                    elseif #path>1 then group.spans[#group.spans+1]=path end
                end
            end
        end
    end
    local active={};for _,group in ipairs(groups) do active[group.vehicle]=true end
    for vehicle in pairs(self.trajectories) do if not active[vehicle] then
        self.trajectories[vehicle]=nil
        if CVPVehicleMotion then CVPVehicleMotion.forget(vehicle) end
    end end
    for _,group in ipairs(groups) do
        local byBody={}
        for _,r in ipairs(group.records) do byBody[r.link[other(r.edge.side)].key]=r end
        for _,r in ipairs(group.records) do
            r.parent=r.source.kind=='body' and byBody[r.source.key] or nil
            if r.parent then
                if not r.sourcePose or r.sourcePose.body~=r.parent.body or r.sourcePose.point~=r.source.point then
                    r.sourcePose={body=r.parent.body,point=r.source.point};Geometry.capture(r.sourcePose)
                end
            else r.sourcePose=nil end
        end
    end
    self.records=records;self.groups=groups
    self.generation=generation;self.index=complete and index or nil
end
-- Roll back original bodies, never substitutes or inventories. Retain pending
-- recovery if the engine also refuses rollback; do not simulate over it.
function Sim:restore()
    if self.calculating then
        for _,r in ipairs(self.calculating) do recoverRecord(r) end
        self.calculating=nil
    end
    if not self.pendingPoses then return end
    local problem;local remaining={}
    for i=#self.pendingPoses,1,-1 do local r=self.pendingPoses[i];local p=r.before
        local attempted=false
        local ok,err=pcall(function()
            local e=r.rollbackExpected
            assert(not e or matchesPose(r.body,e),'body changed during pending rollback')
            attempted=true
            World.move(r.body,p.x,p.y,p.z,p.square)
            World.angle(r.body,p.angle)
        end)
        if not ok then
            problem=problem or tostring(err);remaining[#remaining+1]=r
            if attempted then r.rollbackExpected=readPose(r.body) end
        else r.rollbackExpected=nil end
        recoverRecord(r)
    end
    if problem then self.pendingPoses=remaining;error('pose rollback pending: '..problem) end
    self.pendingPoses=nil
end
function Sim:apply(group,readPass,skipInvalidation)
    assert(CVPWorldNative and CVPWorldNative.move,'CVP native movement unavailable; update the mod JAR and restart the game')
    self.pendingPoses={}
    -- Java journals each body before mutation; Lua owns group rollback and retries.
    local ok,err=pcall(CVPWorldNative.applyPoses,group.records,self.pendingPoses,readPass,skipInvalidation)
    if not ok then
        for _,r in ipairs(self.pendingPoses) do r.rollbackExpected=readPose(r.body) end
        self:restore();error(err)
    end
    self.pendingPoses=nil
end
-- Capture the live world immediately before solving this group, not at tick start.
function Sim:prepareGroup(group,graph,sample,readPass,network,dt,recovering)
    local first=group.records[1];local root=graph.links[group.root.id]
    group.correctionOnly=recovering==true or self.clockCorrection==true
    if readPass then CVPWorldNative.readPoses(readPass,group.records) end
    for _,r in ipairs(group.records) do
        local p=r.before or {};r.before=p
        if not readPass then
            readPose(r.body,p)
        end
        local x,y,z,angle=p.x,p.y,p.z,p.angle
        if math.abs(x-r.x)+math.abs(y-r.y)>0.001 or z~=r.z or math.abs(Rope.wrapAngle(angle-r.angle))>0.001 then
            -- Another mechanic may have moved the same original body. Never replay an old pose over it.
            resetConstraint(r)
        end
        r.x=x;r.y=y;r.z=z;r.angle=angle;r.blocked=false;r.taut=false
        -- Immutable during this synchronous group calculation; refresh next tick.
        local length,capacity=Joints.length(r.path,graph);r.length=length;r.maxGapSquared=(capacity+6)^2
        r.floor=math.floor(z)
        r.sourceSample=not r.parent and sample(graph.links[r.path[1].id][r.path[1].side]) or nil
    end
    self.calculating=group.records
    local rootSample=G.copy(sample(root[group.root.side]))
    local startX,startY
    if first then
        startX,startY=first.ax or rootSample.x,first.ay or rootSample.y
        local ax,ay
        if network then
            local correction
            ax,ay,correction=Trajectory.advance(network,first,rootSample,dt,recovering)
            group.correctionOnly=group.correctionOnly or correction
        else ax,ay=Rope.networkAnchor({ax=startX,ay=startY},rootSample.x,rootSample.y,dt,group.horse and 0 or group.vehicle:getCurrentSpeedKmHour()) end
        rootSample.x,rootSample.y=ax,ay
    end
    return rootSample,startX,startY
end
-- Produces candidate records only. The caller still owns commit and recovery.
local function solveGroup(group,root,pathCache,steps,h,now,startX,startY,rootSample,release,loadBlend)
    group.nativeFallback=false;group.solverIterations=0;group.solverResidual=0;group.recoverySteps=0
    local first=group.records[1]
    local ready,obstruction,accumulated=true,nil,0
    if pathCache.native then
        for _,r in ipairs(group.records) do
            Load.refresh(r,now)
            r.nativeElastic=r.gear and r.gear:getFullType()=='Base.Rope'
        end
        group.nativeState=group.nativeState or CVPSolverNative.prepare(group.records)
        accumulated=CVPSolverNative.solvePersistent(group.nativeState,pathCache.native,group,steps,h,
            startX or 0,startY or 0,rootSample.x,rootSample.y)
        if group.nativeGap>0 then
            release(root,group.root.side,'solver_gap',
                {x=group.nativeGapX,y=group.nativeGapY,z=group.nativeGapZ},group.records[group.nativeGap])
            ready=false
        end
        if group.nativeUnconverged then ready=false end
        if group.nativeObstruction then obstruction=group.nativeObstruction;ready=false end
    else
    for step=1,steps do
        group.contacts=group.contacts or {}
        Rope.separate(group.records,group.contacts)
        group.recoveryStep=group.correctionOnly
        if #group.records==1 then
            local r=group.records[1]
            local angularDamping=math.exp(-4*h)
            local vx,vy=r.vx+(r.pushX or 0)*h,r.vy+(r.pushY or 0)*h
            local speed=math.sqrt(vx*vx+vy*vy)
            local slide=speed>0 and math.max(0,1-9.81*.65*h/speed) or 0
            r.physicalVX=vx*slide;r.physicalVY=vy*slide
            r.physicalW=math.max(-3,math.min(3,(r.angularVelocity or 0)*angularDamping))
            r.correctionStep=false
        end
        if #group.records>1 then
            if step==1 then for _,r in ipairs(group.records) do Load.refresh(r,now) end end
            GroupConstraints.step(group.records,pathCache,startX+(rootSample.x-startX)*step/steps,
                startY+(rootSample.y-startY)*step/steps,h,group)
            if group.nativeGap>0 then
                release(root,group.root.side,'solver_gap',
                    {x=group.nativeGapX,y=group.nativeGapY,z=group.nativeGapZ},group.records[group.nativeGap]);ready=false
            end
            if group.nativeUnconverged then ready=false end
            if group.nativeObstruction then obstruction=group.nativeObstruction;ready=false end
        else
        for _,r in ipairs(group.records) do
            local sx,sy,sz
            if r.parent then
                local p=r.sourcePose;local parent=r.parent
                p.x=parent.x;p.y=parent.y;p.z=parent.z;p.angle=parent.angle
                sx,sy,sz=Rope.feet(p)
            else local source=r.sourceSample;sx,sy,sz=source.x,source.y,source.z end
            if r==first then sx=startX+(rootSample.x-startX)*step/steps;sy=startY+(rootSample.y-startY)*step/steps end
            if math.floor(sz)~=r.floor or (sx-r.x)^2+(sy-r.y)^2>r.maxGapSquared then
                release(root,group.root.side,'solver_gap',{x=sx,y=sy,z=sz},r);ready=false;break
            end
            r.ax=r.ax or sx;r.ay=r.ay or sy
            Core.advance(r,sx,sy,sz,h,pathCache,true)
            if r.ropeBlocked then obstruction=r.ropeBlocked;ready=false;break end
            if r.blocked and r.taut then obstruction=Obstacles.blocked;ready=false;break end
            r.ax=sx;r.ay=sy
            if step==1 then Load.refresh(r,now) end
        end
        end
        if not ready then break end
        if #group.records==1 then group.recoveryStep=group.recoveryStep or group.records[1].correctionStep end
        if group.recoveryStep then group.recoverySteps=group.recoverySteps+1 end
        Load.connect(group.records,group.contacts)
        local fallbackMass
        if group.fallbackStep and not group.correctionOnly and not group.takeupStep then
            local dx=(rootSample.x-startX)/steps;local dy=(rootSample.y-startY)/steps
            local distance2=dx*dx+dy*dy
            if distance2>(.02*h)^2 then
                -- The degraded projection cannot recover a reliable constraint
                -- impulse. Charge only ground friction for connected bodies in
                -- proportion to their actual travel along the moving anchor.
                fallbackMass=0
                for _,r in ipairs(group.records) do if r.loadConnected then
                    local travel=((r.fallbackDX or 0)*dx+(r.fallbackDY or 0)*dy)/distance2
                    fallbackMass=fallbackMass+r.mass*math.max(0,math.min(1,travel))
                end end
            end
        end
        for _,r in ipairs(group.records) do
            if group.recoveryStep then
                r.vx=r.blocked and 0 or r.physicalVX;r.vy=r.blocked and 0 or r.physicalVY
                r.angularVelocity=r.blocked and 0 or r.physicalW;r.reaction=0
            end
            r.loadMass=not r.parent and (fallbackMass or (r.reaction or 0)/(9.81*.65)) or 0
            accumulated=accumulated+r.loadMass/steps
        end
    end
    end
    if not pathCache.native then
        clearNativeResets(group.records)
    end
    if group.nativeFallback then group.fallbackTicks=(group.fallbackTicks or 0)+1 end
    return ready,obstruction,accumulated,loadBlend
end
function Sim:tick(graph,index,dt,now,interpolationLag,clockCorrection)
    self:restore()
    self.clockCorrection=clockCorrection==true
    self.sampledAt=math.floor(now-(interpolationLag or 0)*1000)
    local requests,loads={},{}
    -- No physics interval means no new geometry. Retain the last committed
    -- endpoint positions instead of alternating them with saved coordinates.
    if self.host.enabled() and dt<=0 then return requests,loads end
    self.obstacles={};self.host.joints={};self.host.freeEnds={}
    if not self.host.enabled() then
        for _,r in pairs(self.records) do
            r.taut=false;r.loadMass=0;r.spreadSpeed=0;r.effectTravel=0
        end
        return requests,loads
    end
    self:build(graph,index)
    local solver=CVPSolverNative and not CVPSolverUseLua and CVPSolverNative or false
    BodySpread.update(self,solver)
    if #self.groups==0 then return requests,loads end
    -- Vehicle transforms cannot change during this synchronous authority tick.
    -- Body endpoints remain live so each child sees its parent's substep.
    local readPass
    local anchors={}
    local function sample(e)
        -- Reuse the validated object for ownership checks, but never cache a
        -- body's availability/pose across calls, commits or inventory changes.
        if e.kind=='body' then
            local body=self.host.body(e,readPass)
            return body and self.host.bodyPoint(body,e.point),body
        end
        if e.kind~='vehicle' then return self.host.sample(e) end
        local key=e.key..':'..tostring(e.point);local row=anchors[key]
        if row==nil then row=self.host.sample(e) or false;anchors[key]=row end
        if row then return row end
    end
    local pathCache=Obstacles.new(solver)
    if not pathCache.native then
        useLuaHistory(self)
    end
    -- Authority retains up to 500 ms at 100 Hz, including SP physics intervals.
    -- Do not compress a 100-500 ms vehicle movement into 100 ms of body motion.
    -- Beyond this bounded window the existing trajectory recovery still applies.
    dt=math.min(not isClient() and .5 or .1,dt)
    local steps=math.max(1,math.ceil(dt*100-1e-9));local h=dt/steps
    -- Optional additive bridge: older JARs keep the identical Lua read path.
    if CVPWorldNative and CVPWorldNative.beginRead then readPass=CVPWorldNative.beginRead() end
    local skipInvalidation -- Camera/render mode is stable during this synchronous tick.
    local loadBlend -- Lazily shared by all moving groups at this timestep.
    for _,group in ipairs(self.groups) do
        if #group.spans>0 then Joints.place(group,graph,self.host) end
        local ready=not group.horse or Horse.active(group.vehicle);local root=graph.links[group.root.id];local obstruction
        local first=group.records[1]
        local unavailable=false
        for _,edge in ipairs(group.edges) do
            local target=graph.links[edge.id][other(edge.side)]
            local r=self.records[edge.id]
            if target.kind=='body' and (not r or not World.present(r.body,readPass)) then unavailable=true;break end
        end
        if unavailable then ready=false end
        -- Do not consume vehicle travel while the chain cannot be simulated.
        -- On return, the existing bounded recovery validates elapsed time/direction/gap.
        local network
        if (isServer() or CVPVehicleMotion and CVPVehicleMotion.localTime) and not group.horse and first and not unavailable then
            local endpoint=sample(root[group.root.side])
            if endpoint then network=Trajectory.sample(self.trajectories,group.vehicle,root[group.root.side].point,endpoint,now,dt,not isServer(),interpolationLag) end
        end
        if network then
            if first.trajectoryOwner~=nil and first.trajectoryOwner~=network.owner then
                first.recoveryUntil=nil;first.anchorAt=nil
            end
            first.trajectoryOwner=network.owner
        end
        local recovering=false
        local function release(link,side,reason,source,target)
            local gap=source and target and G.distance(source,target)
            requests[#requests+1]={id=link.id,revision=link.revision,side=side,where=link[side],
                diagnostic=diagnostic(reason,link,side,gap,network)}
        end
        for _,edge in ipairs(group.edges) do local link=graph.links[edge.id]
            if not self.store.linkReady(link) then ready=false end
            local record=self.records[link.id]
            if record and self.wearPending[record.body] then ready=false end
            if link[other(edge.side)].kind=='body' and not self.records[link.id] then
                ready=false;self.index=nil -- Retry after an unloaded body or pending transfer becomes available.
            end
            local source,sourceBody=sample(link[edge.side]);local target,targetBody=sample(link[other(edge.side)])
            if source and target and link[other(edge.side)].kind=='body' then
                obstruction=obstruction or Obstacles.check(pathCache,source,target)
                if obstruction then ready=false end
            end
            if link==root and not obstruction then source=source and Trajectory.checkedSource(network,first,source,dt) end
            if not unavailable and source and target and link[other(edge.side)].kind=='body' and link[edge.side].kind~='joint'
                and (math.floor(source.z)~=math.floor(target.z) or (source.x-target.x)^2+(source.y-target.y)^2>(G.capacityFor(link)+6)^2) then
                local gap=G.distance(source,target)
                if link==root then
                    local started
                    recovering,started=Trajectory.recover(network,first,source,target,G.capacityFor(link),now,obstruction)
                    if started then print('[CVP recovery] start '..diagnostic('delayed_vehicle',link,edge.side,gap,network)) end
                end
                local side=edge.side
                if math.floor(target.z)~=math.floor(link[other(side)].z) then side=other(side) end
                if not (link==root and recovering) then
                    local reason=math.floor(source.z)~=math.floor(target.z) and 'floor_change'
                        or obstruction or first and first.recoveryUntil and now>=first.recoveryUntil and 'recovery_timeout' or 'excess_gap'
                    release(link,side,reason,source,target);ready=false
                end
            end
            for _,side in ipairs(sides) do local e=link[side]
                local endpoint
                if side==edge.side then endpoint=source else endpoint=target end
                if (e.kind=='body' or G.tractor(e)) and not endpoint then ready=false end
                if e.kind=='body' then local b;if side==edge.side then b=sourceBody else b=targetBody end
                    local grappled=b and b:isBeingGrappled()
                    if b and (grappled or b:getModData().CorpseTowingVehicleToken~=nil) then
                        requests[#requests+1]={id=link.id,revision=link.revision,side=side,where=endpoint,
                            diagnostic=diagnostic(grappled and 'body_grappled' or 'foreign_tow',link,side,source and target and G.distance(source,target),network)}
                        ready=false
                    end
                end
            end
        end
        if ready then
            local accumulated=0
            local rootSample,startX,startY=self:prepareGroup(group,graph,sample,readPass,network,dt,recovering)
            ready,obstruction,accumulated,loadBlend=solveGroup(group,root,pathCache,steps,h,now,
                startX,startY,rootSample,release,loadBlend)
            if skipInvalidation==nil then
                skipInvalidation=CVPDynamicCorpses~=nil and CVPDynamicCorpses.canSkipMoveInvalidation()
            end
            self:apply(group,readPass,skipInvalidation)
            if ready then
                for _,r in ipairs(group.records) do
                    local source=graph.links[r.path[1].id][r.path[1].side]
                    local used=G.copy(sample(source))
                    if used and r==first then used.x=rootSample.x;used.y=rootSample.y end
                    r.corrected=group.recoverySteps>0
                    r.committedSource=used;r.committedAt=math.floor(now-(interpolationLag or 0)*1000)
                end
            end
            self.calculating=nil
            if #group.spans>0 then Joints.place(group,graph,self.host) end
            Effects.committed(group,self.wearPending,now)
            if ready and not group.horse and accumulated>0 then loads[group.vehicle]=(loads[group.vehicle] or 0)+accumulated*(9.81*.65) end
        end
        if Trajectory.finish(first,now,ready,recovering) then
            print('[CVP recovery] '..(ready and 'complete ' or 'stopped ')..diagnostic(obstruction or 'gap_check',root,group.root.side,nil,network))
        end
        if not ready then for _,r in ipairs(group.records) do
            r.corrected=true;r.taut=false;r.loadMass=0;resetMotion(r)
            if (not unavailable or obstruction) and not group.nativeUnconverged then r.ax=nil;r.ay=nil end
            if obstruction then r.blocked=true end
        end end
        if obstruction then for _,edge in ipairs(group.edges) do self.obstacles[edge.id]=obstruction end end
    end
    return requests,loads
end
return Sim
