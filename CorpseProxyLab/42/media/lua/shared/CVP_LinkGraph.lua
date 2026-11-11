-- Saved connections own endpoints; a corpse or car is only one possible target.
-- Pure rules shared by the authority, packet validation and offline tests.
local G={capacity=12,materials={['Base.Rope']=true,['Base.HeavyChain']=true,['Base.HeavyChain_Hook']=true}}
function G.tractor(e) return e.kind=='vehicle' or e.kind=='horse' end
-- A queued action follows small corpse settling, never a moving vehicle or a
-- different floor. Always compare with the original capture, not the last frame.
function G.actionMoved(kind,current,origin)
    return math.floor(current.z)~=math.floor(origin.z)
        or G.distance(current,origin)>(kind=='body' and 1 or .2)
end
local sides={'a','b'}
local function key(v) return type(v)=='string' and #v>0 and #v<=256 end
local function finite(v) return type(v)=='number' and v==v and math.abs(v)<10000000 end
local function integer(v) return finite(v) and v>=0 and v==math.floor(v) end
local function position(p) return type(p)=='table' and finite(p.x) and finite(p.y) and finite(p.z) end
local function fields(row,allowed)
    for k in pairs(row) do if not allowed[k] then return false end end;return true
end
local endpointFields={kind=true,key=true,point=true,holder=true,x=true,y=true,z=true}
local linkFields={id=true,revision=true,owner=true,material=true,equipment=true,extension=true,returning=true,allocation=true,length=true,a=true,b=true}
local function copy(v)
    if type(v)~='table' then return v end
    local out={};for k,x in pairs(v) do out[k]=type(x)=='table' and copy(x) or x end;return out
end
local function endpoint(e)
    if not position(e) or not fields(e,endpointFields) then return false end
    if e.kind=='joint' then return e.holder==nil and key(e.key) and e.point==nil end
    if e.kind=='body' then return e.holder==nil and key(e.key) and (e.point=='feet' or e.point=='neck') end
    if e.kind=='horse' then return e.holder==nil and key(e.key) and e.point=='harness' end
    if e.kind=='vehicle' then return e.holder==nil and key(e.key) and (e.point=='hitch' or e.point=='front') end
    if e.kind=='ground' then return e.holder==nil and e.key==nil and e.point==nil end
    if e.kind=='held' then return key(e.holder) and e.key==nil and e.point==nil end
    return false
end
local function node(e,id,side)
    if e.kind=='body' or e.kind=='joint' or G.tractor(e) then return e.kind..':'..e.key end
    return 'end:'..id..':'..side
end
function G.distance(a,b) return math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+((a.z-b.z)*3)^2) end
function G.empty() return {version=1,revision=0,links={}} end
function G.copy(graph) return copy(graph) end
function G.capacityFor(link) return link.allocation or G.capacity*(link.extension and 2 or 1) end
-- Rebinding may use unallocated rope, but never borrow from another segment.
function G.bindCapacity(link,index)
    local spool=link.allocation and index.spools[link.equipment]
    return spool and link.allocation+math.max(0,G.capacity-spool.used) or G.capacityFor(link)
end

-- Index once after a committed edit, not once per render or solver frame.
function G.index(graph)
    if type(graph)~='table' or graph.version~=1 or not integer(graph.revision) or type(graph.links)~='table'
        or not fields(graph,{version=true,revision=true,links=true}) then return nil,'graph schema' end
    local idx={nodes={},held={},equipment={},spools={},byBody={},byVehicle={},byHorse={},byJoint={}}
    for id,link in pairs(graph.links) do
        if not key(id) or type(link)~='table' or not fields(link,linkFields) or link.id~=id or not integer(link.revision)
            or not key(link.owner) or not G.materials[link.material] or not key(link.equipment)
            or link.extension~=nil and (not key(link.extension) or link.material~='Base.Rope')
            or link.returning~=nil and link.returning~=true
            or link.allocation~=nil and (not finite(link.allocation) or link.allocation<.1 or link.allocation>G.capacity or link.material~='Base.Rope' or link.extension~=nil)
            or not finite(link.length) or link.length<.1 or link.length>G.capacityFor(link)
            or not endpoint(link.a) or not endpoint(link.b) then return nil,'invalid link' end
        if math.floor(link.a.z)~=math.floor(link.b.z) then return nil,'different floors' end
        local spool=idx.spools[link.equipment]
        if idx.equipment[link.equipment] and (not spool or not link.allocation or not spool.shared or spool.owner~=link.owner) then
            return nil,'equipment already bound'
        end
        if not spool then spool={ids={},used=0,shared=link.allocation~=nil,owner=link.owner};idx.spools[link.equipment]=spool end
        spool.ids[#spool.ids+1]=id;spool.used=spool.used+(link.allocation or G.capacity)
        if spool.shared and spool.used>G.capacity+1e-7 then return nil,'rope exhausted' end
        idx.equipment[link.equipment]=id
        if link.extension then
            if idx.equipment[link.extension] then return nil,'equipment already bound' end
            idx.equipment[link.extension]=id
        end
        local names={node(link.a,id,'a'),node(link.b,id,'b')}
        if names[1]==names[2] then return nil,'loop' end
        for i,side in ipairs(sides) do
            local e=link[side];local n=idx.nodes[names[i]]
            if not n then n={kind=e.kind,key=e.key,edges={}};idx.nodes[names[i]]=n end
            n.edges[#n.edges+1]={id=id,side=side,other=names[3-i]}
            if e.kind=='body' then
                if #n.edges>2 then return nil,'body branch' end
                idx.byBody[e.key]=n.edges
            elseif e.kind=='joint' then
                if #n.edges>2 then return nil,'joint branch' end
                idx.byJoint[e.key]=n.edges
            elseif e.kind=='vehicle' then idx.byVehicle[e.key]=n.edges
            elseif e.kind=='horse' then idx.byHorse[e.key]=n.edges
            elseif e.kind=='held' then
                if idx.held[e.holder] then return nil,'hands occupied' end
                idx.held[e.holder]={id=id,side=side}
            end
        end
    end
    local seen={}
    for name in pairs(idx.nodes) do
        if not seen[name] then
            local queue={{name=name}};local at=1;local vehicles=0;seen[name]=true
            while at<=#queue do
                local row=queue[at];at=at+1;local n=idx.nodes[row.name]
                if G.tractor(n) then vehicles=vehicles+1;if vehicles>1 then return nil,'two vehicles' end end
                for _,edge in ipairs(n.edges) do
                    if edge.id~=row.from then
                        if seen[edge.other] then return nil,'loop' end
                        seen[edge.other]=true;queue[#queue+1]={name=edge.other,from=edge.id}
                    end
                end
            end
        end
    end
    return idx
end
-- Walk away from the selected end using an already validated index. Bodies and
-- joints have at most two edges; tractors terminate the walk, keeping roots separate.
-- Returned rows/endpoints belong to the graph and are read-only to callers.
function G.branch(graph,index,id,side)
    local branch={ids={},bodies={}}
    while id do
        local row=graph.links[id];local e=row[side=='a' and 'b' or 'a']
        branch.ids[#branch.ids+1]=id;branch.last=row;branch.endpoint=e
        if e.kind=='body' then branch.bodies[#branch.bodies+1]=e end
        if e.kind~='body' and e.kind~='joint' then break end
        local edges=(e.kind=='body' and index.byBody or index.byJoint)[e.key]
        local nextEdge=edges[1].id~=id and edges[1] or edges[2]
        if not nextEdge then break end
        id,side=nextEdge.id,nextEdge.side
    end
    return branch
end
function G.withinLimit(idx,id,maxBodies)
    if maxBodies==0 or maxBodies==math.huge then return true end
    maxBodies=maxBodies or 32
    -- The vehicle terminates traversal: its independent roots do not share a limit.
    local start
    for name,n in pairs(idx.nodes) do
        if not G.tractor(n) then for _,edge in ipairs(n.edges) do if edge.id==id then start=name;break end end end
        if start then break end
    end
    if not start then return true end
    local queue={start};local seen={[start]=true};local at,count=1,0
    while at<=#queue do
        local n=idx.nodes[queue[at]];at=at+1
        if n.kind=='body' then count=count+1;if count>maxBodies then return false end end
        for _,edge in ipairs(n.edges) do
            if not seen[edge.other] and not G.tractor(idx.nodes[edge.other]) then seen[edge.other]=true;queue[#queue+1]=edge.other end
        end
    end
    return true
end
local function accepted(graph,id,limit)
    local idx,why=G.index(graph);if not idx then return nil,why end
    if limit and not G.withinLimit(idx,id,limit) then return nil,'chain limit' end
    graph.revision=graph.revision+1;return graph
end
function G.create(graph,id,a,b,equipment,material,owner,limit,shared)
    if not G.index(graph) then return nil,'invalid graph' end
    if not key(id) or graph.links[id] then return nil,'connection exists' end
    if not endpoint(a) or not endpoint(b) then return nil,'invalid endpoint' end
    local length=math.max(.1,G.distance(a,b))
    if length>G.capacity then return nil,'too far' end
    local out=copy(graph)
    out.links[id]={id=id,revision=1,a=copy(a),b=copy(b),equipment=equipment,material=material,owner=owner,length=length}
    if shared then
        if material~='Base.Rope' then return nil,'material unavailable' end
        out.links[id].allocation=length
    end
    return accepted(out,id,limit or 32)
end
local function editable(graph,id,revision,actor,allowOthers,removing)
    if not G.index(graph) then return nil,'invalid graph' end
    local link=graph.links[id]
    if not link or link.revision~=revision then return nil,'stale connection' end
    if not key(actor) or not allowOthers and link.owner~=actor and link.owner~='legacy:unowned' then return nil,'not owner' end
    if link.returning and not removing then return nil,'equipment return pending' end
    return link
end
function G.extend(graph,id,revision,equipment,actor,allowOthers)
    local link,why=editable(graph,id,revision,actor,allowOthers);if not link then return nil,why end
    if link.allocation then return nil,'shared rope' end
    if link.material~='Base.Rope' or link.extension then return nil,'only one extra rope' end
    for _,side in ipairs(sides) do
        if link[side].kind=='held' and link[side].holder~=actor then return nil,'held by another player' end
    end
    local out=copy(graph);local row=out.links[id]
    row.extension=equipment;row.length=row.length+G.capacity;row.revision=row.revision+1
    return accepted(out,id)
end
-- Topology edits can leave a former through-node with only one section.
-- It is now a loose, pickable end, not a fixed attachment. Mutate only owned copies.
-- Every durable deletion/rollback path must go through G.edit() so this rule has
-- exactly one implementation and the graph revision advances exactly once.
local function releaseOrphanJoints(graph)
    local idx=assert(G.index(graph));local changed=false
    for _,edges in pairs(idx.byJoint) do if #edges==1 then
        local edge=edges[1];local row=graph.links[edge.id];local e=row[edge.side]
        row[edge.side]={kind='ground',x=e.x,y=e.y,z=math.floor(e.z)+.025}
        row.revision=row.revision+1;changed=true
    end end
    return changed
end
-- Apply one topology transaction to a copy of the graph: let the caller edit
-- links, release joints that lost a neighbour, advance the graph revision once,
-- then reject a result that violates the graph schema. The caller persists the
-- returned graph in the same equipment write as the item accounting change.
function G.edit(graph,mutate)
    if type(graph)~='table' or graph.version~=1 or not integer(graph.revision)
        or type(graph.links)~='table' or type(mutate)~='function' then return nil,'graph schema' end
    local out=copy(graph)
    local ok,why=pcall(mutate,out);if not ok then return nil,tostring(why) end
    releaseOrphanJoints(out)
    out.revision=graph.revision+1
    local idx,problem=G.index(out);if not idx then return nil,problem end
    return out,idx
end
-- releaseEnd only changes the selected endpoint. It never returns gear or destroys a tail.
function G.releaseEnd(graph,id,revision,side,where,actor,allowOthers)
    local link,why=editable(graph,id,revision,actor,allowOthers);if not link then return nil,why end
    if side~='a' and side~='b' or not position(where) then return nil,'invalid endpoint' end
    if link[side].kind=='held' and link[side].holder~=actor then return nil,'held by another player' end
    local out=copy(graph);local row=out.links[id];row.revision=row.revision+1
    row[side]={kind='ground',x=where.x,y=where.y,z=where.z}
    releaseOrphanJoints(out)
    return accepted(out,id)
end
-- Remove the cargo, not the continuous tether passing through its attachment.
function G.unloadBody(graph,bodyKey,where,actor,allowOthers)
    local idx,why=G.index(graph);if not idx then return nil,why end
    local edges=idx.byBody[bodyKey];if not edges then return copy(graph) end
    if not position(where) then return nil,'invalid endpoint' end
    for _,edge in ipairs(edges) do
        local link=graph.links[edge.id]
        local ok,err=editable(graph,link.id,link.revision,actor,allowOthers)
        if not ok then return nil,err end
    end
    local out=copy(graph)
    local serial=graph.revision+1
    while idx.byJoint['empty:'..serial] do serial=serial+1 end
    local jointKey='empty:'..serial
    for _,edge in ipairs(edges) do local row=out.links[edge.id]
        row[edge.side]={kind=#edges==2 and 'joint' or 'ground',
            key=#edges==2 and jointKey or nil,x=where.x,y=where.y,z=where.z}
        row.revision=row.revision+1
    end
    return accepted(out)
end
function G.take(graph,id,revision,side,actor,allowOthers)
    local link,why=editable(graph,id,revision,actor,allowOthers);if not link then return nil,why end
    if side~='a' and side~='b' or link[side].kind~='ground' then return nil,'end not free' end
    local out=copy(graph);local row=out.links[id];row.revision=row.revision+1
    row[side].kind='held';row[side].holder=actor
    return accepted(out,id)
end
function G.bind(graph,id,revision,side,target,actor,allowOthers,limit)
    local link,why=editable(graph,id,revision,actor,allowOthers);if not link then return nil,why end
    if side~='a' and side~='b' or not endpoint(target) or target.kind~='body' and not G.tractor(target) then return nil,'invalid target' end
    local e=link[side]
    if e.kind~='ground' and e.kind~='held' then return nil,'end not free' end
    if e.kind=='held' and e.holder~=actor then return nil,'held by another player' end
    local out=copy(graph);local row=out.links[id];row.revision=row.revision+1;row[side]=copy(target)
    row.length=math.max(.1,G.distance(row.a,row.b))
    if row.length>G.bindCapacity(row,G.index(graph)) then return nil,'too far' end
    if row.allocation then row.allocation=math.max(row.allocation,row.length) end
    return accepted(out,id,limit or 32)
end
-- Continue a loose tail without branching at its last body. The original
-- allocation remains owned by its spool; only the new segment owns new gear.
function G.joinTail(graph,id,revision,side,target,equipment,actor,allowOthers,limit,opposite)
    local link,why=editable(graph,id,revision,actor,allowOthers);if not link then return nil,why end
    if link.material~='Base.Rope' or not endpoint(target) or target.kind~='body' then return nil,'invalid target' end
    local e=link[side]
    if not e or e.kind~='ground' and e.kind~='held' then return nil,'end not free' end
    if e.kind=='held' and e.holder~=actor then return nil,'held by another player' end
    local other=side=='a' and 'b' or 'a'
    local from=opposite or link[other]
    local available=G.bindCapacity(link,G.index(graph));local distance=G.distance(from,target)
    if distance<=available or distance>available+G.capacity then return nil,'too far' end
    local out=copy(graph);local row=out.links[id]
    if opposite then row[other]=copy(opposite) end
    local fraction=available/distance
    local joint={kind='joint',key='tail:'..equipment,x=from.x+(target.x-from.x)*fraction,
        y=from.y+(target.y-from.y)*fraction,z=from.z+(target.z-from.z)*fraction}
    row[side]=joint;row.length=available;row.revision=row.revision+1
    if row.allocation then row.allocation=available end
    return G.create(out,'tail:'..equipment,joint,target,equipment,'Base.Rope',actor,limit,true)
end
function G.remove(graph,id,revision,actor,allowOthers)
    local link,why=editable(graph,id,revision,actor,allowOthers,true);if not link then return nil,why end
    for _,side in ipairs(sides) do if link[side].kind=='held' and link[side].holder~=actor then return nil,'held by another player' end end
    return G.edit(graph,function(out) out.links[id]=nil end)
end
-- After loading a world, old online/session claims are always ground ends.
function G.dropHolders(graph,actor)
    if not G.index(graph) then return nil,'invalid graph' end
    local out=copy(graph);local changed=releaseOrphanJoints(out)
    for _,link in pairs(out.links) do
        local edited=false
        for _,side in ipairs(sides) do local e=link[side]
            if e.kind=='held' and (actor==nil or e.holder==actor) then e.kind='ground';e.holder=nil;edited=true end
        end
        if edited then link.revision=link.revision+1;changed=true end
    end
    if changed then out.revision=out.revision+1 end;return out,changed
end
-- Runtime samples never move a player/body. Carrying pays out up to the material's
-- capacity; towing a fixed connection cannot lengthen it. An overreach drops at
-- the last reachable sample, then a free end may trail the other moving endpoint.
-- Snapshots stay immutable by default. Authority may update attached-end positions
-- in place after validating both samples; the fourth result reports that change.
local function attached(e) return e.kind=='body' or e.kind=='joint' or G.tractor(e) end
function G.advance(link,samples,holders,inPlace)
    if link.returning then return link,false end
    if inPlace and attached(link.a) and attached(link.b) then
        local a,b=samples.a,samples.b
        if not position(a) or not position(b) then return link,false,'unloaded endpoint' end
        if math.floor(a.z)~=math.floor(b.z) then return link,false,'different floors' end
        local changed=link.a.x~=a.x or link.a.y~=a.y or link.a.z~=a.z
            or link.b.x~=b.x or link.b.y~=b.y or link.b.z~=b.z
        if changed then
            link.a.x,link.a.y,link.a.z=a.x,a.y,a.z
            link.b.x,link.b.y,link.b.z=b.x,b.y,b.z
        end
        return link,false,nil,changed
    end
    local row=copy(link);local dropped=false
    for _,side in ipairs(sides) do
        local e=row[side];local p=samples[side]
        if attached(e) then
            if not position(p) then return link,false,'unloaded endpoint' end
            e.x,e.y,e.z=p.x,p.y,p.z
        end
    end
    if math.floor(row.a.z)~=math.floor(row.b.z) then return link,false,'different floors' end
    for _,side in ipairs(sides) do
        local e=row[side];local other=row[side=='a' and 'b' or 'a'];local p=samples[side]
        if e.kind=='ground' and p and position(p) then e.x,e.y,e.z=p.x,p.y,p.z end
        if e.kind=='held' then
            if not holders or not holders[e.holder] or not position(p) or math.floor(p.z)~=math.floor(other.z) or other.kind~='ground' and G.distance(p,other)>G.capacityFor(row) then
                e.kind='ground';e.holder=nil;dropped=true
            else e.x,e.y,e.z=p.x,p.y,p.z;row.length=math.min(G.capacityFor(row),math.max(row.length,G.distance(e,other))) end
        end
    end
    for _,side in ipairs(sides) do
        local e=row[side];local other=row[side=='a' and 'b' or 'a']
        if e.kind=='ground' and other.kind~='ground' then
            local d=G.distance(e,other)
            if d>row.length then
                local horizontal=math.sqrt((e.x-other.x)^2+(e.y-other.y)^2)
                local reach=math.sqrt(math.max(0,row.length^2-((e.z-other.z)*3)^2))
                local f=horizontal>0 and math.min(1,reach/horizontal) or 0
                e.x=other.x+(e.x-other.x)*f;e.y=other.y+(e.y-other.y)*f
            end
        end
    end
    if dropped then row.revision=row.revision+1 end
    local changed=dropped or row.length~=link.length
    for _,side in ipairs(sides) do local a,b=row[side],link[side]
        changed=changed or a.x~=b.x or a.y~=b.y or a.z~=b.z
    end
    return changed and row or link,dropped
end
return G
