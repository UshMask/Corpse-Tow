-- Compatibility with pre-graph saves. Never creates replacement bodies or gear.
local Legacy={}
function Legacy.vehicleKey(md)
    return md and (md.rootVehicle or md.vehicle or md.connection.a and md.connection.a.key)
end
function Legacy.forgetLegacy(data,md)
    local vehicle=Legacy.vehicleKey(md);if not vehicle then return end
    data.legacyMembership=data.legacyMembership or {}
    data.legacyMembership[vehicle]=data.legacyMembership[vehicle] or {}
    data.legacyMembership[vehicle][md.connection.id]=nil
end
function Legacy.markTail(data,md)
    local id=md and md.connection and md.connection.id;if not id then return end
    local ended={[id]=true};local changed=true
    while changed do changed=false
        for _,row in pairs(data.rows) do local m=row.metadata
            if row.state~='released' and m and m.parentConnection and ended[m.parentConnection] and not ended[m.connection.id] then
                ended[m.connection.id]=true;m.ended=true;changed=true
            end
        end
        for _,members in pairs(data.legacyMembership or {}) do
            for child,parent in pairs(members) do
                if type(parent)=='string' and ended[parent] and not ended[child] then ended[child]=true;changed=true end
            end
        end
    end
    for _,members in pairs(data.legacyMembership or {}) do for connection in pairs(ended) do members[connection]=nil end end
end
local function rootOf(id,members)
    local seen={}
    while members[id]~=true do
        if seen[id] or type(members[id])~='string' then return end
        seen[id]=true;id=members[id]
    end
    return id
end
function Legacy.migrate(self)
    local E=require 'CVP_Equipment'
    local World=require 'CVP_World'
    local Core=require 'CVP_Core'
    -- Import complete independent trains. A sleeping legacy tail must not be
    -- accidentally reattached to a car after its root was edited in the graph.
    local byID={};local hasLegacy=false;local now=self.host.now()
    self.legacyChecks=self.legacyChecks or setmetatable({},{__mode='k'})
    local checked=self.legacyChecks
    for _,body in pairs(self.host.bodies) do if body and
        (body:getModData().CVPTether or self.recoveryErrors[body] or not checked[body] or now>=checked[body]) then
        if body:getModData().CVPTether then
            local saved,why=self.service:flush();if not saved then return false,why end
        end
        local ok,err=E.observeBody(body);self.recoveryErrors[body]=not ok and err or nil
        if ok then checked[body]=now+5000 end
        local md=body:getModData().CVPTether
        if ok and World.valid(md) and not md.ended then byID[md.connection.id]={body=body,md=md};hasLegacy=true end
    end end
    local visited={}
    for _,car in pairs(self.host.vehicles) do if car and not visited[car] then
        visited[car]=true;local key=car:getModData().CVPVehicleKey
        if key and (hasLegacy or car:getModData().CVPConnections or not checked[car] or now>=checked[car]) then
            local members,err=E.members(key,car:getModData().CVPConnections)
            if not members then return false,err end
            local groups={}
            for id in pairs(members) do local root=rootOf(id,members)
                if root then groups[root]=groups[root] or {};table.insert(groups[root],id) end
            end
            for _,ids in pairs(groups) do
                local entries={};local ready=true;table.sort(ids)
                for _,id in ipairs(ids) do local row=byID[id]
                    if not row then ready=false;break end
                    local md,b=row.md,row.body
                    local a=self.host.sample(md.connection.a);local endpoint=self.host.sample(md.connection.b)
                    if not a or not endpoint or math.floor(a.z)~=math.floor(endpoint.z) or not World.gear(b,md) then ready=false;break end
                    entries[#entries+1]={id=id,a=a,b=endpoint,owner=md.owner or 'legacy:unowned',body=b,metadata=md}
                end
                if ready then
                    local ok,why=self.service:flush();if not ok then return false,why end
                    for _,entry in ipairs(entries) do local md=entry.metadata
                        if md.version==2 then
                            local gear=World.gear(entry.body,md)
                            local saved,err=E.hold(gear,self.host.transfer,{body=entry.body,metadata=md})
                            if not saved or err then return false,err or 'legacy equipment unavailable' end
                            local observed,why=E.observeBody(entry.body);if not observed then return false,why end
                            md=entry.body:getModData().CVPTether
                        end
                        entry.key=md.equipmentKey
                    end
                    local imported,problem=E.migrateLinks(entries);if not imported then return false,problem end
                    self.service.graph=nil
                    local graph,why=self.service:refresh();if not graph then return false,why end
                    for _,entry in ipairs(entries) do
                        local clean,err=E.observeBody(entry.body);if not clean then return false,err end
                    end
                end
            end
            Core.observeVehicle(car);checked[car]=now+5000
        end
    end end
    return true
end
function Legacy.import(data,entries,readRow,copy)
    local G=require('CVP_LinkGraph');local graph=data.graph or G.empty();local seen={}
    for _,entry in ipairs(entries) do
        local row,why=readRow(entry.key);if not row then return false,why end
        local md=row.metadata
        if seen[entry.key] or row.state~='held' or not row.bodyKey or not md or md.ended
            or type(md.connection.a)~='table' or type(entry.a)~='table' or type(entry.b)~='table'
            or md.connection.id~=entry.id or entry.b.kind~='body' or entry.b.key~=row.bodyKey
            or entry.a.kind~=md.connection.a.kind or entry.a.key~=md.connection.a.key
            or entry.a.point~=md.connection.a.point or entry.b.point~=md.connection.b.point then return false,'legacy import conflict' end
        seen[entry.key]=true
        if graph.links[entry.id] then return false,'legacy connection already imported' end
        -- Import the saved working length, even if a car moved away while the
        -- body was unloaded. Creating a new attachment would incorrectly refit
        -- it (or reject a stretched but otherwise intact old connection).
        graph.links[entry.id]={id=entry.id,revision=1,a=copy(entry.a),b=copy(entry.b),
            equipment=entry.key,material=row.type,owner=entry.owner,length=md.length}
        graph.revision=graph.revision+1
        local valid,problem=G.index(graph);if not valid then return false,problem end
        Legacy.forgetLegacy(data,md)
        local updated=data.rows[entry.key]
        updated.legacy={bodyKey=row.bodyKey,connection=entry.id};updated.bodyKey=nil;updated.metadata=nil
    end
    data.version=3;data.graph=graph;return data
end
return Legacy
