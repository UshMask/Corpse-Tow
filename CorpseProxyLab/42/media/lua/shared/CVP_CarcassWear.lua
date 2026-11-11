-- Authority-only wear uses vanilla butchering data; never edits inventory or age.
local W={}
local rates={.5,1,2}
function W.committed(group)
    local rules=SandboxVars.CorpseProxyLab or {}
    if isClient() or rules.CarcassWear==false then return end
    local rate=rates[rules.CarcassWearRate or 2] or 1
    for _,r in ipairs(group.records) do
        local b=r.body
        if b:isAnimal() and not b:isPlayer() then
            local md=b:getModData();local ratio=md.meatRatio
            if md.parts and not md.skeleton and type(ratio)=='number' and ratio==ratio and ratio>0 and ratio<math.huge then
                local distance=r.effectDistance or 0
                if distance>0 and distance<math.huge then
                    local state=md.CVPCarcassWear
                    if not state then state={distance=0,steps=0};md.CVPCarcassWear=state end
                    if state.steps<10 then
                        state.distance=math.min(1100,state.distance+distance*rate)
                        local steps=math.min(10,math.max(0,math.floor((state.distance-100)/100)))
                        if steps>state.steps then
                            -- Scale the current value, preserving other mods' changes.
                            md.meatRatio=ratio*(1-steps*.01)/(1-state.steps*.01)
                            state.steps=steps
                            b:transmitModData()
                        end
                    end
                end
            end
        end
    end
end
return W
