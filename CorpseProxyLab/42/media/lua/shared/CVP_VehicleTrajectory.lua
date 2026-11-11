-- One confirmed trajectory per vehicle attachment, shared by every towing root.
-- All recovery decisions live here; the solver still owns collision and length.
local T={}
-- A packet is input data, not a physics tick. Keep its time independently of
-- polling, and replay only the confirmed interval; no extrapolation after loss.
local function accept(n,p,time,dt,speed,native,localMotion)
    if not n then n={x=p.x,y=p.y,z=p.z,changed=time,speed=speed,samples={}} end
    local dx,dy=p.x-n.x,p.y-n.y
    n.jump=math.sqrt(dx*dx+dy*dy);n.interval=time-n.changed
    n.correction=n.jump>math.max(3,speed*dt*1.5) or math.floor(p.z)~=math.floor(n.z)
    local sameFloor=math.floor(p.z)==math.floor(n.z)
    local forward=n.dx and dx*n.dx+dy*n.dy>=n.jump*.7
    local elapsed=n.interval/1000
    local budget=elapsed>=.25 and math.min(40,n.speed*elapsed*1.5+2)
        or math.min(16,math.min(speed,n.speed)*.75+2)
    n.acceptCorrection=n.correction and sameFloor and forward and math.min(speed,n.speed)>=2
        and elapsed>0 and elapsed<=2 and n.jump<=budget
    n.normal=sameFloor and forward and elapsed<=.5
        and n.jump<=math.max(.02,math.min(speed,n.speed)*elapsed*1.5)
    if #n.samples==0 or n.jump>0 or p.z~=n.z or native then
        if not native then
            -- A long local frame still has a confirmed physics interval. Keep
            -- both ends so the unconsumed clock remainder is not skipped.
            -- Packet gaps retain their separate transport recovery policy.
            if (not localMotion and elapsed>.25) or not sameFloor or n.jump>math.max(3,speed*elapsed*1.5+2) then n.samples={} end
            n.samples[#n.samples+1]={x=p.x,y=p.y,time=time}
        end
        if n.jump>.02 then n.dx=dx/n.jump;n.dy=dy/n.jump end
        n.x=p.x;n.y=p.y;n.z=p.z;n.changed=time
    end
    n.speed=speed;n.revision=(n.revision or 0)+1
    return n
end
function T.sample(tracks,vehicle,point,anchor,now,dt,localMotion,interpolationLag)
    local owner=vehicle.getNetPlayerId and vehicle:getNetPlayerId() or 0
    local track=tracks[vehicle]
    if not track or track.owner~=owner then
        track={owner=owner,frames={},resetAt=track and now or nil};tracks[vehicle]=track
    end
    point=point or 'hitch';local n=track[point]
    if n and n.at==now then return n end
    local speed=math.abs(vehicle:getCurrentSpeedKmHour())/3.6
    if not localMotion and CVPVehicleMotion and track.readAt~=now then
        local packet=CVPVehicleMotion.sample(vehicle);track.readAt=now
        if packet and packet.owner==owner and packet~=track.packet then
            track.offset=track.offset or now-packet.time
            local last=track.frames[#track.frames]
            if last and packet.time-last.packet.time>250 then
                -- A new history needs a new clock reference as well: the engine
                -- may resynchronize packet time after loading or reconnecting.
                track.frames={};track.offset=now-packet.time
            end
            track.frames[#track.frames+1]={packet=packet,time=packet.time+track.offset}
            track.packet=packet
        end
    end
    local reset=track.resetAt==now
    local sampleTime=now
    if localMotion and CVPVehicleMotion and CVPVehicleMotion.localTime then
        local clock=CVPVehicleMotion.localTime()
        if track.localTime and clock<track.localTime then n=nil;track.offset=nil;track.resetAt=now;reset=true end
        track.offset=track.offset or now-clock;track.localTime=clock
        sampleTime=clock+track.offset
    end
    if track.resetAt==now then n=nil;reset=true end
    local packet=track.packet
    if packet then
        if not n or n.packetTime~=packet.time then
            local offset=track.offset
            n=accept(n,{x=packet[point..'X'],y=packet[point..'Y'],z=packet.z},packet.time+offset,dt,packet.speed,true)
            n.offset=offset;n.packetTime=packet.time;n.native=true
        else n.jump=0;n.correction=false;n.acceptCorrection=false end
    elseif not n or not n.native then
        n=accept(n,anchor,sampleTime,dt,speed,false,localMotion)
    end
    if reset then n.correction=true;n.acceptCorrection=false;n.normal=false end
    -- Both modes sample at the consumed simulation time. MP alone needs a
    -- transport buffer; SP keeps the engine physics clock as its reference.
    local delay=localMotion and 0 or 150
    local samples=n.native and track.frames or n.samples
    local time=(localMotion and sampleTime or now)-delay-(interpolationLag or 0)*1000
    while #samples>2 and samples[2].time<=time do table.remove(samples,1) end
    local a=samples[1];local b=samples[2] or a
    local alpha=b.time>a.time and math.max(0,math.min(1,(time-a.time)/(b.time-a.time))) or 0
    local ax,ay,bx,by
    if n.native then ax=a.packet[point..'X'];ay=a.packet[point..'Y'];bx=b.packet[point..'X'];by=b.packet[point..'Y']
    else ax,ay,bx,by=a.x,a.y,b.x,b.y end
    n.hitchX=ax+(bx-ax)*alpha;n.hitchY=ay+(by-ay)*alpha
    n.at=now;n.tick=dt*1000;n.owner=owner;track[point]=n
    return n
end
function T.checkedSource(n,r,actual,dt)
    if not n or not n.normal or not r or not r.ax or r.recoveryUntil then return actual end
    -- Compare the pre-step body with the pre-step anchor. Every swept substep
    -- checks its own length against the interpolated anchor, without extra slack.
    return {x=r.ax,y=r.ay,z=actual.z}
end
function T.recover(n,r,source,target,capacity,now,obstruction)
    if not n or not r or not r.ax or obstruction or math.floor(source.z)~=math.floor(target.z) then return false end
    local dx,dy=source.x-target.x,source.y-target.y
    if dx*dx+dy*dy>(capacity+6+40)^2 then return false end
    local elapsed=now-(r.anchorAt or now)
    local rx,ry=source.x-r.ax,source.y-r.ay;local distance=math.sqrt(rx*rx+ry*ry)
    local resumed=elapsed>=250 and elapsed<=2000 and n.speed>=2 and n.dx
        and distance<=math.min(40,n.speed*elapsed/1000*1.5+2)
        and rx*n.dx+ry*n.dy>=distance*.7
    if r.recoveryUntil and n.correction and n.revision~=r.recoveryRevision then
        r.recoveryUntil=nil;return false
    end
    if not r.recoveryUntil and (n.acceptCorrection or resumed) then
        r.recoveryUntil=now+2000;r.recoveryRevision=n.revision
        return true,true
    end
    return r.recoveryUntil~=nil and now<r.recoveryUntil,false
end
function T.advance(n,r,actual,dt,recovering)
    local x,y=actual.x,actual.y
    if not recovering then x,y=n.hitchX,n.hitchY end
    local dx,dy=x-(r.ax or x),y-(r.ay or y);local distance=math.sqrt(dx*dx+dy*dy)
    local limit=math.max(12,n.speed*1.5)*math.max(0,dt)
    if distance>limit then x=(r.ax or x)+dx*limit/distance;y=(r.ay or y)+dy*limit/distance end
    -- Rate limiting is ordinary swept motion, not a state discontinuity.
    -- Keep its constraint reaction and velocity; only actual recovery may
    -- discard those, otherwise frame jitter releases the whole train's load.
    return x,y,recovering==true or n.correction==true
end
function T.finish(r,now,ready,recovering)
    local completed=r and r.recoveryUntil and (not recovering or not ready)
    if r then
        if completed then r.recoveryUntil=nil end
        if ready then r.anchorAt=now end
    end
    return completed
end
return T
