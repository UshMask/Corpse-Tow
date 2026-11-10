-- Shared SP/MP result contract. Time is milliseconds; intervals are seconds;
-- loads are nonnegative resistance forces in newtons, never replayable impulses.
local G=require 'CVP_LinkGraph'
local F={version=1}
function F.capture(simulation,graph,loads,now,intervalSeconds,sequence,host,samples)
    local frame={frameSchema=F.version,sequence=sequence,revision=graph.revision,
        sampledAt=simulation.sampledAt or now,intervalSeconds=intervalSeconds,
        bodies={},endpoints={},loads={},obstacles=G.copy(simulation.obstacles or {})}
    -- Final graph coordinates already include loose-end dragging. Resolve live
    -- attachments once here, then presentation consumes only these owned values.
    if host then
        samples=samples or host.samples(graph)
        for id,link in pairs(graph.links) do
            local ends={};frame.endpoints[id]=ends
            for _,side in ipairs({'a','b'}) do
                local ref=link[side]
                local p=ref.kind=='ground' and ref or samples[id] and samples[id][side]
                ends[side]=p and G.copy(p)
            end
        end
    end
    for vehicle,force in pairs(loads) do frame.loads[vehicle]=force end
    for _,r in pairs(simulation.records) do
        local ref=r.link[r.edge.side=='a' and 'b' or 'a']
        local current=graph.links[r.link.id]
        if current and current.revision==r.link.revision and ref.kind=='body' and r.body then
            local b=r.body
            frame.bodies[ref.key]={body=b,x=b:getX(),y=b:getY(),z=b:getZ(),angle=b:getAngle(),
                source=r.committedSource and G.copy(r.committedSource) or nil,
                sourceSampledAt=r.committedAt,corrected=r.corrected==true,
                parent=r.parent and r.parent.link[r.parent.edge.side=='a' and 'b' or 'a'].key or nil,
                token=r.link.id..':'..tostring(r.link.revision),
                vehicle=r.vehicle and not r.horse and r.vehicle:getId() or nil,taut=r.taut==true,blocked=r.blocked==true}
        end
    end
    -- Detached/body-only links have no towing solver record, but still need a
    -- frozen pose for knots and endpoint playback (never disappear on detach).
    if host then for _,link in pairs(graph.links) do for _,side in ipairs({'a','b'}) do
        local ref=link[side]
        if ref.kind=='body' and not frame.bodies[ref.key] then
            local b=host.body(ref)
            if b then frame.bodies[ref.key]={body=b,x=b:getX(),y=b:getY(),z=b:getZ(),angle=b:getAngle(),
                token='body:'..ref.key,taut=false,blocked=false} end
        end
    end end end
    return frame
end
return F
