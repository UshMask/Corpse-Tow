-- Rebuild one loaded vehicle group atomically; equipment keeps its stable key.
local Core=require 'CVP_Core'
local World=require 'CVP_World'
local Rope=require 'CVP_Rope'
local R={}
local function xy(r) return r.body:getX(),r.body:getY() end
local function distance(a,b)
    local ax,ay=a.x,a.y;local bx,by=b.x,b.y
    return math.sqrt((ax-bx)^2+(ay-by)^2)
end
function R.plan(v,rows)
    if #rows<2 or #rows>World.maxChain() then return nil,'IGUI_CVP_RewireLimit' end
    local ax,ay=require('CVP_Geometry').anchor(v)
    local pool,points={},{}
    for _,r in ipairs(rows) do local x,y=xy(r);points[r]={x=x,y=y};pool[#pool+1]=r end
    local order={};local last={x=ax,y=ay}
    while #pool>0 do
        local best,bd
        for i,r in ipairs(pool) do local d=distance(last,points[r])
            if d<=8 and (not bd or d<bd or d==bd and r.connection.id<pool[best].connection.id) then best,bd=i,d end
        end
        if not best then return nil,'IGUI_CVP_RewireSpread' end
        local r=table.remove(pool,best);order[#order+1]=r;last=points[r]
    end
    local function length(list)
        local d=0;local prev={x=ax,y=ay}
        for _,r in ipairs(list) do d=d+distance(prev,points[r]);prev=points[r] end
        return d
    end
    -- Preserve a shorter existing train; never worsen it with a greedy restart.
    local child,root={},nil;local roots=0
    for _,r in ipairs(rows) do if r.parent then child[r.parent]=r else root=r;roots=roots+1 end end
    if roots==1 then
        local existing,seen={},{};local r=root
        while r and not seen[r] do seen[r]=true;existing[#existing+1]=r;r=child[r] end
        if #existing==#rows and length(existing)<=length(order) then order=existing end
    end
    -- Bounded 2-opt: reversing a segment only changes its two outer edges.
    for pass=1,4 do local changed=false
        for i=1,#order-1 do for j=i+1,#order do
            local a=i==1 and {x=ax,y=ay} or points[order[i-1]]
            local b,c=points[order[i]],points[order[j]]
            local d=j<#order and points[order[j+1]]
            local old=distance(a,b)+(d and distance(c,d) or 0)
            local new=distance(a,c)+(d and distance(b,d) or 0)
            if new+.01<old and distance(a,c)<=8 and (not d or distance(b,d)<=8) then
                local lo,hi=i,j;while lo<hi do order[lo],order[hi]=order[hi],order[lo];lo=lo+1;hi=hi-1 end
                changed=true
            end
        end end
        if not changed then break end
    end
    local same=true
    for i,r in ipairs(order) do if r.parent~=(i>1 and order[i-1] or nil) then same=false end end
    if same then return nil,'IGUI_CVP_RewireOptimal' end
    return order
end
function R.validate(reg,v,order,p)
    if not World.towingEnabled() then return 'IGUI_CVP_TowingDisabled' end
    if not v or not v:getSquare() or math.abs(v:getCurrentSpeedKmHour())>1 then return 'IGUI_CVP_StopVehicle' end
    local group=reg.byVehicle[v] or {}
    if #group~=#order or Core.memberCount(v)~=#order or #order>World.maxChain() then return 'IGUI_CVP_RewireUnloaded' end
    local seen={};local ax,ay,az=require('CVP_Geometry').anchor(v)
    for _,r in ipairs(order) do
        if seen[r] or reg.byBody[r.body]~=r or r.vehicle~=v or World.data(r.body)~=r.md
            or not World.canDetach(p,r.md) or r.owner and r.owner~=p
            or not r.body:getSquare() or r.body:getStaticMovingObjectIndex()<0 or r.body:isBeingGrappled()
            or World.gear(r.body,r.md)~=r.gear then return 'IGUI_CVP_LetGo' end
        seen[r]=true
        local x,y=xy(r)
        if math.floor(r.body:getZ())~=math.floor(az) or (x-ax)^2+(y-ay)^2>64 then return 'IGUI_CVP_RewireSpread' end
        ax,ay=x,y
    end
end
function R.apply(reg,v,order,p)
    if v and not Core.observeVehicle(v) then return false,'IGUI_CVP_ActionFailed' end
    local reason=R.validate(reg,v,order,p);if reason then return false,reason end
    local fresh={};local parent
    local ok,err=pcall(function()
        for i,r in ipairs(order) do
            local md=parent and Core.childMetadata(parent,r.body,r.gear,i,r.point) or Core.metadata(World.vehicleKey(v),r.gear,i,r.point,r.body)
            md.owner=r.md.owner;md.baseline=r.md.baseline;md.equipmentKey=r.md.equipmentKey
            Core.fitLength(r.body,v,r.gear,md,parent)
            local n=Core.link(r.body,v,r.gear,md,parent)
            n.id=r.id;n.owner=r.owner;n.storage=r.storage;n.baseline=r.baseline;n.proxySquare=r.body:getSquare()
            fresh[#fresh+1]=n;parent=n
        end
    end)
    if not ok then return false,'IGUI_CVP_ActionFailed' end
    local all={};for _,r in ipairs(reg.links) do if r.vehicle~=v then all[#all+1]=r end end
    for _,r in ipairs(fresh) do all[#all+1]=r end
    local previous=v:getModData().CVPConnections
    v:getModData().CVPConnections={}
    local built,new=pcall(Core.registry,all)
    if not built then v:getModData().CVPConnections=previous;return false,'IGUI_CVP_ActionFailed' end
    local members=v:getModData().CVPConnections
    v:getModData().CVPConnections=previous
    local bindings={}
    for _,r in ipairs(fresh) do bindings[#bindings+1]={key=r.md.equipmentKey,body=r.body,metadata=r.md} end
    local saved=require('CVP_Equipment').updateBindings(bindings)
    if not saved then return false,'IGUI_CVP_ActionFailed' end
    v:getModData().CVPConnections=members
    for _,r in ipairs(fresh) do r.body:getModData().CVPTether=r.md end
    local live=reg.links;for i=#live,1,-1 do live[i]=nil end
    for i,r in ipairs(all) do live[i]=r end
    reg.byConnection=new.byConnection;reg.byBody=new.byBody;reg.byVehicle=new.byVehicle;reg.child=new.child
    return true,fresh
end
return R
