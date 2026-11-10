-- Bounded rope compliance / rigid chains + a ground-supported cosmetic curve.
-- XY are world tiles (metres); one PZ storey on Z is three metres.
local Rope={}
-- Kahlua's % is signed remainder; use floor to keep turns in [-pi, pi).
function Rope.wrapAngle(a)
    local shifted=a+math.pi
    return shifted-math.floor(shifted/(2*math.pi))*(2*math.pi)-math.pi
end
Rope.footOffset=0.65
Rope.anchorHeight=0.25
Rope.floorHeight=0.025
Rope.segments=16
-- Vehicle replication may correct its transform by many metres in one server tick.
-- Feed that correction into physics at bounded speed, rather than converting it
-- into an instantaneous pull and a huge constraint-derived body velocity.
function Rope.networkAnchor(r,ax,ay,dt,speed)
    -- Temporary stretch is preferable to an instantaneous body impulse.
    local dx,dy=ax-r.ax,ay-r.ay;local d=math.sqrt(dx*dx+dy*dy)
    local limit=math.max(12,math.abs(speed or 0)/3.6*1.5)*math.max(0,dt)
    if d>limit and d>0 then return r.ax+dx*limit/d,r.ay+dy*limit/d end
    return ax,ay
end
function Rope.feet(r,x,y)
    local fx,fy=r.attachLocalX or r.footLocalX or -Rope.footOffset,r.attachLocalY or r.footLocalY or 0
    local c,s=math.cos(r.angle),math.sin(r.angle)
    return (x or r.x)+c*fx-s*fy,(y or r.y)+s*fx+c*fy,(r.z or 0)+Rope.floorHeight
end
-- Soft contacts between attached bodies. Snapshot all forces before moving any body
-- so iteration order cannot favour one tether. No world teleport or live actor.
function Rope.separate(links,contacts)
    if contacts then for i=#contacts,1,-1 do contacts[i]=nil end end
    local firstRoot,same=nil,true
    for _,r in ipairs(links) do
        r.pushX=0;r.pushY=0;r.contactRoot=r.parent and r.parent.contactRoot or r
        if not firstRoot then firstRoot=r.contactRoot elseif firstRoot~=r.contactRoot then same=false end
    end
    if same then return end
    for i=1,#links-1 do local a=links[i]
        for j=i+1,#links do local b=links[j]
            if a.contactRoot~=b.contactRoot and not a.failed and not b.failed and math.floor(a.z)==math.floor(b.z) then
                local dx,dy=a.x-b.x,a.y-b.y
                local d=math.sqrt(dx*dx+dy*dy)
                if d<1.1 then
                    -- Reuse this exact contact set for load transmission; no second pair scan.
                    if contacts then contacts[#contacts+1]=a;contacts[#contacts+1]=b end
                    if d<0.001 then
                        -- Stable sideways split even for initially identical coordinates.
                        local angle=a.angle or 0;dx=-math.sin(angle);dy=math.cos(angle)
                    else dx=dx/d;dy=dy/d end
                    local force=45*(1.1-d)
                    a.pushX=a.pushX+dx*force;a.pushY=a.pushY+dy*force
                    b.pushX=b.pushX-dx*force;b.pushY=b.pushY-dy*force
                end
            end
        end
    end
    for _,r in ipairs(links) do
        local f=math.sqrt(r.pushX*r.pushX+r.pushY*r.pushY)
        if f>60 then r.pushX=r.pushX*60/f;r.pushY=r.pushY*60/f end
    end
end
function Rope.step(r,x,y,ax,ay,dt,az)
    if dt<=0 then return x,y,false end
    local count=math.max(1,math.ceil(dt*100-1e-9))
    local h=dt/count
    local height=((az or r.z or 0)+(r.anchorHeight or Rope.anchorHeight)-(r.z or 0)-Rope.floorHeight)*3
    local length=r.length or 4
    local reach=math.sqrt(math.max(0.01,length*length-height*height))
    local elastic=r.gear and r.gear:getFullType()=='Base.Rope'
    local stretchedLength=length+math.min(0.25,length*0.05)
    local allowance=elastic and math.sqrt(math.max(0.01,stretchedLength*stretchedLength-height*height))-reach or 0
    local anchorVX,anchorVY=(ax-r.ax)/dt,(ay-r.ay)/dt
    -- Old saves or hot reload can start overstretched. Take up that existing error
    -- gradually; normal driving thereafter enforces length on every substep.
    if not r.ropeConstraintReady then
        local fx,fy=Rope.feet(r,x,y)
        r.takeup=math.max(reach,math.sqrt((r.ax-fx)^2+(r.ay-fy)^2))
        r.ropeConstraintReady=true
    end
    local taut=false;r.reaction=0
    for i=1,count do
        local tx=r.ax+(ax-r.ax)*i/count;local ty=r.ay+(ay-r.ay)*i/count
        local ox,oy=x,y
        r.vx=r.vx+(r.pushX or 0)*h;r.vy=r.vy+(r.pushY or 0)*h
        local speed=math.sqrt(r.vx*r.vx+r.vy*r.vy)
        local friction=speed>0 and math.max(0,1-9.81*.65*h/speed) or 0
        r.vx=r.vx*friction;r.vy=r.vy*friction
        x=x+r.vx*h;y=y+r.vy*h
        local fx,fy=Rope.feet(r,x,y)
        local dx,dy=tx-fx,ty-fy;local d=math.sqrt(dx*dx+dy*dy)
        r.correctionStep=r.correctionStep or (r.takeup or reach)>reach
        r.takeup=math.max(reach,(r.takeup or reach)-2*h)
        local stepTaut=d>r.takeup
        if stepTaut then
            -- Native leg direction depends on whether the body fell on its front.
            local footAngle=math.atan2(r.attachLocalY or r.footLocalY or 0,r.attachLocalX or r.footLocalX or -Rope.footOffset)
            local wanted=math.atan2(ty-y,tx-x)-footAngle
            local delta=Rope.wrapAngle(wanted-r.angle)
            r.angle=r.angle+math.max(-3*h,math.min(3*h,delta))
            fx,fy=Rope.feet(r,x,y);dx=tx-fx;dy=ty-fy;d=math.sqrt(dx*dx+dy*dy)
            if d>r.takeup then
                local excess=d-r.takeup
                local pull=excess
                if elastic then
                    -- Implicit damped spring: tension only, no compressive push.
                    -- Relative endpoint speed damps take-up without storing a
                    -- large recoil impulse. A hard cap limits stretch to 5%/25cm.
                    local relative=((anchorVX-r.vx)*dx+(anchorVY-r.vy)*dy)/d
                    pull=math.max(0,(180*h*h*excess+24*h*h*relative)/(1+24*h+180*h*h))
                    pull=math.min(excess,math.max(pull,excess-allowance))
                end
                local speed=math.sqrt(anchorVX*anchorVX+anchorVY*anchorVY)
                if speed>.02 then
                    r.reaction=r.reaction+math.max(0,r.mass or 0)*pull/(h*h)*math.max(0,(dx*anchorVX+dy*anchorVY)/(d*speed))/count
                end
                local correction=pull/d
                x=x+dx*correction;y=y+dy*correction
                dx=dx*(1-correction);dy=dy*(1-correction);d=d-pull
            end
            r.vx=(x-ox)/h;r.vy=(y-oy)/h
            taut=true
        end
        -- Resolve spacing during actual motion, including coasting between
        -- vehicle physics updates. Never create motion under a loose tether.
        -- This positional contact does not inject velocity or another car force.
        if stepTaut and (r.spreadSpeed or 0)>0 and (x~=ox or y~=oy) then
            if d>0 then
                -- At steady speed the constraint correction is tiny: most
                -- travel comes from velocity. Bound spacing by actual travel,
                -- not that residual, or a dense moving group never opens up.
                local travel=math.sqrt((x-ox)^2+(y-oy)^2)
                local push=r.spreadPush or 0
                if r.spreadOffset~=nil then
                    local remaining=r.spreadOffset+(tx-x)*r.spreadNX+(ty-y)*r.spreadNY
                    push=remaining/r.spreadScale;r.spreadRemaining=math.abs(remaining)
                end
                local shift=math.max(-1,math.min(1,push))*math.min(travel,r.spreadSpeed*(h+2*travel))
                shift=shift*((-dy*r.spreadNX+dx*r.spreadNY)/d)
                -- Never step beyond the remaining lateral correction.
                if r.spreadRemaining then
                    shift=math.max(-r.spreadRemaining,math.min(r.spreadRemaining,shift))
                    r.spreadRemaining=math.max(0,r.spreadRemaining-math.abs(shift))
                end
                local scale=d/math.sqrt(d*d+shift*shift)
                local sideX=(-dx-dy/d*shift)*scale+dx
                local sideY=(-dy+dx/d*shift)*scale+dy
                x=x+sideX;y=y+sideY
            end
        end
    end
    r.ax=ax;r.ay=ay
    return x,y,taut
end

local function endpoints(r,ax,ay,az)
    local fx,fy,fz=Rope.feet(r)
    if r.endHeight~=nil then fz=(r.z or 0)+r.endHeight end
    return ax,ay,(az+(r.anchorHeight or Rope.anchorHeight))*3,fx,fy,fz*3
end
local function distance(ax,ay,az,bx,by,bz)
    return math.sqrt((ax-bx)^2+(ay-by)^2+(az-bz)^2)
end
function Rope.seed(r,ax,ay,az)
    local ax,ay,az,bx,by,bz=endpoints(r,ax,ay,az)
    local dx,dy=bx-ax,by-ay;local horizontal=math.sqrt(dx*dx+dy*dy)
    local nx,ny=-math.sin(r.angle),math.cos(r.angle)
    if horizontal>0.001 then nx=-dy/horizontal;ny=dx/horizontal end
    if (r.slot or 1)%2==0 then nx=-nx;ny=-ny end
    local length=math.max(r.length or 4,distance(ax,ay,az,bx,by,bz));local n=r.ropeSegments or Rope.segments
    local elastic=r.gear and r.gear:getFullType()=='Base.Rope'
    local function curve(bend,write)
        local lx,ly,lz=ax,ay,az;local total=0;local points=write and {} or nil
        for i=0,n do local t=i/n;local s=(elastic and (math.sin(2*math.pi*t)*0.75+math.sin(math.pi*t)*0.25) or math.sin(math.pi*t))*bend
            local x,y,z=ax+dx*t+nx*s,ay+dy*t+ny*s,az+(bz-az)*t
            if i>0 then total=total+distance(lx,ly,lz,x,y,z) end
            if write then points[i+1]={x=x,y=y,z=z,vx=0,vy=0,vz=0} end
            lx,ly,lz=x,y,z
        end
        return total,points
    end
    local low,high=0,length
    for i=1,18 do local mid=(low+high)/2;if curve(mid)>length then high=mid else low=mid end end
    local _,points=curve((low+high)/2,true)
    r.ropePoints=points;r.ropeShapeVersion=4;r.ropeSleeping=false;r.ropeQuiet=0;r.ropeStill=0
    return points
end
function Rope.shape(r,ax,ay,az,dt)
    local points=r.ropePoints
    if not points or r.ropeShapeVersion~=4 or #points~=(r.ropeSegments or Rope.segments)+1 then points=Rope.seed(r,ax,ay,az) end
    local ax,ay,az,bx,by,bz=endpoints(r,ax,ay,az);local n=#points-1
    local function common(u,v)
        if u*v<=0 then return 0 end
        return u>0 and math.min(u,v) or math.max(u,v)
    end
    -- Horizontal frame translation does not change slack or wake a settled curve.
    -- Vertical motion still needs the floor constraint below.
    local mx=common(ax-points[1].x,bx-points[n+1].x)
    local my=common(ay-points[1].y,by-points[n+1].y)
    if mx~=0 or my~=0 then for _,p in ipairs(points) do p.x=p.x+mx;p.y=p.y+my end end
    local moved=distance(ax,ay,az,points[1].x,points[1].y,points[1].z)
        +distance(bx,by,bz,points[n+1].x,points[n+1].y,points[n+1].z)
    if r.ropeSleeping and moved<0.00000001 and r.ropeShapeLength==r.length then
        -- A sleeping curve may still have translated with both endpoints.
        return points,mx==0 and my==0
    end
    if r.ropeShapeLength~=r.length then r.ropeStill=0;r.ropeQuiet=0;r.ropeSleeping=false end
    r.ropeShapeLength=r.length
    if moved>=0.0001 then r.ropeSleeping=false;r.ropeQuiet=0;r.ropeStill=0 end
    r.ropeStill=(r.ropeStill or 0)+math.max(0,math.min(dt or 0,1/30))
    local endDistance=distance(ax,ay,az,bx,by,bz)
    if endDistance>=(r.length or 4)-0.01 then
        -- Transport remaining bends with the exact endpoints and let them decay.
        -- Instant straightening used to teleport interior nodes at this threshold.
        local elastic=r.gear and r.gear:getFullType()=='Base.Rope'
        local decayDt=math.max(0,math.min(dt or 0,0.1))
        local keep=elastic and math.exp(-18*decayDt) or 0
        local straighten=0.9*decayDt
        local first,last=points[1],points[n+1]
        local sx,sy,sz,ex,ey,ez=first.x,first.y,first.z,last.x,last.y,last.z
        local residual=0
        local floor=((r.z or 0)+Rope.floorHeight)*3
        local spanX,spanY,spanZ=bx-ax,by-ay,bz-az
        local oldX,oldY,oldZ=ex-sx,ey-sy,ez-sz
        for i=1,n+1 do local p=points[i];local t=(i-1)/n
            local x,y,z=ax+spanX*t,ay+spanY*t,az+spanZ*t
            local dx,dy,dz=p.x-(sx+oldX*t),p.y-(sy+oldY*t),p.z-(sz+oldZ*t)
            local blend=keep
            if elastic then
                local bend=math.sqrt(dx*dx+dy*dy+dz*dz)
                if bend>0 then blend=math.max(blend,1-straighten/bend) end
            end
            dx=dx*blend;dy=dy*blend;dz=dz*blend
            residual=math.max(residual,dx*dx+dy*dy+dz*dz)
            -- Motion of the attachment frame is not free rope velocity.
            p.vx=0;p.vy=0;p.vz=0
            p.x=x+dx;p.y=y+dy;p.z=math.max(floor,z+dz)
        end
        r.ropeSleeping=moved<0.0001 and residual<0.00000001
        return points
    end
    local sx,sy,sz=points[1].x,points[1].y,points[1].z
    local ex,ey,ez=points[n+1].x,points[n+1].y,points[n+1].z
    -- This is the cosmetic curve, not the towing constraint above. Never catch
    -- up multiple expensive solver steps after a slow frame (positive feedback).
    dt=math.max(0,math.min(dt or 0,1/30))
    if dt==0 then return points end
    local h=dt
    local damping=math.exp(-12*h)
    local floor=((r.z or 0)+Rope.floorHeight)*3
    -- Only common translation may move the whole curve. Differential endpoint
    -- motion must travel through segment constraints, never scale the slack.
    local mz=common(az-sz,bz-ez)
    for i=2,n do local p=points[i]
        p.z=math.max(floor,p.z+mz)
    end
    local first,last=points[1],points[n+1]
    first.x=sx+(ax-sx);first.y=sy+(ay-sy);first.z=sz+(az-sz)
    last.x=ex+(bx-ex);last.y=ey+(by-ey);last.z=ez+(bz-ez)
    for i=2,n do local p=points[i]
        p.ox=p.x;p.oy=p.y;p.oz=p.z
        p.x=p.x+p.vx*damping*h;p.y=p.y+p.vy*damping*h;p.z=math.max(floor,p.z+(p.vz*damping-9.81*h)*h)
    end
    local rest=math.max(r.length or 4,distance(first.x,first.y,first.z,last.x,last.y,last.z))/n
    -- Alternate sweeps to avoid biasing slack towards either attachment.
    for pass=1,r.ropePasses or 8 do
        local reverse=pass%2==0
        for k=1,n do
            local i=reverse and n+1-k or k
            local p,q=points[i],points[i+1]
            local dx,dy,dz=q.x-p.x,q.y-p.y,q.z-p.z;local d=math.sqrt(dx*dx+dy*dy+dz*dz)
            if d>0.000001 then
                local wp=i==1 and 0 or 1;local wq=i==n and 0 or 1
                local error=(d-rest)/(d*(wp+wq))
                p.x=p.x+dx*error*wp;p.y=p.y+dy*error*wp;p.z=math.max(floor,p.z+dz*error*wp)
                q.x=q.x-dx*error*wq;q.y=q.y-dy*error*wq;q.z=math.max(floor,q.z-dz*error*wq)
            end
        end
    end
    local maxSpeed2=0
    for i=2,n do local p=points[i]
        p.vx=(p.x-p.ox)/h;p.vy=(p.y-p.oy)/h;p.vz=(p.z-p.oz)/h
        -- Constraint correction is not a source of unbounded kinetic energy.
        local speed=math.sqrt(p.vx*p.vx+p.vy*p.vy+p.vz*p.vz)
        if speed>35 then p.vx=p.vx*35/speed;p.vy=p.vy*35/speed;p.vz=p.vz*35/speed end
        maxSpeed2=math.max(maxSpeed2,p.vx*p.vx+p.vy*p.vy+p.vz*p.vz)
    end
    if moved<0.0001 and maxSpeed2<0.0004 then r.ropeQuiet=(r.ropeQuiet or 0)+dt else r.ropeQuiet=0 end
    -- Finite constraint passes can leave a tiny limit cycle even at rest.
    -- Sleep only after fixed endpoints and low residual motion; movement wakes above.
    if r.ropeQuiet>0.5 or r.ropeStill>1.5 and maxSpeed2<0.01 then
        r.ropeSleeping=true
        for i=2,n do local p=points[i];p.vx=0;p.vy=0;p.vz=0 end
    end
    return points
end
return Rope
