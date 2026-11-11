-- Historical harness adapter only; production has no geometric load prediction.
-- Root reaction is authoritative; geometric slack cannot predict its magnitude.
local P={}
function P.capture(simulation,graph,loads)
    for _,row in pairs(loads) do row.loadEstimate=nil end
end
-- Keep the caller contract; do not reconstruct body mass on the owning client.
function P.force(state,row,now,anchors)
    return row.resistanceForceN,nil
end
return P
