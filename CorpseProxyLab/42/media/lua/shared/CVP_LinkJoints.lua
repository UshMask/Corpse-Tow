-- Empty attachment nodes keep the original sections and their equipment budgets.
-- A span between remaining bodies is solved at its combined length; empty nodes
-- are placed along that span. No surrogate corpse or inventory is created.
local G=require 'CVP_LinkGraph'
local J={}
function J.length(path,graph)
    local length,capacity=0,0
    for _,edge in ipairs(path) do local link=graph.links[edge.id]
        length=length+link.length;capacity=capacity+G.capacityFor(link)
    end
    return length,capacity
end
function J.place(group,graph,host)
    host.joints=host.joints or {};host.freeEnds=host.freeEnds or {}
    -- A terminal joint can survive removal of its other section. Even a single
    -- remaining section must drag that free endpoint within its length.
    for _,span in ipairs(group.spans) do if #span>0 then
        local first,last=span[1],span[#span]
        local source=host.sample(graph.links[first.id][first.side])
        local targetRef=graph.links[last.id][last.side=='a' and 'b' or 'a']
        local target=host.sample(targetRef)
        if source and target then
            local total=J.length(span,graph);local dx,dy=target.x-source.x,target.y-source.y
            local d=math.sqrt(dx*dx+dy*dy)
            if targetRef.kind=='ground' or targetRef.kind=='joint' then
                local reach=math.sqrt(math.max(0,total*total-((target.z-source.z)*3)^2))
                if d>reach and d>0 then
                    target=G.copy(target);target.x=source.x+dx*reach/d;target.y=source.y+dy*reach/d
                    if targetRef.kind=='ground' then host.freeEnds[targetRef]=target else host.joints[targetRef.key]=target end
                end
            end
            local walked=0
            for i=1,#span-1 do local edge=span[i];local link=graph.links[edge.id]
                walked=walked+link.length;local e=link[edge.side=='a' and 'b' or 'a'];local f=walked/total
                host.joints[e.key]={kind='joint',key=e.key,x=source.x+(target.x-source.x)*f,
                    y=source.y+(target.y-source.y)*f,z=source.z+(target.z-source.z)*f}
            end
        end
    end end
end
return J
