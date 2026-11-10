-- Keep the bounded route planner; commit the new endpoint layout in one ledger write.
local G=require 'CVP_LinkGraph'
local World=require 'CVP_World'
local Planner=require 'CVP_Rewire'
local R={}
local function collect(graph,index,host,vehicle)
    local rows,seen={},{};local pending={}
    for key,edges in pairs(index.byVehicle) do if host.vehicle({key=key})==vehicle then
        for _,edge in ipairs(edges) do pending[#pending+1]={edge=edge} end
    end end
    local at=1
    while at<=#pending do
        local entry=pending[at];at=at+1;local edge=entry.edge
        if seen[edge.id] then return nil,'IGUI_CVP_LinkLoop' end;seen[edge.id]=true
        local link=graph.links[edge.id];local other=edge.side=='a' and 'b' or 'a';local endB=link[other]
        if link.returning then return nil,'equipment return pending' end
        -- A spare free end would occupy the second body attachment point after
        -- reordering. Leave it intact and require the player to remove it first.
        if endB.kind~='body' then return nil,'IGUI_CVP_RewireFreeEnd' end
        local body=host.body(endB);local a,b=host.sample(link[edge.side]),host.sample(endB)
        if not body or not a or not b or body:isBeingGrappled() or World.foreignTowed(body) then return nil,'IGUI_CVP_RewireUnloaded' end
        local row={id=link.id,revision=link.revision,owner=link.owner,equipment=link.equipment,
            sourceSide=edge.side,a=a,b=b,parent=entry.parent,connection={id=link.id},body=body}
        rows[#rows+1]=row
        for _,nextEdge in ipairs(index.byBody[endB.key] or {}) do if nextEdge.id~=edge.id then
            pending[#pending+1]={edge=nextEdge,parent=row}
        end end
    end
    return rows
end
function R.plan(graph,index,host,vehicle,actor)
    if not host.enabled() then return nil,'towing disabled' end
    if math.abs(vehicle:getCurrentSpeedKmHour())>1 then return nil,'stop vehicle' end
    local rows,err=collect(graph,index,host,vehicle);if not rows then return nil,err end
    for _,row in ipairs(rows) do
        if not actor.allowOthers and row.owner~=actor.key and row.owner~='legacy:unowned' then return nil,'not owner' end
    end
    local anchor
    for _,row in ipairs(rows) do if row.a.kind=='vehicle' then
        local point=row.a.point or 'hitch'
        if anchor and anchor~=point then return nil,'IGUI_CVP_RewireSeparateAnchors' end
        anchor=point
    end end
    local order,why=Planner.plan(vehicle,rows,anchor);if not order then return nil,why end
    local result={rows={},steps={}};local source=host.sample({kind='vehicle',key=rows[1].a.kind=='vehicle' and rows[1].a.key or nil,point=anchor})
    if not source then return nil,'vehicle unavailable' end
    result.root=G.copy(source)
    for _,row in ipairs(order) do
        local a,b=G.copy(source),G.copy(row.b);local length=math.max(.1,G.distance(a,b))
        if math.floor(a.z)~=math.floor(b.z) or length>G.capacityFor(graph.links[row.id]) then return nil,'IGUI_CVP_RewireSpread' end
        if host.path then local blocked=host.path(a,b);if blocked then return nil,blocked end end
        result.rows[#result.rows+1]={id=row.id,revision=row.revision,equipment=row.equipment,sourceSide=row.sourceSide,a=a,b=b,length=length}
        result.steps[#result.steps+1]=a;result.steps[#result.steps+1]=b;source=b
    end
    return result
end
function R.validate(plan,graph,index,host,actor)
    if not host.enabled() then return 'towing disabled' end
    local vehicle=host.vehicle(plan.root)
    if not vehicle or math.abs(vehicle:getCurrentSpeedKmHour())>1 then return 'stop vehicle' end
    local rows,why=collect(graph,index,host,vehicle);if not rows then return why end
    if #rows~=#plan.rows then return 'stale connection' end
    local expected={};for _,row in ipairs(plan.rows) do expected[row.id]=row end
    for _,row in ipairs(rows) do
        local captured=expected[row.id]
        if not captured or captured.revision~=row.revision or captured.equipment~=row.equipment then return 'stale connection' end
        if not actor.allowOthers and row.owner~=actor.key and row.owner~='legacy:unowned' then return 'not owner' end
    end
    for _,e in ipairs(plan.steps) do
        local point=host.sample(e)
        if not point or G.actionMoved(e.kind,point,e) then return 'first endpoint moved' end
    end
    if #rows>host.maxBodies() then return 'chain limit' end
end
function R.apply(plan,graph,host)
    local out=G.copy(graph)
    for _,row in ipairs(plan.rows) do
        local link=out.links[row.id];local other=row.sourceSide=='a' and 'b' or 'a'
        local a,b=host.sample(row.a),host.sample(row.b)
        if not a or not b then return nil,'endpoint unloaded' end
        link[row.sourceSide]=a;link[other]=b
        link.length=math.max(.1,G.distance(a,b));link.revision=link.revision+1
    end
    local index,why=G.index(out);if not index then return nil,why end
    return out
end
return R
