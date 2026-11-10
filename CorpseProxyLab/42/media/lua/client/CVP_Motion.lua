-- Small delayed snapshot buffer: visual motion only, no client physics prediction.
local M={delay=250,capacity=8}
local sides={'a','b'}
-- Keep sample spacing in server time, independent of packet arrival jitter.
-- The lowest observed transit offset supplies the clock reference; approach a
-- better reference slowly so an unusually fast packet cannot jump playback.
function M.syncClock(clock,sampledAt,now)
    local offset=now-sampledAt
    -- Wall clocks may step without a server restart. Never mix those samples
    -- or spend minutes slewing across a discontinuity as if it were jitter.
    if not clock or sampledAt<clock.sampledAt or now<clock.receivedAt
        or math.abs((sampledAt-clock.sampledAt)-(now-clock.receivedAt))>10000 then
        return {offset=offset,target=offset,at=now,sampledAt=sampledAt,receivedAt=now}
    end
    clock.sampledAt=sampledAt;clock.receivedAt=now
    clock.target=math.min(clock.target,offset)
    return clock
end
function M.time(clock,now)
    if not clock then return now end -- Before the first confirmed snapshot.
    local elapsed=math.max(0,now-clock.at);clock.at=now
    clock.offset=math.max(clock.target,clock.offset-elapsed*.05)
    return now-clock.offset
end
-- Reuse a compact writer target; appearance and recovery descriptors remain in
-- their immutable snapshot instead of being deep-copied for pose playback.
function M.target(r,s)
    local old=r.target;local before=old and old.anchor;local after=s.source
    local changed=not old or old.source~=s.parent
        or (before and before.kind)~=(after and after.kind)
        or (before and before.key)~=(after and after.key)
        or (before and before.point)~=(after and after.point)
    if changed then r.samples=nil;r.visualPose=nil end
    local t=r.target or {};r.target=t
    t.object=s.body -- SP identity guard only; never sent through the wire.
    t.x=s.x;t.y=s.y;t.z=s.z;t.angle=s.angle;t.token=s.token;t.vehicle=s.vehicle
    t.source=s.parent;t.anchor=s.source;t.sourceSampledAt=s.sourceSampledAt
    t.anchorX=s.source and s.source.x;t.anchorY=s.source and s.source.y;t.anchorZ=s.source and s.source.z
    return t,changed
end
function M.push(r,s,time)
    local samples=r.samples or {};local last=samples[#samples]
    if last and (time<last.time or time-last.time>1000 or (not r.endpoint and s.z~=last.z) or s.vehicle~=last.vehicle
        or (s.x-last.x)^2+(s.y-last.y)^2>4096) then
        samples={};last=nil;r.visualPose=nil
    end
    local replace=last and time==last.time
    local sample=replace and last or #samples>=M.capacity and table.remove(samples,1) or {}
    sample.x=s.x;sample.y=s.y;sample.z=s.z;sample.angle=s.angle or 0;sample.vehicle=s.vehicle;sample.time=time
    sample.anchorX=s.anchorX;sample.anchorY=s.anchorY;sample.anchorZ=s.anchorZ;sample.sourceSampledAt=s.sourceSampledAt
    if not replace then samples[#samples+1]=sample end
    r.samples=samples
end
function M.pose(r,now,delay)
    local samples=r.samples
    if not samples or #samples==0 then return r.target end
    local time=now-(delay or M.delay)
    local a=samples[1];local b=a
    for i=2,#samples do
        b=samples[i]
        if b.time>=time then break end
        a=b
    end
    local alpha=b.time>a.time and math.max(0,math.min(1,(time-a.time)/(b.time-a.time))) or 0
    local x=a.x+(b.x-a.x)*alpha;local y=a.y+(b.y-a.y)*alpha
    local pose=r.visualPose
    pose=pose or {};r.visualPose=pose
    pose.x=x;pose.y=y;pose.z=r.endpoint and a.z+(b.z-a.z)*alpha or b.z
    -- Kahlua uses signed remainder for %, including negative snapshot angles.
    local shifted=b.angle-a.angle+math.pi
    local turn=shifted-math.floor(shifted/(2*math.pi))*(2*math.pi)-math.pi
    pose.angle=a.angle+turn*alpha
    pose.anchorX=a.anchorX and b.anchorX and a.anchorX+(b.anchorX-a.anchorX)*alpha or b.anchorX
    pose.anchorY=a.anchorY and b.anchorY and a.anchorY+(b.anchorY-a.anchorY)*alpha or b.anchorY
    pose.anchorZ=b.anchorZ
    pose.sourceSampledAt=b.sourceSampledAt;pose.sampledAt=b.time
    return pose
end
-- Pose playback owns world coordinates. Vehicle render alignment belongs only
-- to the vehicle endpoint; it must never translate confirmed body replicas.
function M.begin(host,displayTime,localAuthority)
    host.visualTime=displayTime
end
function M.present(r,pose,rows,host)
    r.visualRoot=r;r.drawDX=0;r.drawDY=0;r.visualRecovery=false
    if r.body and CVPBodyPresentation then
        host.visualOffsets=host.visualOffsets or {};host.visualOffsets[r.body]=r
    end
    return false
end
-- Endpoint buffers share the accepted snapshot timestamps with body buffers.
-- Topology changes reset only the affected section, never interpolate a new
-- attachment from the previous attachment's position.
function M.pushEndpoints(previous,graph,time,reset,bodies)
    local rows={}
    for id,link in pairs(graph.links) do
        local row=not reset and previous and previous[id]
        if not row or row.revision~=link.revision then row={revision=link.revision,a={},b={}} end
        for _,side in ipairs(sides) do
            local e=link[side];local r=row[side]
            r.endpoint=e
            local body=e.kind=='body' and bodies and bodies[e.key]
            r.localX=nil;r.localY=nil
            if body then
                local dx,dy=e.x-body.x,e.y-body.y;local c,s=math.cos(body.angle),math.sin(body.angle)
                r.localX=dx*c+dy*s;r.localY=-dx*s+dy*c;r.height=e.z-body.z
            end
            M.push(r,e,time)
        end
        rows[id]=row
    end
    return rows
end
function M.endpoints(rows,time,bodies,out)
    out=out or {}
    for id in pairs(out) do if not rows or not rows[id] then out[id]=nil end end
    for id,row in pairs(rows or {}) do
        local ends=row.display or {a={},b={}};row.display=ends;out[id]=ends
        for _,side in ipairs(sides) do
            local r=row[side];local e=r.endpoint;local pose=M.pose(r,time)
            local p=ends[side];p.kind=e.kind;p.key=e.key;p.point=e.point;p.holder=e.holder
            p.x=pose.x;p.y=pose.y;p.z=pose.z
            local body=e.kind=='body' and bodies and bodies[e.key]
            if body and r.localX then
                local c,s=math.cos(body.angle),math.sin(body.angle)
                p.x=body.x+c*r.localX-s*r.localY;p.y=body.y+s*r.localX+c*r.localY;p.z=body.z+r.height
            end
        end
    end
    return out
end
function M.unpresent(r,host)
    if not r or not r.body then return end
    if CVPBodyPresentation then CVPBodyPresentation.remove(r.body) end
    if host.visualOffsets then host.visualOffsets[r.body]=nil end
end
-- Resolve intermediate rope joints only when topology/row identity changes.
-- At most two visits per span; no graph traversal in the per-frame pose loop.
function M.bindJoints(rows,graph,index,host)
    local joints={};host.visualJoints=joints
    if not index then return end
    for key,r in pairs(rows) do for _,start in ipairs(index.byBody[key] or {}) do
        local edge=start
        while edge do
            local link=graph.links[edge.id];local e=link[edge.side=='a' and 'b' or 'a']
            if e.kind~='joint' or joints[e.key] then break end
            joints[e.key]=r
            local edges=index.byJoint[e.key]
            edge=edges and (edges[1].id~=edge.id and edges[1] or edges[2])
        end
    end end
end
-- Iterative parent-first traversal; missing parents are roots, cycles are skipped.
-- No recursion limit for long chains and no dependence on pairs/hash order.
function M.ordered(links)
    local ordered,children,waiting={},{},{}
    for id,r in pairs(links) do
        r.id=id
        local parent=r.target.source
        if parent and links[parent] then
            local list=children[parent] or {};children[parent]=list;list[#list+1]=r
            waiting[id]=true
        else ordered[#ordered+1]=r end
    end
    local i=1
    while i<=#ordered do
        local r=ordered[i];i=i+1
        for _,child in ipairs(children[r.id] or {}) do
            if waiting[child.id] then waiting[child.id]=nil;ordered[#ordered+1]=child end
        end
    end
    return ordered
end
return M
