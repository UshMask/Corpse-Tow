-- Engine-model counterpart of WorldBridge; never calls the production Lua wrapper.
-- Draw-only API: offsets are recorded separately from world coordinates.
local presentation={}
CVPBodyPresentation={version=function() return '1-shared-playback' end,
    stockSupported=function() return true end,
    update=function(rows)
        for _,r in ipairs(rows) do if r.body then
            presentation[r.body]={x=r.drawDX or 0,y=r.drawDY or 0}
        end end
    end,
    remove=function(body) presentation[body]=nil end,
    clear=function() presentation={} end}
local function present(b,pass)
    if pass then return CVPWorldNative.contains(pass,b) end
    return b:getSquare()~=nil and b:getStaticMovingObjectIndex()>=0
end
local function position(b,x,y,z,sq)
    b:setX(x);b:setY(y);b:setZ(z);b:setSquare(sq);b:setCurrent(sq)
end
function CVPWorldNative.move(b,x,y,z,sq,pass,before,skipInvalidation)
    local old,ox,oy,oz
    if before then old=before.square;ox=before.x;oy=before.y;oz=before.z
    else old=b:getSquare();ox=b:getX();oy=b:getY();oz=b:getZ() end
    assert(present(b,pass),'world corpse missing')
    if old==sq and ox==x and oy==y and oz==z then return end
    if old~=sq then
        local network=isClient() or isServer()
        local ok,err=pcall(function()
            CVPWorldNative.removePreservingPose(old,b)
            position(b,x,y,z,sq);sq:addCorpse(b,network)
            assert(present(b,pass),'destination did not register corpse')
        end)
        if not ok then
            if b:getStaticMovingObjectIndex()>=0 and b:getSquare()~=old then
                CVPWorldNative.removePreservingPose(b:getSquare(),b)
            end
            position(b,ox,oy,oz,old)
            if b:getStaticMovingObjectIndex()<0 then old:addCorpse(b,network) end
            error(err)
        end
    else position(b,x,y,z,sq) end
    if old==sq and skipInvalidation==nil then
        skipInvalidation=CVPDynamicCorpses and CVPDynamicCorpses.canSkipMoveInvalidation()
    end
    if old~=sq or not skipInvalidation then b:invalidateRenderChunkLevel(2) end
end
function CVPWorldNative.setAngle(b,angle)
    local previous=b:getAngle()
    if previous==angle then return end
    b:setForwardDirectionAngle(angle)
    local function bucket(a)
        local period=6.2831855
        return math.floor((a-math.floor(a/period)*period)*57.295776)
    end
    if bucket(previous)~=bucket(angle) then b:invalidateCorpse() end
end
function CVPWorldNative.applyPoses(records,pending,pass,skipInvalidation)
    local cell=getCell()
    for i,r in ipairs(records) do
        local b,p=r.body,r.before
        assert(b:getX()==p.x and b:getY()==p.y and b:getZ()==p.z
            and b:getAngle()==p.angle and b:getSquare()==p.square,'body changed before pose commit')
        -- Include the failing body, just as Java does before entering movePose.
        pending[i]=r
        local sq=cell:getGridSquare(math.floor(r.x),math.floor(r.y),math.floor(r.z))
        -- Shared model seam for counting writes and injecting native move failures.
        CVPWorldNative.move(b,r.x,r.y,r.z,sq,pass,p,skipInvalidation)
        CVPWorldNative.setAngle(b,r.angle)
    end
end
function CVPWorldNative.placeClientPose(b,x,y,z,angle)
    local sq=getCell():getGridSquare(math.floor(x),math.floor(y),math.floor(z))
    if not sq or not present(b) or b:isBeingGrappled()
        or b:getModData().CorpseTowingVehicleToken~=nil then return false end
    CVPWorldNative.move(b,x,y,z,sq)
    CVPWorldNative.setAngle(b,angle)
    return true
end
