-- Historical controller operations; inserted only by the legacy test loader.
function Connection.chainSize(members,id)
    local seen={}
    while members[id]~=true do
        if seen[id] or type(members[id])~='string' then return math.huge end
        seen[id]=true;id=members[id]
    end
    local children={}
    for child,parent in pairs(members) do
        if type(parent)=='string' then
            children[parent]=children[parent] or {};table.insert(children[parent],child)
        end
    end
    local queue={id};local count=0;seen={}
    while count<#queue do
        count=count+1;local current=queue[count]
        if seen[current] then return math.huge end;seen[current]=true
        for _,child in ipairs(children[current] or {}) do queue[#queue+1]=child end
    end
    return count
end
