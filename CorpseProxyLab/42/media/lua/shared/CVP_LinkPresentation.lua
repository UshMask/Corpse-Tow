-- Client/SP presentation consumes resolved endpoints. It never changes bodies,
-- equipment, permissions or saved link lengths; the native scene owns frame copies.
local Rope=require 'CVP_Rope'
local Presentation={};Presentation.__index=Presentation
local simplifyAt,restoreAt=16,12
local function empty(t) for _ in pairs(t) do return false end;return true end
-- With no keep set, remove the entire collection. Leave Lua state intact until
-- all removals succeed so a failed clear/update can be retried.
local function removeMissing(previous,keep)
    for id in pairs(previous) do
        if not keep or not keep[id] then CVPFreeRopeScene.remove(id) end
    end
end
function Presentation.new(host) return setmetatable({curves={},host=host,held={},details={}},Presentation) end
local function hand(host,e,out)
    local p=host.players and e.kind=='held' and host.players[e.holder]
    if p and CVPVisualAttachment then
        if CVPVisualAttachment.hand(p,out) then
            out.kind=e.kind;out.holder=e.holder;out.key=nil;out.point=nil
            return out,p
        end
    end
    return e,p
end
local function bodyPoint(host,ref,e,poses,out)
    if ref.kind=='joint' then
        local visual=host.visualJoints and host.visualJoints[ref.key]
        if not visual then return e end
        if visual.visualRecovery then return nil end
        out.kind=e.kind;out.key=e.key;out.point=nil;out.holder=nil
        out.x=e.x+(visual.drawDX or 0);out.y=e.y+(visual.drawDY or 0);out.z=e.z
        return out
    end
    if ref.kind~='body' then return e end
    local pose=host.displayBodies and host.displayBodies[ref.key]
    if host.displayBodies and not pose then return nil end
    local b=pose and pose.body or host.body(ref)
    if not b then return nil end
    local visual=host.visualOffsets and host.visualOffsets[b]
    if visual and visual.visualRecovery then return nil end
    local dx,dy=0,0
    if not pose then
        pose=poses[b]
        if not pose then pose={x=b:getX(),y=b:getY(),z=b:getZ()};poses[b]=pose end
    end
    out.kind=e.kind;out.key=e.key;out.point=e.point;out.holder=nil
    if not b.getGrabLegsPosition or b.isAnimal and b:isAnimal() then
        out.x=e.x+dx;out.y=e.y+dy;out.z=e.z
    else
        out.x=pose.x+(e.x-pose.x)*.75+dx;out.y=pose.y+(e.y-pose.y)*.75+dy;out.z=pose.z+.04
    end
    return out
end
-- Share only visually identical bindings; rope and chain remain distinguishable.
function Presentation.bindingId(link,side)
    local ref=link[side]
    if ref.kind=='vehicle' then
        return 'binding:vehicle:'..#ref.key..':'..ref.key..':'..(ref.point or 'hitch')..':'..
            (link.material=='Base.Rope' and 'rope' or 'chain')
    end
    return 'binding:'..link.id..':'..side
end
local ring={}
for i=0,8 do local a=i/8*math.pi*2;ring[i+1]={x=(math.cos(a)-1)*.035,y=math.sin(a)*.035} end
function Presentation:detail(id,link,ref,e,keep,players,car)
    if not CVPVisualAttachment or (ref.kind~='body' and ref.kind~='vehicle' and ref.kind~='horse') then return end
    if keep[id] then return end
    local near=false
    for _,p in ipairs(players) do
        if (p.x-e.x)^2+(p.y-e.y)^2<6^2 then near=true;break end
    end
    if not near then return end
    local chain=link.material~='Base.Rope'
    local old=self.details[id]
    if old and not old.uploadPending and old.x==e.x and old.y==e.y and old.z==e.z and old.chain==chain and old.car==car
        and old.point==ref.point and old.kind==ref.kind then keep[id]=old;return end
    -- Compact round knot; decorative only, independent of body dimensions.
    local state=old or {}
    local count=(ref.kind=='body' or ref.kind=='horse') and 2 or #ring
    local points=state.points
    if not points or #points~=count then
        points={};for i=1,count do points[i]={} end
    end
    local height=e.z*3
    if count==2 then
        for i=1,2 do local p=points[i]
            p.x=i==1 and e.x-.03 or e.x+.03;p.y=e.y;p.z=height
        end
    else
        local floorHeight=math.max(math.floor(e.z)*3+.035,height)
        for i,offset in ipairs(ring) do local p=points[i]
            p.x=e.x+offset.x;p.y=e.y+offset.y;p.z=floorHeight
        end
    end
    -- Java copies points before publishing; these tables belong only to this writer.
    self.details[id]=state -- Own the ID even if upload or vehicle binding fails.
    state.uploadPending=true
    CVPFreeRopeScene.update(id,points,chain)
    if ref.kind=='vehicle' and (not old or old.car~=car or old.point~=ref.point) then CVPFreeRopeScene.vehicle(id,car,true,ref.point) end
    state.x=e.x;state.y=e.y;state.z=e.z;state.chain=chain;state.car=car
    state.point=ref.point;state.kind=ref.kind;state.points=points;state.uploadPending=nil
    keep[id]=state
end
function Presentation:clear()
    self.attachmentRows=nil -- Release the former batch cache from development sessions.
    self.crowded=false
    if empty(self.curves) and empty(self.details) and empty(self.held) then return end
    if CVPFreeRopeScene then removeMissing(self.curves) end
    if CVPFreeRopeScene then removeMissing(self.details) end
    if CVPVisualAttachment then for p in pairs(self.held) do CVPVisualAttachment.release(p) end end
    self.details={};self.held={}
    self.curves={}
end
function Presentation:update(graph,samples,dt)
    if isServer() then return true end
    if empty(graph.links) then self:clear();return true end
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    if options and not options:getOption('ShowRopes'):getValue() then self:clear();return true end
    if not CVPFreeRopeScene or not CVPFreeRopeScene.shape then return false,'free rope native renderer unavailable' end
    local quality=options and options:getOption('RopeQuality')
    local linkCount=0
    for _ in pairs(graph.links) do
        linkCount=linkCount+1
        if linkCount>=simplifyAt then break end
    end
    if linkCount>=simplifyAt then self.crowded=true
    elseif linkCount<=restoreAt then self.crowded=false end
    -- Reuse existing quality levels; hysteresis avoids repeated curve reseeding
    -- when links are added/removed near the threshold. Manual low stays low.
    local simple=self.crowded or quality and quality:getValue()==2
    samples=samples or self.host.samples(graph)
    local keep,held,details={},{},{}
    self.shapeElapsed=(self.shapeElapsed or 0)+math.max(0,dt)
    local shapeDue=self.shapeElapsed+1e-9>=1/60
    local shapeDt=self.shapeElapsed
    if shapeDue then self.shapeElapsed=0 end
    local bodyPoses={} -- Valid only during this synchronous presentation update.
    local players={}
    if CVPVisualAttachment then for i=0,getNumActivePlayers()-1 do local p=getSpecificPlayer(i)
        if p then players[#players+1]={x=p:getX(),y=p:getY()} end
    end end
    for id,link in pairs(graph.links) do
        local ends=samples[id]
        local a,b
        if ends then a,b=ends.a,ends.b end
        if a and b then
            local r=self.curves[id]
            if not r then
                r={slot=1,angle=0,attachLocalX=0,attachLocalY=0,anchorHeight=0}
                self.curves[id]=r -- Keep ownership through any partial update.
            end
            -- Writer-owned scratch; never overwrite the authoritative samples.
            r.visualA=r.visualA or {};r.visualB=r.visualB or {}
            a=bodyPoint(self.host,link.a,a,bodyPoses,r.visualA)
            b=bodyPoint(self.host,link.b,b,bodyPoses,r.visualB)
            if a and b then
            local pa,pb;a,pa=hand(self.host,a,r.visualA);b,pb=hand(self.host,b,r.visualB)
            if pa and CVPVisualAttachment then held[pa]=true;self.held[pa]=true;CVPVisualAttachment.carry(pa,link.material) end
            if pb and pb~=pa and CVPVisualAttachment then held[pb]=true;self.held[pb]=true;CVPVisualAttachment.carry(pb,link.material) end
            if r.kindA~=link.a.kind or r.kindB~=link.b.kind then
                r.nativeShape=nil;r.shaped=nil
                r.kindA=link.a.kind;r.kindB=link.b.kind
            end
            r.grounded=(link.a.kind=='ground' or link.a.kind=='joint') and
                (link.b.kind=='ground' or link.b.kind=='joint') and
                a.z-math.floor(a.z)<=Rope.floorHeight+.001 and b.z-math.floor(b.z)<=Rope.floorHeight+.001
            r.x=b.x;r.y=b.y;r.z=math.floor(b.z);r.endHeight=b.z-r.z;r.length=link.length
            r.ropeSegments=simple and 8 or Rope.segments;r.ropePasses=simple and 4 or 8
            if shapeDue or not r.shaped then
                CVPFreeRopeScene.shape(id,r,a.x,a.y,a.z,shapeDt,link.material~='Base.Rope');r.shaped=true
            else
                CVPFreeRopeScene.endpoints(id,a.x,a.y,a.z,b.x,b.y,b.z)
            end
            local car=self.host and self.host.vehicle and
                (a.kind=='vehicle' and self.host.vehicle(a) or b.kind=='vehicle' and self.host.vehicle(b))
            local start=a.kind=='vehicle'
            local point=start and a.point or b.point
            if r.car~=car or r.carStart~=start or r.carPoint~=point then CVPFreeRopeScene.vehicle(id,car or nil,start,point) end
            r.car=car;r.carStart=start;r.carPoint=point;keep[id]=r
            self:detail(Presentation.bindingId(link,'a'),link,link.a,a,details,players,link.a.kind=='vehicle' and car or nil)
            self:detail(Presentation.bindingId(link,'b'),link,link.b,b,details,players,link.b.kind=='vehicle' and car or nil)
            end
        end
    end
    removeMissing(self.curves,keep)
    removeMissing(self.details,details)
    if CVPVisualAttachment then for p in pairs(self.held) do if not held[p] then CVPVisualAttachment.release(p) end end end
    self.details=details;self.held=held
    self.curves=keep;return true
end
return Presentation
