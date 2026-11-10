-- Cosmetic recipe carried by the real inventory item, never an equipment claim.
local M={}
local function free(e) return e.kind=='ground' or e.kind=='joint' end
function M.eligible(graph,index,key)
    local id=index.equipment[key];if not id then return false end
    local pending={id};local seen={}
    while #pending>0 do
        local current=table.remove(pending)
        if not seen[current] then
            seen[current]=true;local link=graph.links[current]
            if not free(link.a) or not free(link.b) then return false end
            local spool=index.spools[link.equipment]
            for _,other in ipairs(spool.ids) do if not seen[other] then pending[#pending+1]=other end end
            for _,e in ipairs({link.a,link.b}) do if e.kind=='joint' then
                for _,edge in ipairs(index.byJoint[e.key] or {}) do
                    if not seen[edge.id] then pending[#pending+1]=edge.id end
                end
            end end
        end
    end
    return true
end
function M.recipe(graph,index,key)
    local ids=index.spools[key] and index.spools[key].ids or {index.equipment[key]}
    ids={unpack(ids)};table.sort(ids)
    local first=graph.links[ids[1]];local x,y,z=math.floor(first.a.x),math.floor(first.a.y),math.floor(first.a.z)
    local recipe={version=1,parts={}}
    for _,id in ipairs(ids) do local link=graph.links[id]
        -- An extended connection owns two originals; each draws only its half.
        local lo,hi=1,17
        if link.extension then if key==link.extension then lo=9 else hi=9 end end
        recipe.parts[#recipe.parts+1]={link.a.x-x,link.a.y-y,link.b.x-x,link.b.y-y,link.length,lo,hi}
    end
    return recipe,x,y,z
end
function M.points(recipe,x,y,z,material)
    if type(recipe)~='table' or recipe.version~=1 or type(recipe.parts)~='table'
        or #recipe.parts<1 or #recipe.parts>120 then return nil end
    local Rope=require 'CVP_Rope';local curves={}
    for _,p in ipairs(recipe.parts) do
        if type(p)~='table' or #p~=7 then return nil end
        for i=1,7 do if type(p[i])~='number' or p[i]~=p[i] or math.abs(p[i])>48 then return nil end end
        if p[5]<.1 or p[5]>24 or p[6]~=math.floor(p[6]) or p[7]~=math.floor(p[7])
            or p[6]<1 or p[7]>17 or p[7]<=p[6] then return nil end
        local r={x=x+p[3],y=y+p[4],z=z,angle=0,slot=1,attachLocalX=0,attachLocalY=0,
            anchorHeight=0,endHeight=Rope.floorHeight,length=p[5],gear={getFullType=function() return material end}}
        local all=Rope.seed(r,x+p[1],y+p[2],z+Rope.floorHeight);local points={}
        for i=p[6],p[7] do points[#points+1]=all[i] end
        curves[#curves+1]=points
    end
    return curves
end
return M
