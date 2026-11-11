-- Rebuild one loaded vehicle group atomically; equipment keeps its stable key.
local World=require 'CVP_World'
local R={}
local function xy(r) return r.body:getX(),r.body:getY() end
local function distance(a,b)
    local ax,ay=a.x,a.y;local bx,by=b.x,b.y
    return math.sqrt((ax-bx)^2+(ay-by)^2)
end
function R.plan(v,rows,point)
    if #rows<2 or #rows>World.maxChain() then return nil,'IGUI_CVP_RewireLimit' end
    local ax,ay=require('CVP_Geometry').anchor(v,point)
    local pool,points={},{}
    for _,r in ipairs(rows) do local x,y=xy(r);points[r]={x=x,y=y};pool[#pool+1]=r end
    local order={};local last={x=ax,y=ay}
    while #pool>0 do
        local best,bd
        for i,r in ipairs(pool) do local d=distance(last,points[r])
            if d<=8 and (not bd or d<bd or d==bd and r.connection.id<pool[best].connection.id) then best,bd=i,d end
        end
        if not best then return nil,'IGUI_CVP_RewireSpread' end
        local r=table.remove(pool,best);order[#order+1]=r;last=points[r]
    end
    local function length(list)
        local d=0;local prev={x=ax,y=ay}
        for _,r in ipairs(list) do d=d+distance(prev,points[r]);prev=points[r] end
        return d
    end
    -- Preserve a shorter existing train; never worsen it with a greedy restart.
    local child,root={},nil;local roots=0
    for _,r in ipairs(rows) do if r.parent then child[r.parent]=r else root=r;roots=roots+1 end end
    if roots==1 then
        local existing,seen={},{};local r=root
        while r and not seen[r] do seen[r]=true;existing[#existing+1]=r;r=child[r] end
        if #existing==#rows and length(existing)<=length(order) then order=existing end
    end
    -- Bounded 2-opt: reversing a segment only changes its two outer edges.
    for pass=1,4 do local changed=false
        for i=1,#order-1 do for j=i+1,#order do
            local a=i==1 and {x=ax,y=ay} or points[order[i-1]]
            local b,c=points[order[i]],points[order[j]]
            local d=j<#order and points[order[j+1]]
            local old=distance(a,b)+(d and distance(c,d) or 0)
            local new=distance(a,c)+(d and distance(b,d) or 0)
            if new+.01<old and distance(a,c)<=8 and (not d or distance(b,d)<=8) then
                local lo,hi=i,j;while lo<hi do order[lo],order[hi]=order[hi],order[lo];lo=lo+1;hi=hi-1 end
                changed=true
            end
        end end
        if not changed then break end
    end
    local same=true
    for i,r in ipairs(order) do if r.parent~=(i>1 and order[i-1] or nil) then same=false end end
    if same then return nil,'IGUI_CVP_RewireOptimal' end
    return order
end
return R
