-- Authority-only floor blood after a successful world-pose commit. The engine
-- stores bounded chunk splats and replicates AddBlood to nearby MP clients.
local Blood={}
local spacings={2,1,.5}
function Blood.trail(r)
    if isClient() then return end
    local b,p=r.body,r.before
    if SandboxVars.CorpseProxyLab.BloodTrails==false or b:isSkeleton() then r.bloodDistance=0;return end
    local spacing=spacings[SandboxVars.CorpseProxyLab.BloodTrailDensity or 2] or 1
    -- A live density change must not turn the old remainder into a burst of blood.
    if r.bloodSpacing and r.bloodSpacing~=spacing then r.bloodDistance=0 end
    r.bloodSpacing=spacing
    if r.effectDistance then
        local total=(r.bloodDistance or 0)+r.effectDistance
        r.bloodDistance=total%spacing
        local count=math.min(4,math.floor(total/spacing))
        local sq=b:getSquare()
        -- Sparse splats at the actual committed position; never a straight line across turns/walls.
        if count>0 and sq then addBloodSplat(sq,count,b:getX()-math.floor(b:getX()),b:getY()-math.floor(b:getY())) end
        return
    end
    local dx,dy=b:getX()-p.x,b:getY()-p.y
    local distance=math.sqrt(dx*dx+dy*dy)
    -- Never draw across teleports, floor transitions or a newly loaded gap.
    if math.floor(b:getZ())~=math.floor(p.z) or distance>4 then r.bloodDistance=0;return end
    if distance==0 then return end
    local carried=r.bloodDistance or 0
    local offset=spacing-carried
    r.bloodDistance=(carried+distance)%spacing
    while offset<=distance do
        local x,y=p.x+dx*offset/distance,p.y+dy*offset/distance
        local sq=getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(p.z))
        if sq then addBloodSplat(sq,1,x-math.floor(x),y-math.floor(y)) end
        offset=offset+spacing
    end
end
function Blood.committed(group)
    for _,r in ipairs(group.records) do
        local ok,err=pcall(Blood.trail,r)
        -- A cosmetic failure cannot roll back bodies or interrupt inventory work.
        if not ok and not Blood.reported then Blood.reported=true;print('[CVP blood] '..tostring(err)) end
    end
end
return Blood
