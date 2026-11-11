-- World-space attachment and a conservative swept body footprint. No new actors.
local Geometry={}
local wrapAngle=require('CVP_Rope').wrapAngle
local Environment
local anchorPosition
local function finite(v) return type(v)=='number' and v==v and math.abs(v)<10000000 end
function Geometry.anchor(v,point)
    local attachment=point=='front' and 'trailerfront' or 'trailer'
    anchorPosition=anchorPosition or Vector3f.new()
    local out=anchorPosition
    if v.attachmentExist and v.getAttachmentWorldPos then
        local ok,x,y=pcall(function()
            if not v:attachmentExist(attachment) then return end
            local p=v:getAttachmentWorldPos(attachment,out)
            if p then return p:x(),p:y() end
        end)
        if ok and finite(x) and finite(y) then return x,y,v:getZ() end
    end
    v:getWorldPos(0,0,(point=='front' and 1 or -1)*v:getScript():getExtents():z()/2,out)
    return out:x(),out:y(),v:getZ()
end
function Geometry.capture(r)
    local b=r.body
    local function offset(method,default)
        local ok,x,y=pcall(function()
            local p=method(b,Vector2f.new())
            local dx,dy=p:x()-b:getX(),p:y()-b:getY()
            local a=b:getAngle();local c,s=math.cos(a),math.sin(a)
            return dx*c+dy*s,-dx*s+dy*c
        end)
        if ok and finite(x) and finite(y) and x*x+y*y>0.01 and x*x+y*y<4 then return x,y,true end
        return default,0,false
    end
    r.footLocalX,r.footLocalY,r.nativeFeet=offset(b.getGrabLegsPosition,-0.65)
    r.headLocalX,r.headLocalY=offset(b.getGrabHeadPosition,0.65)
    -- Three strips cover length and width; edges between samples catch thin walls.
    local dx,dy=r.headLocalX-r.footLocalX,r.headLocalY-r.footLocalY
    local length=math.sqrt(dx*dx+dy*dy)
    if length<0.1 then
        r.headLocalX=-r.footLocalX;r.headLocalY=-r.footLocalY
        dx,dy=r.headLocalX-r.footLocalX,r.headLocalY-r.footLocalY
        length=math.sqrt(dx*dx+dy*dy)
    end
    Geometry.footprint(r,dx,dy,length)
    r.attachLocalX,r.attachLocalY=r.footLocalX,r.footLocalY
    if r.point=='neck' then
        -- Head grab point shifted 18 cm toward the torso; retain full collision footprint.
        r.attachLocalX=r.headLocalX-dx/length*0.18
        r.attachLocalY=r.headLocalY-dy/length*0.18
    end
    -- Recalibrating an old live link must take up a changed endpoint gradually.
    r.ropeConstraintReady=nil;r.ropePoints=nil
    r.nativeResetConstraint=true
end
function Geometry.nearAnchor(p,v,point)
    if not v or not v:getSquare() or not p:getSquare() then return false end
    local x,y,z=Geometry.anchor(v,point)
    local sq=getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(z))
    return sq and math.floor(p:getZ())==math.floor(z) and (p:getX()-x)^2+(p:getY()-y)^2<=2.25
        and p:getSquare():canReachTo(sq)
end
function Geometry.nearestPoint(b,v,point)
    local r={body=b,point='neck'};Geometry.capture(r)
    local ax,ay=Geometry.anchor(v,point)
    local dx,dy=ax-b:getX(),ay-b:getY();local a=b:getAngle();local c,s=math.cos(a),math.sin(a)
    local x,y=dx*c+dy*s,-dx*s+dy*c
    local feet=(x-r.footLocalX)^2+(y-r.footLocalY)^2
    local neck=(x-r.attachLocalX)^2+(y-r.attachLocalY)^2
    return neck<feet and 'neck' or 'feet'
end
function Geometry.footprint(r,dx,dy,length)
    local nx,ny=-dy/length*0.22,dx/length*0.22
    local count=math.max(1,math.ceil(length/0.3));local samples={}
    for i=0,count do for side=-1,1 do
        samples[#samples+1]={x=r.footLocalX+dx*i/count+side*nx,y=r.footLocalY+dy*i/count+side*ny}
    end end
    r.footprint=samples;r.footprintRadius=math.max(math.sqrt(r.footLocalX^2+r.footLocalY^2),math.sqrt(r.headLocalX^2+r.headLocalY^2))+0.22
end
function Geometry.resolve(r,tx,ty,angle,oldAngle,environment)
    if not r.footprint then Geometry.capture(r) end
    local turn=wrapAngle(angle-oldAngle)
    if math.abs(tx-r.x)+math.abs(ty-r.y)+math.abs(turn)<0.000001 then return r.x,r.y,oldAngle,false end
    Environment=Environment or require 'CVP_LinkObstacles'
    local cache=environment or Environment.new();local z=math.floor(r.z)
    -- The radius encloses every orientation, including the entire rotation arc.
    -- Require all directed neighbouring edges (including diagonals) to be clear;
    -- any doubt falls back to the original detailed sweep and sliding response.
    local radius=r.footprintRadius
    local minX,maxX=math.floor(math.min(r.x,tx)-radius),math.floor(math.max(r.x,tx)+radius)
    local minY,maxY=math.floor(math.min(r.y,ty)-radius),math.floor(math.max(r.y,ty)+radius)
    -- Consecutive substeps usually stay inside the same swept bounds. Reuse only
    -- a successful proof from this exact tick; doors/unloads invalidate it next tick.
    if r.clearRegionCache==cache and r.clearMinX==minX and r.clearMaxX==maxX
        and r.clearMinY==minY and r.clearMaxY==maxY and r.clearZ==z then
        return tx,ty,oldAngle+turn,false
    end
    if (maxX-minX+1)*(maxY-minY+1)<=64 then
        cache.regions=cache.regions or {}
        local key=minX..':'..maxX..':'..minY..':'..maxY..':'..z
        local clear=cache.regions[key]
        if clear==nil then
            clear=Environment.bodyRegion(cache,minX,maxX,minY,maxY,z);cache.regions[key]=clear
        end
        if clear then
            r.clearRegionCache=cache;r.clearMinX=minX;r.clearMaxX=maxX
            r.clearMinY=minY;r.clearMaxY=maxY;r.clearZ=z
            return tx,ty,oldAngle+turn,false
        end
    end
    local function tile(x,y)
        return Environment.bodyTile(cache,math.floor(x),math.floor(y),z)
    end
    local function edge(a,b)
        return Environment.bodyEdge(cache,a,b)
    end
    local function passage(a,b)
        if not edge(a,b) then return false end
        if a.x~=b.x and a.y~=b.y then
            local h,v=tile(b.x,a.y),tile(a.x,b.y)
            return (edge(a,h) and edge(h,b)) or (edge(a,v) and edge(v,b))
        end
        return true
    end
    local function pose(x,y,a)
        local c,s=math.cos(a),math.sin(a);local cells={}
        for i,p in ipairs(r.footprint) do
            cells[i]=tile(x+c*p.x-s*p.y,y+s*p.x+c*p.y)
        end
        return cells
    end
    local function sweep(x,y,a,bx,by,ba)
        local da=wrapAngle(ba-a)
        local travel=math.sqrt((bx-x)^2+(by-y)^2)+r.footprintRadius*math.abs(da)
        local n=math.max(1,math.ceil(travel/0.15));local previous=pose(x,y,a)
        local lx,ly,la=x,y,a
        for step=1,n do
            local f=step/n;local px,py,pa=x+(bx-x)*f,y+(by-y)*f,a+da*f
            local cells=pose(px,py,pa)
            for i,t in ipairs(cells) do
                if not passage(previous[i],t)
                    or (i>3 and not passage(cells[i-3],t))
                    or (i%3~=1 and not passage(cells[i-1],t)) then return lx,ly,la,true end
            end
            lx,ly,la=px,py,pa;previous=cells
        end
        return lx,ly,la,false
    end
    local x,y,a,blocked=sweep(r.x,r.y,oldAngle,tx,ty,angle)
    if not blocked then return x,y,a,false end
    local function score(px,py) return (tx-px)^2+(ty-py)^2 end
    -- A blocked turn must not prevent translation parallel to an obstacle.
    if math.abs(turn)>0.000001 then
        local sx,sy,sa=sweep(r.x,r.y,oldAngle,tx,ty,oldAngle)
        if score(sx,sy)<score(x,y) then x,y,a=sx,sy,sa end
    end
    local sx,sy,sa=sweep(x,y,a,tx,y,a)
    local ux,uy,ua=sweep(x,y,a,x,ty,a)
    if score(sx,sy)<score(x,y) then x,y,a=sx,sy,sa end
    if score(ux,uy)<score(x,y) then x,y,a=ux,uy,ua end
    return x,y,a,true
end
return Geometry
