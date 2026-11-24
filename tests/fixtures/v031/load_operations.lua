-- Historical load ramp used by the pre-graph controller.
function Load.blend(dt) return 1-math.exp(-math.max(0,dt)/0.2) end
function Load.tension(r,taut,dt,blend)
    if not taut then r.loadMass=0;return 0 end
    local target=math.max(0,r.mass or 0)
    blend=blend or Load.blend(dt)
    r.loadMass=(r.loadMass or 0)+(target-(r.loadMass or 0))*blend
    return r.loadMass
end
