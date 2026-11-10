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
local function turn(used,requested,h)
    return math.max(-3*h,math.min(3*h,used+requested))-used
end
local function tether(records,i,rx,ry,h,hard,apply)
    local r=records[i];local p=r.coupledPose;local parent=r.parent and r.parent.coupledPose
    if hard and p.allowance<=0 then return 0 end
    local sx,sy=source(r,i,rx,ry);local fx,fy=foot(r,p)
    local dx,dy=fx-sx,fy-sy;local d=math.sqrt(dx*dx+dy*dy)
    if d<1e-9 then return 0 end
    local nx,ny=dx/d,dy/d
    local g=(fx-p.x)*ny-(fy-p.y)*nx
    local gp=parent and ((sx-parent.x)*ny-(sy-parent.y)*nx) or 0
    local wp=parent and parent.weight or 0;local ip=parent and parent.inertia or 0
    local w=p.weight+wp
    local alpha=not hard and p.allowance>0 and w/(180*h*h) or 0
    local gamma=alpha>0 and 24/(180*h) or 0
    local lambda=hard and p.hardLambda or p.tensionLambda
    local oldX,oldY=foot(r,r)
    -- Constant-length sideways motion must not generate damping tension.
    local oldDX,oldDY=oldX-r.ax,oldY-r.ay
    local displacement=d-math.sqrt(oldDX*oldDX+oldDY*oldDY)
    local residual=d-(hard and p.limit or r.takeup)+gamma*displacement-alpha*lambda
    local used=Rope.wrapAngle(p.angle-r.angle)
    local parentUsed=parent and Rope.wrapAngle(parent.angle-r.parent.angle) or 0
    local amount=math.max(-lambda,residual/((1+gamma)*(w+p.inertia*g*g+ip*gp*gp)+alpha))
    if math.abs(used-amount*p.inertia*g)>3*h or math.abs(parentUsed+amount*ip*gp)>3*h then
        local low=math.max(-lambda,math.min(0,residual/((1+gamma)*w+alpha)))
        local high=math.max(0,residual/((1+gamma)*w+alpha))
        for k=1,28 do
            local q=(low+high)*.5
            local closure=w*q-g*turn(used,-q*p.inertia*g,h)+gp*turn(parentUsed,q*ip*gp,h)
            if (1+gamma)*closure+alpha*q<residual then low=q else high=q end
        end
        amount=(low+high)*.5
    end
    local rotation=turn(used,-amount*p.inertia*g,h);local parentRotation=turn(parentUsed,amount*ip*gp,h)
    local error=math.abs(w*amount-g*rotation+gp*parentRotation)
    if not apply then return error end
    if hard then p.hardLambda=math.max(0,lambda+amount) else p.tensionLambda=math.max(0,lambda+amount) end
    p.x=p.x-nx*amount*p.weight;p.y=p.y-ny*amount*p.weight;p.angle=p.angle+rotation
    if parent then
        parent.x=parent.x+nx*amount*wp;parent.y=parent.y+ny*amount*wp;parent.angle=parent.angle+parentRotation
    else
        local vx,vy=(sx-r.ax)/h,(sy-r.ay)/h;local speed=math.sqrt(vx*vx+vy*vy)
        if speed>.02 then r.reaction=r.reaction+amount/(h*h)*math.max(0,-(nx*vx+ny*vy)/speed) end
    end
    return error
end
function C.step(records,cache,rx,ry,h,group)
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
            group.nativeGap=i;group.nativeGapX=sx;group.nativeGapY=sy;group.nativeGapZ=sz;return
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
    local tolerance=math.min(.0025,.001*h)
    local converged=false
    for iteration=1,256 do
        for j=1,#records do
            local i=iteration%2==1 and j or #records+1-j
            tether(records,i,rx,ry,h,false,true);tether(records,i,rx,ry,h,true,true)
        end
        local error=0
        for i=1,#records do
            error=math.max(error,tether(records,i,rx,ry,h,false,false),tether(records,i,rx,ry,h,true,false))
        end
        group.solverResidual=error;group.solverIterations=math.max(group.solverIterations or 0,iteration)
        if error<tolerance then converged=true;break end
    end
    if not converged then
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
            return
        end
    end
    for i,r in ipairs(records) do
        local p=r.coupledPose
        r.fallbackDX=p.x-r.x;r.fallbackDY=p.y-r.y
        r.vx=(p.x-r.x)/h;r.vy=(p.y-r.y)/h;r.angularVelocity=Rope.wrapAngle(p.angle-r.angle)/h
        r.x=p.x;r.y=p.y;r.angle=p.angle
        r.ax,r.ay=source(r,i,rx,ry)
    end
end
return C

