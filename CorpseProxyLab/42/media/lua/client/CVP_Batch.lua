-- Inventory selection shared by the current menus and action queues.
local Batch={}
local materials={['Base.Rope']=1,['Base.HeavyChain']=2,['Base.HeavyChain_Hook']=3}
function Batch.equipment(p,material)
    local rows,seen={},{}
    local function collect(inv)
        if seen[inv] then return end;seen[inv]=true
        local items=inv:getItems()
        for i=0,items:size()-1 do local item=items:get(i)
            if materials[item:getFullType()] and (not material or item:getFullType()==material) and (not p.getPrimaryHandItem or p:getPrimaryHandItem()~=item)
                and (not p.getSecondaryHandItem or p:getSecondaryHandItem()~=item) then rows[#rows+1]=item end
            if instanceof(item,'InventoryContainer') then collect(item:getInventory()) end
        end
    end
    collect(p:getInventory())
    table.sort(rows,function(a,b)
        local x,y=materials[a:getFullType()],materials[b:getFullType()]
        return x<y or x==y and a:getID()<b:getID()
    end)
    return rows
end
return Batch
