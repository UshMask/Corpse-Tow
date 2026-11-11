-- Solve connected bodies together. Internal tether reactions act on both bodies;
-- rotation comes from the attachment lever arm, not an independent angle motor.
local Rope=require 'CVP_Rope'
local Geometry=require 'CVP_Geometry'
local Obstacles=require 'CVP_LinkObstacles'
local C={}
local function foot(r,p)
    local x,y=r.attachLocalX or r.footLocalX or -.65,r.attachLocalY or r.footLocalY or 0
    local c,s=math.cos(p.angle),math.sin(p.angle)
    return p.x+c*x-s*y,p.y+s*x+c*y
end
local function source(r,i,rx,ry)
    if i==1 then return rx,ry,r.sourceSample.z end
    if r.parent then
        local p=r.parent.coupledPose;local f=r.sourcePose
        local x,y=foot(f,p);return x,y,r.parent.z+.025
    end
    local p=r.sourceSample;return p.x,p.y,p.z
end
-- `negLimit`/`limit` are the cached -3*h / 3*h turn bounds of the current substep.
local function turn(used,requested,negLimit,limit)
    return math.max(negLimit,math.min(limit,used+requested))-used
end
-- Opt-in aggregated solver counters. Disabled by default: the hot path only
-- reads one boolean, allocates nothing per constraint and writes no group field.
-- Their lifetime is the enabled interval; group fields are reset at the first
-- substep of each solve (the caller already resets group.solverIterations then)
-- and report the aggregate for that solve.
local aggregate={substeps=0,iterations=0,calls=0,searchEntries=0,fallbacks=0,limitHits=0}
C.counters=aggregate
C.countersEnabled=false
local counting=false
local stepIterations,stepCalls,stepSearch,stepLimitHits,stepFallbacks=0,0,0,0,0
local function resetAggregate()
    aggregate.substeps=0;aggregate.iterations=0;aggregate.calls=0
    aggregate.searchEntries=0;aggregate.fallbacks=0;aggregate.limitHits=0
end
function C.setCounters(enabled)
    C.countersEnabled=enabled==true
    if C.countersEnabled then resetAggregate() end
    return C.countersEnabled
end
function C.resetCounters() resetAggregate() end
function C.counterSnapshot()
    return {substeps=aggregate.substeps,iterations=aggregate.iterations,calls=aggregate.calls,
        searchEntries=aggregate.searchEntries,fallbacks=aggregate.fallbacks,limitHits=aggregate.limitHits,
        limitRatio=aggregate.calls>0 and aggregate.limitHits/aggregate.calls or 0}
end
-- Per-evaluation geometry. Everything here can move during one substep's
-- iteration loop (candidate pose, a child's parent pose), so it is recomputed
-- for every constraint evaluation. Values that are fixed for one substep
-- (oldFootX/oldFootY/oldDistance, softAlpha/softGamma, the source anchor of a
-- parentless record and 3*h) are cached by step() and used here instead of
-- being recomputed inside the loop. The cache is overwritten at the start of
-- every substep; it is never read after a commit is published.
local function measure(r,i,rx,ry)
    local p=r.coupledPose;local parent=r.parent and r.parent.coupledPose
    local sx,sy
    if r.parent then sx,sy=source(r,i,rx,ry) else sx,sy=r.sourceX,r.sourceY end
    local fx,fy=foot(r,p)
    local dx,dy=fx-sx,fy-sy;local d=math.sqrt(dx*dx+dy*dy)
    if d<1e-9 then return p,parent,d end
    local nx,ny=dx/d,dy/d
    local g=(fx-p.x)*ny-(fy-p.y)*nx
    local gp=parent and ((sx-parent.x)*ny-(sy-parent.y)*nx) or 0
    local wp=parent and parent.weight or 0;local ip=parent and parent.inertia or 0
    local w=p.weight+wp
    return p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w
end
-- One constraint branch (soft or hard) from shared geometry. Formula and
-- arithmetic order are unchanged from the uncached solver.
local function evaluate(r,p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w,h,negLimit,limit,hard,apply)
    local alpha,gamma,lambda
    if hard then alpha,gamma,lambda=0,0,p.hardLambda else alpha,gamma,lambda=r.softAlpha,r.softGamma,p.tensionLambda end
    local residual=d-(hard and p.limit or r.takeup)+gamma*(d-r.oldDistance)-alpha*lambda
    local used=Rope.wrapAngle(p.angle-r.angle)
    local parentUsed=parent and Rope.wrapAngle(parent.angle-r.parent.angle) or 0
    local amount=math.max(-lambda,residual/((1+gamma)*(w+p.inertia*g*g+ip*gp*gp)+alpha))
    if math.abs(used-amount*p.inertia*g)>limit or math.abs(parentUsed+amount*ip*gp)>limit then
        if counting then stepLimitHits=stepLimitHits+1 end
        local low=math.max(-lambda,math.min(0,residual/((1+gamma)*w+alpha)))
        local high=math.max(0,residual/((1+gamma)*w+alpha))
        for k=1,28 do
            local q=(low+high)*.5
            local closure=w*q-g*turn(used,-q*p.inertia*g,negLimit,limit)+gp*turn(parentUsed,q*ip*gp,negLimit,limit)
            if (1+gamma)*closure+alpha*q<residual then low=q else high=q end
        end
        amount=(low+high)*.5
        if counting then stepSearch=stepSearch+28 end
    end
    local rotation=turn(used,-amount*p.inertia*g,negLimit,limit);local parentRotation=turn(parentUsed,amount*ip*gp,negLimit,limit)
    local error=math.abs(w*amount-g*rotation+gp*parentRotation)
    if not apply then return error end
    if hard then p.hardLambda=math.max(0,lambda+amount) else p.tensionLambda=math.max(0,lambda+amount) end
    p.x=p.x-nx*amount*p.weight;p.y=p.y-ny*amount*p.weight;p.angle=p.angle+rotation
    if parent then
        parent.x=parent.x+nx*amount*wp;parent.y=parent.y+ny*amount*wp;parent.angle=parent.angle+parentRotation
    else
        local vx,vy,speed=r.anchorVX,r.anchorVY,r.anchorSpeed
        if speed>.02 then r.reaction=r.reaction+amount/(h*h)*math.max(0,-(nx*vx+ny*vy)/speed) end
    end
    return error
end
local function tether(records,i,rx,ry,h,hard,apply,negLimit,limit)
    local r=records[i]
    if hard and r.coupledPose.allowance<=0 then return 0 end
    local p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w=measure(r,i,rx,ry)
    if w==nil then return 0 end
    if counting then stepCalls=stepCalls+1 end
    return evaluate(r,p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w,h,negLimit,limit,hard,apply)
end
-- After a full sweep both apply=false branches inspect the same poses, so the
-- shared geometry is computed once and both constraints are evaluated from it.
-- Never shared between apply=true calls: those move the bodies between calls.
local function residual(records,i,rx,ry,h,negLimit,limit)
    local r=records[i]
    local p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w=measure(r,i,rx,ry)
    if w==nil then return 0 end
    if counting then stepCalls=stepCalls+1 end
    local soft=evaluate(r,p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w,h,negLimit,limit,false,false)
    if p.allowance<=0 then return soft end
    if counting then stepCalls=stepCalls+1 end
    local hard=evaluate(r,p,parent,sx,sy,d,nx,ny,g,gp,wp,ip,w,h,negLimit,limit,true,false)
    return math.max(soft,hard)
end
local function publishCounters(group)
    if not counting then return end
    group.solverSubsteps=(group.solverSubsteps or 0)+1
    group.solverIterationsTotal=(group.solverIterationsTotal or 0)+stepIterations
    group.solverConstraintCalls=(group.solverConstraintCalls or 0)+stepCalls
    group.solverSearchEntries=(group.solverSearchEntries or 0)+stepSearch
    group.solverFallbacks=(group.solverFallbacks or 0)+stepFallbacks
    group.solverLimitHits=(group.solverLimitHits or 0)+stepLimitHits
    group.solverLimitRatio=group.solverConstraintCalls>0 and group.solverLimitHits/group.solverConstraintCalls or 0
    group.solverBackend='lua'
    aggregate.substeps=aggregate.substeps+1
    aggregate.iterations=aggregate.iterations+stepIterations
    aggregate.calls=aggregate.calls+stepCalls
    aggregate.searchEntries=aggregate.searchEntries+stepSearch
    aggregate.fallbacks=aggregate.fallbacks+stepFallbacks
    aggregate.limitHits=aggregate.limitHits+stepLimitHits
end
function C.step(records,cache,rx,ry,h,group)
    -- group.solverCounters is the shared backend-agnostic opt-in used by the
    -- native solver as well; setCounters() is the Lua-local equivalent.
    counting=C.countersEnabled==true or group.solverCounters==true
    if counting then
        if (group.solverIterations or 0)==0 then
            group.solverSubsteps=0;group.solverIterationsTotal=0;group.solverConstraintCalls=0
            group.solverSearchEntries=0;group.solverFallbacks=0;group.solverLimitHits=0;group.solverLimitRatio=0
        end
        stepIterations,stepCalls,stepSearch,stepLimitHits,stepFallbacks=0,0,0,0,0
    end
    group.nativeGap=0;group.nativeObstruction=nil;group.nativeUnconverged=false
    group.fallbackStep=false;group.takeupStep=false
    local friction=math.exp(-4*h)
    for _,r in ipairs(records) do
        local p=r.coupledPose or {};r.coupledPose=p
        p.x=r.x;p.y=r.y;p.angle=r.angle;p.weight=1/math.max(1,r.mass or 75)
        p.inertia=2*p.weight/((r.footprintRadius or .87)^2)
        p.tensionLambda=0;p.hardLambda=0;r.reaction=0;r.taut=false;r.blocked=false;r.ropeBlocked=nil
    end
    for i,r in ipairs(records) do
        local sx,sy,sz=source(r,i,rx,ry)
        if math.floor(sz)~=math.floor(r.z) or (sx-r.x)^2+(sy-r.y)^2>r.maxGapSquared then
            group.nativeGap=i;group.nativeGapX=sx;group.nativeGapY=sy;group.nativeGapZ=sz
            publishCounters(group);return
        end
        local p=r.coupledPose;p.sx=sx;p.sy=sy;p.sz=sz
        r.ax=r.ax or sx;r.ay=r.ay or sy
        local height=(sz+(r.anchorHeight or .25)-r.z-.025)*3
        local length=r.length or 4
        local reach=math.sqrt(math.max(.01,length*length-height*height))
        local stretched=length+math.min(.25,length*.05)
        p.allowance=r.gear and r.gear:getFullType()=='Base.Rope' and math.sqrt(math.max(.01,stretched*stretched-height*height))-reach or 0
        if not r.ropeConstraintReady then
            local fx,fy=foot(r,p);r.takeup=math.max(reach,math.sqrt((sx-fx)^2+(sy-fy)^2));r.ropeConstraintReady=true
        end
        local takingUp=(r.takeup or reach)>reach
        group.takeupStep=group.takeupStep or takingUp
        group.recoveryStep=group.recoveryStep or takingUp
        r.takeup=math.max(reach,(r.takeup or reach)-2*h)
        p.limit=r.takeup+p.allowance
    end
    for _,r in ipairs(records) do
        local p=r.coupledPose
        local vx,vy=r.vx+(r.pushX or 0)*h,r.vy+(r.pushY or 0)*h
        local speed=math.sqrt(vx*vx+vy*vy)
        local slide=speed>0 and math.max(0,1-9.81*.65*h/speed) or 0
        r.physicalVX=vx*slide;r.physicalVY=vy*slide
        r.physicalW=math.max(-3,math.min(3,(r.angularVelocity or 0)*friction))
        p.x=p.x+r.physicalVX*h;p.y=p.y+r.physicalVY*h;p.angle=p.angle+r.physicalW*h
    end
    -- Everything reused by the iteration loop is fixed for this substep only:
    -- r.x/r.y/r.angle and r.ax/r.ay do not change until the commit below, and
    -- allowance/weights are recomputed from the next substep's state.
    local turnLimit=3*h;local negLimit=-turnLimit
    for i,r in ipairs(records) do
        local p=r.coupledPose
        local oldX,oldY=foot(r,r)
        r.oldFootX=oldX;r.oldFootY=oldY
        local oldDX,oldDY=oldX-r.ax,oldY-r.ay
        r.oldDistance=math.sqrt(oldDX*oldDX+oldDY*oldDY)
        local parent=r.parent and r.parent.coupledPose
        local wp=parent and parent.weight or 0
        local w=p.weight+wp
        r.softAlpha=p.allowance>0 and w/(180*h*h) or 0
        r.softGamma=r.softAlpha>0 and 24/(180*h) or 0
        if not r.parent then
            local sx,sy
            if i==1 then sx,sy=rx,ry else sx,sy=r.sourceSample.x,r.sourceSample.y end
            r.sourceX=sx;r.sourceY=sy
            local vx,vy=(sx-r.ax)/h,(sy-r.ay)/h
            r.anchorVX=vx;r.anchorVY=vy
            r.anchorSpeed=math.sqrt(vx*vx+vy*vy)
        end
    end
    local tolerance=math.min(.0025,.001*h)
    local converged=false
    for iteration=1,256 do
        for j=1,#records do
            local i=iteration%2==1 and j or #records+1-j
            tether(records,i,rx,ry,h,false,true,negLimit,turnLimit);tether(records,i,rx,ry,h,true,true,negLimit,turnLimit)
        end
        local error=0
        for i=1,#records do
            error=math.max(error,residual(records,i,rx,ry,h,negLimit,turnLimit))
        end
        group.solverResidual=error;group.solverIterations=math.max(group.solverIterations or 0,iteration)
        if counting then stepIterations=iteration end
        if error<tolerance then converged=true;break end
    end
    if not converged then
        if counting then stepFallbacks=stepFallbacks+1 end
        group.nativeFallback=true;group.fallbackStep=true;group.recoveryStep=true
        for _,r in ipairs(records) do
            local p=r.coupledPose
            p.x=r.x+r.physicalVX*h;p.y=r.y+r.physicalVY*h
            p.angle=r.angle+r.physicalW*h
            r.reaction=0;p.tensionLambda=0;p.hardLambda=0
        end
        for i,r in ipairs(records) do
            local p=r.coupledPose;local sx,sy=source(r,i,rx,ry);local fx,fy=foot(r,p)
            local dx,dy=fx-sx,fy-sy;local d=math.sqrt(dx*dx+dy*dy)
            local pull=math.max(0,d-p.limit)
            if pull>0 then
                local amount=pull/p.weight;p.hardLambda=amount
                p.x=p.x-dx/d*pull;p.y=p.y-dy/d*pull
                if not r.parent then
                    local vx,vy=(sx-r.ax)/h,(sy-r.ay)/h;local speed=math.sqrt(vx*vx+vy*vy)
                    if speed>.02 then r.reaction=amount/(h*h)*math.max(0,-(dx*vx+dy*vy)/(d*speed)) end
                end
            end
        end
    end
    for _,r in ipairs(records) do
        local p=r.coupledPose;r.taut=p.tensionLambda+p.hardLambda>0;r.reaction=math.max(0,r.reaction)
    end
    -- A body already stopped by ground friction should not creep under a
    -- sub-threshold spring force. Keep stronger pulls and existing motion.
    for _,r in ipairs(records) do
        local p=r.coupledPose;local dx,dy=p.x-r.x,p.y-r.y
        local limit=9.81*.65*h*h
        if r.physicalVX==0 and r.physicalVY==0 and dx*dx+dy*dy<limit*limit then
            p.x=r.x;p.y=r.y
        end
    end
    -- Every candidate still passes the existing swept footprint and tether ray.
    -- Reject the entire coupled step on obstruction; do not leave half a chain moved.
    for i,r in ipairs(records) do
        local p=r.coupledPose
        local x,y,a,blocked=Geometry.resolve(r,p.x,p.y,p.angle,r.angle,cache)
        local sx,sy,sz=source(r,i,rx,ry);local fx,fy=foot(r,p)
        local why=Obstacles.check(cache,{x=sx,y=sy,z=sz},{x=fx,y=fy,z=r.z},(r.length or 4)+6)
        if blocked or why then
            group.nativeObstruction=why or Obstacles.blocked
            for _,b in ipairs(records) do b.vx=0;b.vy=0;b.angularVelocity=0;b.blocked=true;b.taut=false end
            publishCounters(group);return
        end
    end
    for i,r in ipairs(records) do
        local p=r.coupledPose
        r.fallbackDX=p.x-r.x;r.fallbackDY=p.y-r.y
        r.vx=(p.x-r.x)/h;r.vy=(p.y-r.y)/h;r.angularVelocity=Rope.wrapAngle(p.angle-r.angle)/h
        r.x=p.x;r.y=p.y;r.angle=p.angle
        r.ax,r.ay=source(r,i,rx,ry)
    end
    publishCounters(group)
end
return C

