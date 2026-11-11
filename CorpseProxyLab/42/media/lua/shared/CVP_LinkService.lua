-- Commands and runtime endpoint positions for SP/server. The host resolves only
-- real loaded objects and checks paths; clients never supply trusted positions.
local G=require 'CVP_LinkGraph'
local Service={};Service.__index=Service
function Service.new(store,host)
    return setmetatable({store=store,host=host,pending={},dirty=false,lastSave=0},Service)
end
function Service:refresh()
    local revision,err=self.store.linkRevision();if revision==nil then return nil,err end
    if not self.graph or self.persistedRevision~=revision then
        if self.dirty then return nil,'graph changed during pending movement save' end
        local graph,why=self.store.links();if not graph then return nil,why end
        local idx,problem=G.index(graph);if not idx then return nil,problem end
        self.graph=graph;self.index=idx;self.persistedRevision=revision
    end
    return self.graph
end
function Service:commit(graph)
    local ok,err,idx=self.store.editLinks(graph,self.persistedRevision)
    if not ok then self.nextWrite=self.host.now()+5000;return false,err end
    self.graph=graph;self.persistedRevision=graph.revision;self.index=idx or assert(G.index(graph));self.dirty=false
    self.lastSave=self.host.now();self.nextWrite=0;return true
end
function Service:flush()
    if not self.dirty then return true end
    local graph=G.copy(self.graph);graph.revision=self.persistedRevision+1
    local ok,err=self.store.editLinks(graph,self.persistedRevision)
    if not ok then self.nextWrite=self.host.now()+5000;return false,err end
    -- A checkpoint changes no membership. Keep the live graph and simulation plans;
    -- the ledger owns its separate validated copy, installed only after durable write.
    self.graph.revision=graph.revision;self.persistedRevision=graph.revision;self.dirty=false
    self.lastSave=self.host.now();self.nextWrite=0;return true
end
function Service:load()
    local graph,err=self:refresh();if not graph then return false,err end
    local dropped,changed=G.dropHolders(graph)
    if changed then return self:commit(dropped) end
    return true
end
local function usable(actor)
    return actor and actor.alive and actor.onFoot and type(actor.key)=='string'
end
function Service:near(p,actor,e)
    return math.floor(actor.z)==math.floor(e.z) and (actor.x-e.x)^2+(actor.y-e.y)^2<=2.25 and self.host.canReach(p,e)
end
function Service:joinable(actor,e)
    -- A car terminates traversal: its other independent trains do not acquire
    -- shared ownership. Joining a body can affect its whole existing train.
    if e.kind~='body' then return end
    local queue={'body:'..e.key};local seen={};local at=1
    while at<=#queue do
        local name=queue[at];at=at+1
        if not seen[name] then
            seen[name]=true;local node=self.index.nodes[name]
            if node and node.kind=='horse' then
                if not require('CVP_Horse').enabled() then return 'IGUI_CVP_HorseDisabled' end
                if not require('CVP_Horse').stopped(self.host.horse(node)) then return 'IGUI_CVP_StopHorse' end
            elseif node and node.kind=='vehicle' then
                local v=self.host.vehicle and self.host.vehicle({kind='vehicle',key=node.key})
                if v and math.abs(v:getCurrentSpeedKmHour())>1 then return 'stop vehicle' end
            elseif node then for _,edge in ipairs(node.edges) do
                local owner=self.graph.links[edge.id].owner
                if not actor.allowOthers and owner~=actor.key and owner~='legacy:unowned' then return 'not owner' end
                queue[#queue+1]=edge.other
            end end
        end
    end
end
function Service:prepare(p,target,gearID,shared,reuse,revision)
    if not self.host.enabled() then return nil,'towing disabled' end
    local actor=self.host.actor(p);if not usable(actor) then return nil,'leave vehicle or unavailable player' end
    local graph,err=self:refresh();if not graph then return nil,err end
    local e,why=self.host.resolve(target,p);if not e then return nil,why end
    if e.kind~='body' and not G.tractor(e) or not self:near(p,actor,e) then return nil,'endpoint not reachable' end
    local denied=self:joinable(actor,e);if denied then return nil,denied end
    local item,equipment,owner
    if reuse then
        local link=graph.links[reuse]
        if not shared or not link or link.revision~=revision or not link.allocation then return nil,'stale connection' end
        if not actor.allowOthers and link.owner~=actor.key then return nil,'not owner' end
        if e.kind~='body' or #(self.index.byBody[e.key] or {})~=1 then return nil,'body branch' end
        local same=false;for _,side in ipairs({'a','b'}) do local endPoint=link[side]
            if endPoint.kind==e.kind and endPoint.key==e.key and endPoint.point==e.point then same=true end
        end
        if not same then return nil,'invalid endpoint' end
        local ready,why=self.store.linkReady(link);if not ready then return nil,why end
        equipment=link.equipment;owner=link.owner
    else
        item=self.host.item(p,gearID)
        if not item or not G.materials[item:getFullType()] or shared and item:getFullType()~='Base.Rope' then return nil,'material unavailable' end
    end
    local token=self.host.uuid()
    local now=self.host.now();local batch=self.pending[actor.key]
    if not batch or now-batch.at>120000 then batch={items={}} end
    for id,row in pairs(batch.items) do if not row.equipment and not self.host.item(p,row.gearID) then batch.items[id]=nil end end
    local slot=equipment and ('rope:'..equipment) or gearID
    local reference=G.copy(e)
    if e.kind=='body' then reference.native=target.native end
    batch.items[slot]={token=token,first=G.copy(e),reference=reference,gearID=gearID,slot=slot,
        shared=shared==true,equipment=equipment,reuse=reuse,revision=revision,owner=owner}
    batch.at=now;self.pending[actor.key]=batch
    return token,nil,G.copy(reference)
end
function Service:create(p,token,target)
    if not self.host.enabled() then return false,'towing disabled' end
    local actor=self.host.actor(p);if not usable(actor) then return false,'leave vehicle or unavailable player' end
    local batch=self.pending[actor.key];local prepared
    if batch and self.host.now()-batch.at<=120000 then
        for _,row in pairs(batch.items) do if row.token==token then prepared=row;break end end
    end
    if not prepared then return false,'attachment expired' end
    local graph,err=self:refresh();if not graph then return false,err end
    local a,why=self.host.resolve(prepared.reference,p);if not a then return false,why end
    if a.kind~=prepared.first.kind or a.key~=prepared.first.key or a.point~=prepared.first.point or G.actionMoved(a.kind,a,prepared.first) then return false,'first endpoint moved' end
    local b,reason=self.host.resolve(target,p);if not b then return false,reason end
    if not self:near(p,actor,b) then return false,'endpoint not reachable' end
    local denied=self:joinable(actor,a) or self:joinable(actor,b);if denied then return false,denied end
    local item=not prepared.equipment and self.host.item(p,prepared.gearID)
    if prepared.equipment then
        local link=graph.links[prepared.reuse]
        if not link or link.revision~=prepared.revision or link.equipment~=prepared.equipment then return false,'stale connection' end
        if not actor.allowOthers and link.owner~=actor.key then return false,'not owner' end
        local ready,why=self.store.linkReady(link);if not ready then return false,why end
    elseif not item or not G.materials[item:getFullType()] then return false,'material unavailable' end
    local id=self.host.uuid()
    local preview,problem=G.create(graph,id,a,b,prepared.equipment or 'preview-'..id,prepared.equipment and 'Base.Rope' or item:getFullType(),prepared.owner or actor.key,self.host.maxBodies(),prepared.shared)
    if not preview then return false,problem end
    if self.host.path then local why=self.host.path(a,b);if why then return false,why end end
    if self.host.ensure then for _,e in ipairs({a,b}) do local ok,why=self.host.ensure(e);if not ok then return false,why end end end
    -- A native checkpoint may span frames. Revalidate both endpoints before consuming the item.
    local currentA=self.host.resolve(prepared.reference,p);local currentB=self.host.resolve(target,p)
    if not currentA or not currentB or G.distance(a,currentA)>.2 or G.distance(b,currentB)>.2
        or not self:near(p,self.host.actor(p),currentB) then return false,'endpoint moved during save' end
    local saved,failure=self:flush();if not saved then return false,failure end
    batch.items[prepared.slot]=nil;batch.at=self.host.now()
    local remaining=false;for _ in pairs(batch.items) do remaining=true;break end
    if not remaining then self.pending[actor.key]=nil end
    if prepared.equipment then
        -- flush may advance the graph revision; allocate against the saved graph.
        local out,why=G.create(self.graph,id,a,b,prepared.equipment,'Base.Rope',prepared.owner,self.host.maxBodies(),true)
        if not out then return false,why end
        local ok,err=self:commit(out);if not ok then return false,err end
        return true,id
    end
    local key,holdError=self.store.hold(item,self.host.transfer,{link={id=id,a=a,b=b,owner=actor.key,maxBodies=self.host.maxBodies(),shared=prepared.shared}})
    self.graph=nil;self.dirty=false;self:refresh()
    if not key or holdError then return false,holdError or 'equipment transfer rejected' end
    return true,id
end
function Service:command(p,args)
    if type(args)~='table' then return false,'invalid command' end
    local actor=self.host.actor(p);if not usable(actor) then return false,'leave vehicle or unavailable player' end
    local graph,err=self:refresh();if not graph then return false,err end
    local link=graph.links[args.id]
    if not link or link.revision~=args.revision then return false,'stale connection' end
    local side=args.side
    if side~='a' and side~='b' then return false,'invalid endpoint' end
    local selected=link[side];local position,reason=self.host.actionSample(G.copy(selected))
    if not position and selected.kind=='horse' and args.op=='release' then
        position=self.host.actionSample(G.copy(link[side=='a' and 'b' or 'a']))
    end
    if not position then return false,reason or 'endpoint unloaded' end
    if selected.kind=='held' and selected.holder~=actor.key then return false,'held by another player' end
    if not self:near(p,actor,position) and not (args.op=='bind' and args.gear and selected.kind=='ground') then return false,'endpoint not reachable' end
    if args.op~='remove' then local ready,why=self.store.linkReady(link);if not ready then return false,why end end
    local out,why
    if args.op=='extend' then
        if not self.host.enabled() then return false,'towing disabled' end
        local denied=self:joinable(actor,link.a) or self:joinable(actor,link.b);if denied then return false,denied end
        for _,e in ipairs({link.a,link.b}) do
            if e.kind=='horse' and not require('CVP_Horse').stopped(self.host.horse(e)) then return false,'IGUI_CVP_StopHorse' end
            if e.kind=='vehicle' then
            local v=self.host.vehicle(e);if not v or math.abs(v:getCurrentSpeedKmHour())>1 then return false,'stop vehicle' end
        end end
        local item=self.host.item(p,args.gear)
        if not item or item:getFullType()~='Base.Rope' then return false,'material unavailable' end
        local preview,problem=G.extend(graph,args.id,args.revision,'preview-extension',actor.key,actor.allowOthers)
        if not preview then return false,problem end
        local saved,failure=self:flush();if not saved then return false,failure end
        local key,err=self.store.hold(item,self.host.transfer,{extend={id=args.id,revision=args.revision,owner=actor.key,allowOthers=actor.allowOthers}})
        self.graph=nil;self.dirty=false;self:refresh()
        return key~=nil and err==nil,err
    elseif args.op=='take' then
        if not self.host.enabled() then return false,'towing disabled' end
        out,why=G.take(graph,args.id,args.revision,side,actor.key,actor.allowOthers)
    elseif args.op=='drop' then
        if selected.kind~='held' then return false,'end not held' end
        if self.host.ground then position=self.host.ground(position) end
        out,why=G.releaseEnd(graph,args.id,args.revision,side,position,actor.key,actor.allowOthers)
    elseif args.op=='release' then
        if self.host.ground then position=self.host.ground(position) end
        if selected.kind=='body' then
            out,why=G.unloadBody(graph,selected.key,position,actor.key,actor.allowOthers)
        else out,why=G.releaseEnd(graph,args.id,args.revision,side,position,actor.key,actor.allowOthers) end
    elseif args.op=='bind' then
        if not self.host.enabled() then return false,'towing disabled' end
        local other=side=='a' and 'b' or 'a'
        local opposite,unloaded=self.host.actionSample(G.copy(link[other]))
        if not opposite then return false,unloaded or 'endpoint unloaded' end
        local target,problem=self.host.resolve(args.target,p);if not target then return false,problem end
        if not self:near(p,actor,target) then return false,'target not reachable' end
        local denied=self:joinable(actor,target) or self:joinable(actor,link[other]);if denied then return false,denied end
        graph=G.copy(graph)
        local savedEnd=graph.links[args.id][other];savedEnd.x=opposite.x;savedEnd.y=opposite.y;savedEnd.z=opposite.z
        out,why=G.bind(graph,args.id,args.revision,side,target,actor.key,actor.allowOthers,self.host.maxBodies())
        local item
        if not out and why=='too far' and args.gear then
            item=self.host.item(p,args.gear)
            if not item or item:getFullType()~='Base.Rope' then return false,'material unavailable' end
            out,why=G.joinTail(graph,args.id,args.revision,side,target,'preview-tail',actor.key,actor.allowOthers,self.host.maxBodies(),savedEnd)
        end
        if out and self.host.path then local blocked=self.host.path(opposite,target);if blocked then return false,blocked end end
        if out and item then
            if self.host.ensure then local ok,problem=self.host.ensure(target);if not ok then return false,problem end end
            local current=self.host.resolve(args.target,p)
            local source=self.host.actionSample(G.copy(link[other]))
            if not current or not source or G.distance(current,target)>.2 or G.distance(source,opposite)>.2
                or not self:near(p,self.host.actor(p),current) then return false,'endpoint moved during save' end
            local saved,failure=self:flush();if not saved then return false,failure end
            local key,err=self.store.hold(item,self.host.transfer,{tail={id=args.id,revision=args.revision,side=side,
                target=target,opposite=savedEnd,owner=actor.key,allowOthers=actor.allowOthers,maxBodies=self.host.maxBodies()}})
            self.graph=nil;self.dirty=false;self:refresh()
            return key~=nil and not err,err
        end
        if out and self.host.ensure then local ok,problem=self.host.ensure(target);if not ok then return false,problem end end
    elseif args.op=='remove' then
        -- Validate the complete deletion rule (owner, held-by-another, revision)
        -- on a copy, then let the equipment ledger perform the only durable
        -- deletion. E.releaseLink normalizes former through-joints in the same
        -- write as the item return, so the graph and item accounting cannot
        -- disagree after a crash or reload.
        out,why=G.remove(graph,args.id,args.revision,actor.key,actor.allowOthers)
        if not out then return false,why end
        local saved,failure=self:flush();if not saved then return false,failure end
        local ok,problem=self.store.releaseLink(args.id,args.revision,self.host.inventory(p),self.host.transfer)
        self.graph=nil;self.dirty=false;self:refresh();return ok,problem
    else return false,'unknown command' end
    if not out then return false,why end
    return self:commit(out)
end
function Service:disconnect(actorKey)
    self.pending[actorKey]=nil
    if self.rewires then self.rewires[actorKey]=nil end
    local graph,err=self:refresh();if not graph then return false,err end
    local dropped,changed=G.dropHolders(graph,actorKey)
    if changed then return self:commit(dropped) end
    return true
end
function Service:prepareRewire(p,ref)
    local actor=self.host.actor(p);if not usable(actor) then return nil,'leave vehicle or unavailable player' end
    local graph,why=self:refresh();if not graph then return nil,why end
    local root,reason=self.host.resolve(ref,p);if not root then return nil,reason end
    if root.kind~='vehicle' or not self:near(p,actor,root) then return nil,'endpoint not reachable' end
    local plan,err=require('CVP_LinkRewire').plan(graph,self.index,self.host,self.host.vehicle(root),actor)
    if not plan then return nil,err end
    for _,row in ipairs(plan.rows) do if not self.store.linkReady(graph.links[row.id]) then return nil,'material unavailable' end end
    local token=self.host.uuid();self.rewires=self.rewires or {}
    self.rewires[actor.key]={token=token,plan=plan,step=2,at=self.host.now()}
    return {token=token,steps=G.copy(plan.steps),rows=G.copy(plan.rows)}
end
function Service:visitRewire(p,token)
    local actor=self.host.actor(p);if not usable(actor) then return false,'leave vehicle or unavailable player' end
    local pending=self.rewires and self.rewires[actor.key]
    if not pending or pending.token~=token or self.host.now()-pending.at>120000 then return false,'attachment expired' end
    local graph,err=self:refresh();if not graph then return false,err end
    local Rewire=require 'CVP_LinkRewire'
    local why=Rewire.validate(pending.plan,graph,self.index,self.host,actor);if why then return false,why end
    local point=self.host.sample(pending.plan.steps[pending.step])
    if not point or not self:near(p,actor,point) then return false,'endpoint not reachable' end
    for _,row in ipairs(pending.plan.rows) do if not self.store.linkReady(graph.links[row.id]) then return false,'material unavailable' end end
    if pending.step==#pending.plan.steps then
        local ok,why=self:flush();if not ok then return false,why end
        local out,problem=Rewire.apply(pending.plan,self.graph,self.host);if not out then return false,problem end
        if self.host.path then for _,row in ipairs(pending.plan.rows) do
            local link=out.links[row.id];local blocked=self.host.path(link.a,link.b)
            if blocked then return false,blocked end
        end end
        out.revision=self.persistedRevision+1
        local saved,err=self:commit(out);if not saved then return false,err end
        self.rewires[actor.key]=nil;return true,{done=true}
    end
    pending.at=self.host.now();pending.step=pending.step+1
    return true,{done=false}
end
-- Authority-only lifecycle changes. A missing object releases just that end;
-- it never returns equipment or dismantles the rest of the component.
function Service:releaseSystem(requests)
    local graph,err=self:refresh();if not graph then return false,err end
    local observed=graph
    local changed=false;local diagnostics={}
    for _,request in ipairs(requests) do
        local link=graph.links[request.id];local side=request.side
        if link and self.store.linkReady(link) and observed.links[request.id].revision==request.revision and (side=='a' or side=='b')
            and (link[side].kind=='body' or G.tractor(link[side])) then
            local where=request.where or link[side]
            if self.host.ground then where=self.host.ground(where) end
            local out,why
            if link[side].kind=='body' then
                local idx=G.index(graph)
                for _,edge in ipairs(idx.byBody[link[side].key]) do
                    if not self.store.linkReady(graph.links[edge.id]) then return false,'material unavailable' end
                end
                out,why=G.unloadBody(graph,link[side].key,where,link.owner,true)
            else out,why=G.releaseEnd(graph,link.id,link.revision,side,where,link.owner,true) end
            if not out then return false,why end
            graph=out;changed=true
            diagnostics[#diagnostics+1]=request.diagnostic or ('reason='..(request.reason or 'system')..' link='..link.id..' side='..side)
        end
    end
    if not changed then return true end
    graph.revision=self.persistedRevision+1
    local saved,why=self:commit(graph)
    if saved then for _,message in ipairs(diagnostics) do print('[CVP detach] '..message) end end
    return saved,why
end
function Service:unloadBody(key,where)
    local graph,err=self:refresh();if not graph then return false,err end
    local edges=self.index.byBody[key];if not edges then return true end
    for _,edge in ipairs(edges) do if not self.store.linkReady(graph.links[edge.id]) then return false,'material unavailable' end end
    local owner=graph.links[edges[1].id].owner
    local out,why=G.unloadBody(graph,key,where,owner,true);if not out then return false,why end
    out.revision=self.persistedRevision+1
    return self:commit(out)
end
function Service:tick(samples,holders)
    local graph,err=self:refresh();if not graph then return false,err end
    local changed=false;local expired=false
    for id,link in pairs(graph.links) do
        if self.store.linkReady(link) then
            local moved,dropped,why,updated=G.advance(link,samples[id] or {},holders,true)
            if not why and (updated or moved~=link) then graph.links[id]=moved;changed=true;expired=expired or dropped end
        end
    end
    if changed then self.dirty=true;if expired then self.index=assert(G.index(graph)) end end
    local now=self.host.now()
    for actor,row in pairs(self.pending) do if now-row.at>120000 then self.pending[actor]=nil end end
    for actor,row in pairs(self.rewires or {}) do if now-row.at>120000 then self.rewires[actor]=nil end end
    -- Persist moves together, not one disk write per end/frame. Forced releases
    -- and OnSave use the same path immediately; a failed write remains retryable.
    if self.dirty and now>=(self.nextWrite or 0) and (expired or now-self.lastSave>=2000) then return self:flush() end
    return true
end
return Service
