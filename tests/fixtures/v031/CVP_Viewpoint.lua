local Rope=require 'CVP_Rope'
-- Rendering only: retain every physical node and soften the corners between them.
local function visualPoints(r)
    local points=r.ropePoints
    if not points or not r.gear or r.gear:getFullType()~='Base.Rope' then return points end
    local out=r.ropeVisualPoints or {};r.ropeVisualPoints=out
    local floor=((r.z or 0)+Rope.floorHeight)*3
    for i=1,#points-1 do
        local a,b=points[i],points[i+1]
        local prev,after=points[math.max(1,i-1)],points[math.min(#points,i+2)]
        out[2*i-1]=a
        local mid=out[2*i] or {};out[2*i]=mid
        for _,key in ipairs({'x','y','z'}) do
            mid[key]=(a[key]+b[key])*0.5+(a[key]-prev[key]+b[key]-after[key])*0.0625
        end
        mid.z=math.max(floor,mid.z)
    end
    out[#points*2-1]=points[#points]
    for i=#out,#points*2,-1 do out[i]=nil end
    return out
end
local Compat={}
function Compat.is3D()
    if not Viewpoint or not Viewpoint.View or not Viewpoint.View.next then return false end
    local destination=Viewpoint.View.next()
    return destination=='third' or destination=='isometric'
end
function Compat.track(body)
    if CVPViewpoint then CVPViewpoint.track(body) end
end
function Compat.untrack(body)
    if CVPViewpoint then CVPViewpoint.untrack(body) end
    if CVPRopeScene then CVPRopeScene.untrack(body) end
end
function Compat.clear()
    if CVPViewpoint then CVPViewpoint.clear() end
    if CVPRopeScene then CVPRopeScene.clear() end
end
function Compat.rope(r)
    if CVPRopeScene and r.ropePoints then
        -- Isometric view keeps every physical node but needs no extra smoothing
        -- samples. Camera changes affect only the native render instances.
        local points=r.ropePoints
        if Compat.is3D() then points=visualPoints(r) end
        if r.connection and r.connection.a.kind=='body' then
            if not CVPRopeScene.updateBody then return end -- older Java helper: requires restart/update
            local parent=r.parent
            CVPRopeScene.updateBody(r.body,r.vehicle,points,r.attachLocalX or r.footLocalX or -0.65,
                r.attachLocalY or r.footLocalY or 0,r.gear:getFullType()~='Base.Rope',
                parent and parent.body or r.sourceBody,parent and (parent.attachLocalX or parent.footLocalX) or r.sourceX,
                parent and (parent.attachLocalY or parent.footLocalY) or r.sourceY)
        else
        CVPRopeScene.update(r.body,r.vehicle,points,r.attachLocalX or r.footLocalX or -0.65,r.attachLocalY or r.footLocalY or 0,r.gear:getFullType()~='Base.Rope')
        end
    end
end
function Compat.project(x,y,z)
    if CVPViewpoint and CVPViewpoint.project(x,y,z) then
        return CVPViewpoint.screenX(),CVPViewpoint.screenY()
    end
    -- Never draw an isometric line over a perspective camera or across its near plane.
    return nil,nil
end
-- Optional rendering must not interrupt world/inventory operations; report once.
for name,call in pairs(Compat) do
    local method,fn=name,call
    Compat[method]=function(...)
        local ok,a,b=pcall(fn,...);if ok then return a,b end
        Compat[method]=function() end
        print('[CVP] Visual '..method..' disabled: '..tostring(a))
    end
end
return Compat
