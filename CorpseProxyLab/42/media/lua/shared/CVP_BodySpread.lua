-- Authority-only local spacing while being pulled; no vehicle-relative formation.
local S={}
function S.layout(groups)
    local fleets={}
    for _,g in ipairs(groups) do
        if not g.horse and #g.records==1 and #g.edges==1 then
            local r=g.records[1];local v=g.vehicle
            local fleet=fleets[v];if not fleet then fleet={};fleets[v]=fleet end
            local key=(r.source.point or 'hitch')..':'..math.floor(r.length/.75)
            local bucket=fleet[key];if not bucket then bucket={records={},reference=r};fleet[key]=bucket end
            bucket.records[#bucket.records+1]=r
        end
    end
    return fleets
end
local function order(a,b)
    if a.spreadSide==b.spreadSide then return a.link.id<b.link.id end
    return a.spreadSide<b.spreadSide
end
-- Reference/older-bridge implementation, kept separate from runtime dispatch.
local function updateLua(bucket,moving,width,speed)
    local rows=bucket.records
    for _,r in ipairs(rows) do r.spreadSpeed=0;r.spreadPush=0;r.spreadRemaining=0 end
    if moving and #rows>1 then
        -- Use the whole group's pull direction, not one body's rotation
        -- or the vehicle heading. No persistent target lanes.
        local dx,dy=0,0
        for _,r in ipairs(rows) do
            dx=dx+(r.ax or r.x)-r.x;dy=dy+(r.ay or r.y)-r.y
        end
        local distance=math.sqrt(dx*dx+dy*dy)
        local nx,ny
        if distance>0.001 then nx=-dy/distance;ny=dx/distance
        else local angle=bucket.reference.angle;nx=-math.sin(angle);ny=math.cos(angle) end
        local previous;local ordered=true
        for _,r in ipairs(rows) do
            r.spreadSide=r.x*nx+r.y*ny
            r.spreadNX=nx;r.spreadNY=ny
            if previous and order(r,previous) then ordered=false end
            previous=r
        end
        -- Moving neighbours usually keep their order. Check it during
        -- projection; sort only after a crossing or topology change.
        if not ordered then table.sort(rows,order) end
        -- Minimum-displacement spacing: adjacent blocks merge only when
        -- their corrected positions overlap. Splitting at the raw width
        -- instead makes the whole run's targets jump at that threshold.
        -- Reuse the rows as a block stack; each row is pushed/popped once.
        local blocks=bucket.blocks or {};bucket.blocks=blocks
        local top=0;local first=1
        for i,r in ipairs(rows) do
            top=top+1;blocks[top]=r
            r.spreadFirst=i;r.spreadCount=1
            r.spreadSum=r.spreadSide-(i-first)*width
            while top>1 do
                local a,b=blocks[top-1],blocks[top]
                if a.spreadSum/a.spreadCount<=b.spreadSum/b.spreadCount then break end
                a.spreadSum=a.spreadSum+b.spreadSum
                a.spreadCount=a.spreadCount+b.spreadCount
                blocks[top]=nil;top=top-1
            end
            local b=rows[i+1]
            local joined=b and not r.failed and not b.failed and math.floor(r.z)==math.floor(b.z)
                and math.abs((b.x-r.x)*ny-(b.y-r.y)*nx)<1.3
            if not joined then
                local scale=width
                for k=1,top do
                    local block=blocks[k];local count=block.spreadCount
                    if count>1 then
                        local start=block.spreadFirst;local last=start+count-1
                        local target=block.spreadSum/count+(start-first)*width
                        scale=math.max(scale,rows[start].spreadSide-target,
                            target+(count-1)*width-rows[last].spreadSide)
                        for j=start,last do
                            local row=rows[j];local delta=target+(j-start)*width-row.spreadSide
                            row.spreadPush=delta
                            row.spreadRemaining=math.abs(delta);row.spreadSpeed=speed
                        end
                    end
                    blocks[k]=nil
                end
                for j=first,i do
                    local r=rows[j]
                    -- A transient target relative to this tick's anchor;
                    -- substeps measure the remaining error after moving.
                    r.spreadOffset=r.ax and r.ay and r.spreadSide+r.spreadPush-r.ax*nx-r.ay*ny or nil
                    r.spreadScale=scale;r.spreadPush=r.spreadPush/scale
                end
                top=0;first=i+1
            end
        end
    end
end
function S.update(sim,solver)
    local rules=SandboxVars.CorpseProxyLab or {}
    if rules.BodySpread==false then
        if sim.spreading then for _,r in pairs(sim.records) do r.spreadSpeed=0 end end
        sim.spreading=false;return
    end
    if not sim.spreading or sim.spreadGroups~=sim.groups then
        for _,r in pairs(sim.records) do r.spreadSpeed=0 end
        sim.spreadFleets=S.layout(sim.groups)
        sim.spreadGroups=sim.groups
    end
    sim.spreading=true
    local width=rules.BodySpreadWidth==1 and .25 or rules.BodySpreadWidth==3 and .65 or .4
    local speed=rules.BodySpreadStrength==1 and .1 or rules.BodySpreadStrength==3 and .35 or .2
    if solver==nil then solver=CVPSolverNative and not CVPSolverUseLua and CVPSolverNative or false end
    local update=solver and solver.spread or updateLua
    for vehicle,fleet in pairs(sim.spreadFleets) do
        local moving=math.abs(vehicle:getCurrentSpeedKmHour())>1
        for _,bucket in pairs(fleet) do
            update(bucket,moving,width,speed)
        end
    end
end
return S
