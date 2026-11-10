-- Ledger values only: no inventory transfers, native codec or persistence calls.
local materials={['Base.Rope']=true,['Base.HeavyChain']=true,['Base.HeavyChain_Hook']=true}
local function keyValid(k) return type(k)=='string' and #k>0 and #k<=256 end
local function copy(v,seen,depth)
    if type(v)~='table' then
        assert(type(v)=='nil' or type(v)=='string' or type(v)=='boolean' or type(v)=='number' and v==v and math.abs(v)<math.huge,'invalid ledger value')
        return v
    end
    seen=seen or {};depth=depth or 0;assert(not seen[v] and depth<20,'invalid ledger nesting');seen[v]=true
    local out={};for k,x in pairs(v) do assert(type(k)=='string' or type(k)=='number','invalid ledger key');out[k]=copy(x,seen,depth+1) end
    seen[v]=nil;return out
end
local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~='table' then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end;return true
end
local function rowValid(row)
    return type(row)=='table' and type(row.id)=='number' and row.id==math.floor(row.id)
        and row.id>=-2147483648 and row.id<=2147483647 and materials[row.type]
        and (row.state=='taking' or row.state=='held' or row.state=='returning' or row.state=='released' or row.state=='unresolved')
        and type(row.payload)=='string' and #row.payload>0 and #row.payload<=22000 and not row.payload:find('[\128-\255]')
        and ((row.state=='held' or row.state=='released') or type(row.owner)=='table'
            and (row.owner.kind=='player' and keyValid(row.owner.key) or row.owner.kind=='body' and keyValid(row.owner.key)
                or row.owner.kind=='ground' and type(row.owner.x)=='number' and type(row.owner.y)=='number' and type(row.owner.z)=='number'))
        and (row.state~='unresolved' or row.operation=='taking' or row.operation=='returning')
        and (row.receipt==nil or keyValid(row.receipt) and row.owner and row.owner.kind=='player')
        and (row.extensionLength==nil or type(row.extensionLength)=='number' and row.extensionLength>=.1 and row.extensionLength<=12)
        and (row.bodyKey==nil or keyValid(row.bodyKey) and type(row.metadata)=='table'
            and type(row.metadata.connection)=='table' and type(row.metadata.connection.b)=='table'
            and row.metadata.connection.b.key==row.bodyKey)
        and (row.legacy==nil or row.bodyKey==nil and type(row.legacy)=='table'
            and keyValid(row.legacy.bodyKey) and keyValid(row.legacy.connection))
end
local function graphValid(data,idx)
    if data.version==2 and data.graph==nil then return true end
    if data.version~=3 then return false,'invalid equipment graph version' end
    if not idx then local err;idx,err=require('CVP_LinkGraph').index(data.graph);if not idx then return false,err end end
    for equipment,id in pairs(idx.equipment) do
        local row=data.rows[equipment];local link=data.graph.links[id]
        if not row or row.state=='released' and not link.returning or row.bodyKey or row.type~=link.material then return false,'graph equipment conflict' end
        if equipment==link.extension and (row.state=='taking' or row.operation=='taking')
            and (not row.extensionLength or row.extensionLength+12~=link.length) then return false,'invalid extension recovery length' end
    end
    -- A pending tail transfer may be rolled back after reload. Its old segment
    -- must not be independently edited until that transfer is acknowledged.
    for equipment,row in pairs(data.rows) do if row.tailOriginal then
        local original=row.tailOriginal;local current=data.graph.links[original.id]
        if row.state~='taking' and row.operation~='taking' or not current
            or current.revision~=original.revision+1 or not data.graph.links['tail:'..equipment] then
            return false,'pending tail changed'
        end
    end end
    local valid,why=require('CVP_LinkClocks').valid(data,idx)
    return valid,why,idx
end
local function validateStore(data,graphIndex)
    if type(data)~='table' or (data.version~=2 and data.version~=3) or type(data.rows)~='table' then return nil,'invalid equipment store' end
    if data.retired~=nil then
        if type(data.retired)~='table' then return nil,'invalid equipment membership' end
        for vehicle,connections in pairs(data.retired) do
            if not keyValid(vehicle) or type(connections)~='table' then return nil,'invalid equipment membership' end
            for id,value in pairs(connections) do if not keyValid(id) or value~=true then return nil,'invalid equipment membership' end end
        end
    end
    if data.legacyMembership~=nil then
        if type(data.legacyMembership)~='table' then return nil,'invalid equipment membership' end
        for vehicle,connections in pairs(data.legacyMembership) do
            if not keyValid(vehicle) or type(connections)~='table' then return nil,'invalid equipment membership' end
            for id,parent in pairs(connections) do if not keyValid(id) or parent~=true and not keyValid(parent) then return nil,'invalid equipment membership' end end
        end
    end
    local ids,bodies,receipts={},{},{}
    for key,row in pairs(data.rows) do
        local bodyKey=type(row)=='table' and (row.bodyKey or type(row.legacy)=='table' and row.legacy.bodyKey)
        if not keyValid(key) or not rowValid(row) or row.metadata and row.metadata.equipmentKey~=key
            or row.state~='released' and ids[row.id] or bodyKey and bodies[bodyKey]
            or row.receipt and receipts[row.receipt] then return nil,'invalid or duplicate equipment row' end
        if row.metadata and (type(row.metadata)~='table' or type(row.metadata.connection)~='table'
            or not keyValid(row.metadata.connection.id) or row.metadata.connection.a~=nil and type(row.metadata.connection.a)~='table') then return nil,'invalid legacy metadata' end
        if row.state~='released' then ids[row.id]=key end
        if bodyKey then bodies[bodyKey]=key end
        if row.receipt then receipts[row.receipt]=key end
    end
    local shadow=copy(data)
    local goodGraph,graphError,idx=graphValid(data,graphIndex);if not goodGraph then return nil,graphError end
    return shadow,nil,idx
end
return {materials=materials,keyValid=keyValid,copy=copy,equal=equal,rowValid=rowValid,validateStore=validateStore}
