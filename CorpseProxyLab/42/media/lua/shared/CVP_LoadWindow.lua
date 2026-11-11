-- Integrate authority load over the send interval; never replay packet impulses.
local W={}
function W.new() return {rows={},seconds=0} end
function W.clear(w) w.rows={};w.seconds=0 end
function W.add(w,loads,dt,revision,valid)
    if not valid or w.revision~=revision then W.clear(w);w.revision=revision end
    if not valid or dt<=0 then return end
    w.seconds=w.seconds+dt
    for vehicle,forceN in pairs(loads or {}) do
        local owner=vehicle.getNetPlayerId and vehicle:getNetPlayerId() or nil
        local r=w.rows[vehicle]
        if not r or r.owner~=owner then r={area=0,owner=owner,start=r and w.seconds-dt or 0};w.rows[vehicle]=r end
        r.area=r.area+forceN*dt
    end
end
function W.force(w,vehicle,fallback)
    local r=w.rows[vehicle]
    if w.seconds<=0 then return fallback end
    if not r then return 0 end
    local owner=vehicle.getNetPlayerId and vehicle:getNetPlayerId() or nil
    if owner~=r.owner then return 0 end
    local interval=w.seconds-r.start
    if interval<=0 then return fallback end
    return r.area/interval
end
function W.interval(w,vehicle,fallback)
    if w.seconds<=0 then return fallback end
    local r=w.rows[vehicle]
    return r and math.max(0,w.seconds-r.start) or w.seconds
end
return W
