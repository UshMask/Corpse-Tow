-- Historical controller operations; inserted only by the legacy test loader.
function E.updateBindings(entries)
    local r,err=prepare();if not r then return false,err end
    local data=copy(r.data);local seen={}
    for _,entry in ipairs(entries) do
        local row,why=current(r,entry.key);if not row then return false,why end
        local body=entry.body;local md=entry.metadata
        if row.state~='held' or seen[entry.key] or not body or row.bodyKey~=body:getModData().CVPBodyKey
            or not md or not md.connection or not md.connection.b or md.connection.b.key~=row.bodyKey then return false,'equipment binding conflict' end
        seen[entry.key]=true;local ok,binding=pcall(copy,md);if not ok then return false,tostring(binding) end
        binding.version=3;binding.equipmentKey=entry.key
        Legacy.forgetLegacy(data,row.metadata);Legacy.forgetLegacy(data,binding)
        data.rows[entry.key].metadata=binding
    end
    return write(r,data)
end
function E.endTail(md)
    local r,err=prepare();if not r then return false,err end
    local data=copy(r.data);Legacy.markTail(data,md)
    if equal(data,r.data) then return true end
    return write(r,data)
end
