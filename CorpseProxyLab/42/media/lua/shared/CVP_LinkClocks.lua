-- One cumulative removal clock per graph body, not a history of transitions.
-- Graph edits and pause transitions share the equipment ledger's atomic write.
local G=require 'CVP_LinkGraph'
local C={}
local function finite(x) return type(x)=='number' and x==x and math.abs(x)<math.huge end
local function key(x) return type(x)=='string' and #x>0 and #x<=256 end
local function rooted(index)
    local result,seen={},{}
    for name,node in pairs(index.nodes) do if G.tractor(node) and not seen[name] then
        local queue={name};seen[name]=true;local n=1
        while n<=#queue do
            local current=index.nodes[queue[n]];n=n+1
            if current.kind=='body' then result[current.key]=true end
            for _,edge in ipairs(current.edges) do if not seen[edge.other] then
                seen[edge.other]=true;queue[#queue+1]=edge.other
            end end
        end
    end end
    return result
end
function C.valid(data,index)
    local clocks=data.bodyClocks
    if clocks==nil then return true end -- Old store 2 and development store 3.
    if type(clocks)~='table' then return false,'invalid body clocks' end
    local roots=rooted(index)
    for id,row in pairs(clocks) do
        if not key(id) or type(row)~='table' or not key(row.epoch) or not finite(row.started)
            or not finite(row.at) or row.at<row.started or not finite(row.elapsed) or row.elapsed<0
            or type(row.paused)~='boolean' or row.paused~=(roots[id]==true) then return false,'invalid body clock' end
        for field in pairs(row) do
            if field~='epoch' and field~='started' and field~='at' and field~='elapsed' and field~='paused' then return false,'invalid body clock field' end
        end
    end
    for id in pairs(index.byBody) do if not clocks[id] then return false,'missing body clock' end end
    return true
end
function C.reconcile(data)
    if data.version~=3 then return true end
    local index,err=G.index(data.graph);if not index then return false,err end
    local now=getGameTime():getWorldAgeHours()
    if not finite(now) then return false,'world clock unavailable' end
    local roots=rooted(index);local clocks=data.bodyClocks or {};data.bodyClocks=clocks
    for id in pairs(index.byBody) do if not clocks[id] then
        clocks[id]={epoch=getRandomUUID(),started=now,at=now,elapsed=0,paused=roots[id]==true}
    end end
    for id,row in pairs(clocks) do
        local paused=roots[id]==true
        if row.paused~=paused then
            if not row.paused then row.elapsed=row.elapsed+math.max(0,now-row.at) end
            row.at=math.max(row.at,now);row.paused=paused
        end
    end
    local valid,why=C.valid(data,index)
    return valid,why,index
end
return C
