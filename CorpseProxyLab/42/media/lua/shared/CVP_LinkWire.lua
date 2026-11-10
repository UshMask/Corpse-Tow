-- Graph transport: plain tables only. Old tether packets remain protocol 3.
local P=require 'CVP_Protocol'
local G=require 'CVP_LinkGraph'
local W={version=13,module='CVP',interval=100,radius=90,pageSize=16,maxPages=65536}
W.finite=P.finite;W.integer=P.integer;W.id=P.id;W.partBytes=P.partBytes;W.maxParts=P.maxParts
function W.key(s) return type(s)=='string' and #s>0 and #s<=256 end
function W.session(s) return type(s)=='string' and #s>0 and #s<=80 end
function W.ref(r)
    if type(r)~='table' then return false end
    if r.kind=='horse' then return W.key(r.key) and (r.point==nil or r.point=='harness') end
    if r.kind=='ground' then return true end -- Authority chooses the player's actual position.
    if r.kind=='body' then return (W.key(r.key) or P.id(r.native)) and (r.point==nil or r.point=='feet' or r.point=='neck') end
    return r.kind=='vehicle' and (W.key(r.key) or P.integer(r.native)) and (r.point==nil or r.point=='hitch' or r.point=='front')
end
function W.request(name,a)
    if type(a)~='table' then return false end
    if name=='ropePrepare' then return W.ref(a.target) and (P.integer(a.gear) or W.key(a.link) and P.integer(a.revision)) end
    if name=='prepare' then return W.ref(a.target) and P.integer(a.gear) end
    if name=='create' then return W.key(a.token) and W.ref(a.target) end
    if name=='rewirePrepare' then return W.ref(a.target) and a.target.kind=='vehicle' end
    if name=='rewireVisit' then return W.key(a.token) end
    if name~='command' then return false end
    if not W.key(a.id) or not P.integer(a.revision) or a.revision<1 or (a.side~='a' and a.side~='b') then return false end
    if a.op=='bind' then return W.ref(a.target) and a.target.kind~='ground' and (a.gear==nil or P.integer(a.gear)) end
    if a.op=='extend' then return P.integer(a.gear) end
    return a.op=='take' or a.op=='drop' or a.op=='release' or a.op=='remove'
end
local function position(row)
    return type(row)=='table' and P.finite(row.x) and P.finite(row.y) and P.finite(row.z)
end
function W.body(row)
    if type(row)=='table' then
        if row.appearanceRevision~=nil and (not P.integer(row.appearanceRevision) or row.appearanceRevision<1) then return false end
        if row.appearanceOmitted~=nil and (row.appearanceOmitted~=true or not row.appearanceRevision
            or row.cosmetic~=nil or row.clothing~=nil) then return false end
    end
    if type(row)=='table' and row.clothing~=nil then
        if type(row.clothing)~='table' then return false end
        local count,ids=0,{}
        for k,c in pairs(row.clothing) do
            count=count+1
            if not P.integer(k) or k<1 or k>64 or type(c)~='table' or not P.integer(c.id) or ids[c.id]
                or not P.integer(c.condition) or c.condition<0 or c.condition>10000 or type(c.holes)~='table' then return false end
            ids[c.id]=true
            local holes,seen=0,{}
            for n,part in pairs(c.holes) do
                holes=holes+1
                if not P.integer(n) or n<1 or n>18 or not P.integer(part) or part<0 or part>=18 or seen[part] then return false end
                seen[part]=true
            end
            if holes~=#c.holes then return false end
        end
        if count~=#row.clothing then return false end
    end
    if type(row)=='table' and row.cosmetic~=nil then
        local c=row.cosmetic
        if type(c)~='table' or not P.finite(c.blood) or not P.finite(c.dirt)
            or c.blood<0 or c.blood>1 or c.dirt<0 or c.dirt>1 then return false end
    end
    if not position(row) or not W.key(row.key) or not P.id(row.id) or not W.key(row.token)
        or not P.finite(row.angle) or type(row.connections)~='table' then return false end
    local count=0;for k,id in pairs(row.connections) do
        count=count+1;if not P.integer(k) or k<1 or k>2 or not W.key(id) then return false end
    end
    if count<1 or count~=#row.connections then return false end
    if row.retired~=nil and type(row.retired)~='boolean' then return false end
    if row.corrected~=nil and type(row.corrected)~='boolean' then return false end
    if row.source and (not W.ref(row.source) or not position(row.source)) then return false end
    if row.sourceSampledAt~=nil and (not P.integer(row.sourceSampledAt) or row.sourceSampledAt<0) then return false end
    if row.parent and not W.key(row.parent) then return false end
    if row.vehicle~=nil and not P.integer(row.vehicle) then return false end
    return type(row.taut)=='boolean' and type(row.blocked)=='boolean'
end
local function near(x,y,floor,e)
    return floor==math.floor(e.z) and (x-e.x)^2+(y-e.y)^2<=W.radius^2
end
function W.near(p,e)
    return near(p:getX(),p:getY(),math.floor(p:getZ()),e)
end
-- Keep complete body-connected trains, stopping at their vehicle so unrelated
-- roots do not all enter a player's interest area. No global 320-link limit.
function W.visible(graph,index,p)
    local ids,queue,spools={},{},{}
    local x,y,z=p:getX(),p:getY(),math.floor(p:getZ())
    for id,row in pairs(graph.links) do
        if near(x,y,z,row.a) or near(x,y,z,row.b) then ids[id]=true;queue[#queue+1]=id end
    end
    local at=1
    while at<=#queue do
        local row=graph.links[queue[at]];at=at+1
        local spool=index.spools[row.equipment]
        if spool and spool.shared and not spools[row.equipment] then
            spools[row.equipment]=true
            for _,id in ipairs(spool.ids) do
            if not ids[id] then ids[id]=true;queue[#queue+1]=id end
        end end
        for _,side in ipairs({'a','b'}) do local e=row[side]
            if e.kind=='body' or e.kind=='joint' then for _,edge in ipairs((e.kind=='body' and index.byBody or index.byJoint)[e.key]) do
                if not ids[edge.id] then ids[edge.id]=true;queue[#queue+1]=edge.id end
            end end
        end
    end
    return ids
end
-- Immutable key order can be shared across recipients and snapshots. Positions
-- and availability are always read from the current snapshot, never this cache.
local function orderedKeys(rows,previous)
    local count=0;local unchanged=previous~=nil
    for key in pairs(rows) do
        count=count+1
        if unchanged and not previous.members[key] then unchanged=false end
    end
    if unchanged and count==#previous.ids then return previous end
    local order={ids={},members={}}
    for key in pairs(rows) do order.ids[#order.ids+1]=key;order.members[key]=true end
    table.sort(order.ids);return order
end
function W.pageOrder(graph,bodies,previous)
    local links=orderedKeys(graph.links,previous and previous.links)
    local poses=orderedKeys(bodies,previous and previous.bodies)
    if previous and links==previous.links and poses==previous.bodies then return previous end
    return {links=links,bodies=poses}
end
function W.pages(graph,bodies,loads,index,p,obstacles,order)
    order=order or W.pageOrder(graph,bodies)
    local ids=W.visible(graph,index,p);local links,seen,poses,forces={},{},{},{}
    for _,id in ipairs(order.links.ids) do if ids[id] then local row=graph.links[id];links[#links+1]=row
        for _,side in ipairs({'a','b'}) do local e=row[side]
            if e.kind=='body' then seen[e.key]=true end
            if e.kind=='vehicle' and loads[e.key] then forces[e.key]=loads[e.key] end
        end
    end end
    local x,y,z=p:getX(),p:getY(),math.floor(p:getZ())
    for _,key in ipairs(order.bodies.ids) do local row=bodies[key]
        if seen[key] or row.retired and near(x,y,z,row) then poses[#poses+1]=row end
    end
    local pages={};local count=math.max(1,math.ceil(math.max(#links,#poses)/W.pageSize))
    for n=1,count do
        local page={revision=graph.revision,page=n,count=count,links={},bodies={},loads={},obstacles={}}
        for i=(n-1)*W.pageSize+1,n*W.pageSize do
            if links[i] then page.links[#page.links+1]=links[i]
                local id=links[i].id;if obstacles and obstacles[id] then page.obstacles[id]=obstacles[id] end
                for _,side in ipairs({'a','b'}) do local e=links[i][side]
                    if e.kind=='vehicle' and forces[e.key] then local load=forces[e.key]
                        page.loads[e.key]=load;forces[e.key]=nil end
                end
            end
            if poses[i] then page.bodies[#page.bodies+1]=poses[i] end
        end
        pages[n]=page
    end
    return pages
end
function W.loadRow(load)
    return type(load)=='table' and P.integer(load.vehicle)
        and P.finite(load.resistanceForceN) and load.resistanceForceN>=0
        and P.finite(load.intervalSeconds) and load.intervalSeconds>=0
        and P.integer(load.ownerGeneration) and load.ownerGeneration>=1
        and P.integer(load.owner)
end
function W.loadPage(a)
    if type(a)~='table' or not W.session(a.epoch) or not W.session(a.session)
        or not P.integer(a.sequence) or a.sequence<0 or not P.integer(a.revision) or a.revision<0
        or not P.integer(a.sampledAt) or a.sampledAt<0 or not P.integer(a.count) or a.count<1 or a.count>W.maxPages
        or not P.integer(a.page) or a.page<1 or a.page>a.count or type(a.loads)~='table' then return false end
    local n=0
    for key,row in pairs(a.loads) do
        n=n+1;if n>W.pageSize*2 or not W.key(key) or not W.loadRow(row) then return false end
    end
    return true
end
function W.page(a)
    if type(a)~='table' or a.frameSchema~=1 or not P.integer(a.sampledAt) or a.sampledAt<0
        or not P.finite(a.intervalSeconds) or a.intervalSeconds<0 or a.intervalSeconds>.5 then return false end
    if type(a)~='table' or not W.session(a.epoch) or not W.session(a.session)
        or not P.integer(a.sequence) or a.sequence<0 or not P.integer(a.revision) or a.revision<0
        or not P.integer(a.count) or a.count<1 or a.count>W.maxPages
        or not P.integer(a.page) or a.page<1 or a.page>a.count
        or type(a.ready)~='boolean' or type(a.links)~='table' or type(a.bodies)~='table' or type(a.loads)~='table' then return false end
    local n=0;for k in pairs(a.links) do n=n+1;if not P.integer(k) or k<1 or k>W.pageSize then return false end end
    if n~=#a.links then return false end
    n=0;for k,row in pairs(a.bodies) do n=n+1;if not P.integer(k) or k<1 or k>W.pageSize or not W.body(row) then return false end end
    if n~=#a.bodies then return false end
    n=0;for key,load in pairs(a.loads) do
        n=n+1;if n>W.pageSize*2 or not W.key(key) or not W.loadRow(load) then return false end
    end
    if a.obstacles~=nil and type(a.obstacles)~='table' then return false end
    n=0;for key,why in pairs(a.obstacles or {}) do
        n=n+1;if n>W.pageSize or not W.key(key) or (why~='IGUI_CVP_LinkBlocked' and why~='IGUI_CVP_LinkPathUnloaded') then return false end
    end
    return true
end
function W.motionPage(a)
    -- page validates a dense links array; Kahlua does not expose global next.
    if not W.page(a) or #a.links~=0 or type(a.geometry)~='table' then return false end
    local n=0
    for i,row in pairs(a.geometry) do
        n=n+1
        if not P.integer(i) or i<1 or i>W.pageSize or type(row)~='table' or not W.key(row.id)
            or not P.integer(row.revision) or not P.finite(row.length) or row.length<=0
            or not position(row.a) or not position(row.b) then return false end
    end
    return n==#a.geometry
end
local function sameEndpoint(a,b)
    for k,v in pairs(a) do if k~='x' and k~='y' and k~='z' and b[k]~=v then return false end end
    for k,v in pairs(b) do if k~='x' and k~='y' and k~='z' and a[k]~=v then return false end end
    return true
end
function W.assemble(parts,base)
    local graph=G.empty();graph.revision=parts.revision;local bodies,loads,obstacles={},{},{}
    if base then
        if base.revision~=parts.revision then return nil,'motion revision' end
        for id,row in pairs(base.links) do graph.links[id]=row end
    end
    local geometrySeen=base and {}
    for n=1,parts.count do
        local page=parts.pages[n];if not page then return end
        if base then for _,row in ipairs(page.geometry or {}) do
            local old=base.links[row.id]
            if not old or geometrySeen[row.id] or old.revision~=row.revision
                or not sameEndpoint(old.a,row.a) or not sameEndpoint(old.b,row.b) then return nil,'motion topology' end
            geometrySeen[row.id]=true
            local updated={};for k,v in pairs(old) do updated[k]=v end
            updated.length=row.length;updated.a=row.a;updated.b=row.b;graph.links[row.id]=updated
        end end
        for _,row in ipairs(page.links) do
            if type(row)~='table' or not W.key(row.id) or graph.links[row.id] then return nil,'duplicate link' end
            graph.links[row.id]=G.copy(row)
        end
        for _,row in ipairs(page.bodies) do if bodies[row.key] then return nil,'duplicate body' end;bodies[row.key]=G.copy(row) end
        for key,row in pairs(page.loads) do if loads[key] then return nil,'duplicate load' end;loads[key]=G.copy(row) end
        for key,why in pairs(page.obstacles or {}) do
            if obstacles[key] then return nil,'duplicate obstacle' end;obstacles[key]=why
        end
    end
    if base then for id in pairs(base.links) do if not geometrySeen[id] then return nil,'incomplete motion' end end end
    local index,err=G.index(graph);if not index then return nil,err end
    for key,row in pairs(bodies) do
        if not row.retired and not index.byBody[key] or row.retired and index.byBody[key] then return nil,'unbound body' end
        if not row.retired then
            local edges=index.byBody[key];local seen={}
            for _,id in ipairs(row.connections) do seen[id]=true end
            if #row.connections~=#edges then return nil,'body connections' end
            for _,edge in ipairs(edges) do if not seen[edge.id] then return nil,'body connections' end end
        end
    end
    for key in pairs(loads) do if not index.byVehicle[key] then return nil,'unbound vehicle load' end end
    for id in pairs(obstacles) do if not graph.links[id] then return nil,'unbound obstacle' end end
    return {graph=graph,index=index,bodies=bodies,loads=loads,obstacles=obstacles,sampledAt=parts.sampledAt,frameSchema=parts.frameSchema,intervalSeconds=parts.intervalSeconds}
end
return W
