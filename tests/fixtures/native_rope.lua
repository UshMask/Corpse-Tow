-- Lua reference arithmetic models the native shape entry point for orchestration tests.
-- Real numeric parity and immutable frame ownership are covered by Java validators.
function installNativeRopeScene(scene)
    local frames={}
    local remove=scene.remove
    scene.remove=function(id) remove(id);frames[id]=nil end
    function scene.endpoints(id,ax,ay,az,bx,by,bz)
        local frame=frames[id];if not frame then return end
        local points=frame.points;local a,b=points[1],points[#points];local out={}
        for i,p in ipairs(points) do
            local t=(i-1)/(#points-1)
            out[i]={x=p.x+(ax-a.x)*(1-t)+(bx-b.x)*t,
                y=p.y+(ay-a.y)*(1-t)+(by-b.y)*t,
                z=p.z+(az*3-a.z)*(1-t)+(bz*3-b.z)*t}
            if i>1 and i<#points then out[i].z=math.max(out[i].z,math.floor(math.min(az,bz))*3+.075) end
        end
        scene.update(id,out,frame.chain);frame.points=out
    end
    function scene.shape(id,r,ax,ay,az,dt,chain)
        r.gear={getFullType=function() return chain and 'Base.HeavyChain' or 'Base.Rope' end}
        local points,unchanged=require('CVP_Rope').shape(r,ax,ay,az,dt)
        if not unchanged or r.uploadPending or r.testChain~=chain then
            r.uploadPending=true
            scene.update(id,points,chain)
            frames[id]={points=equipmentCopy(points),chain=chain}
            r.uploadPending=nil;r.testChain=chain
        end
    end
end
