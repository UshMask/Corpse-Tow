-- Only server commands carry authoritative world state. No arbitrary Lua or item creation RPC.
local Connection=require 'CVP_Connection'
local P={version=3,module='CVP',interval=100,radius=90,maxParts=60,partBytes=12000}
P.materials={['Base.Rope']=true,['Base.HeavyChain']=true,['Base.HeavyChain_Hook']=true}
function P.finite(n) return type(n)=='number' and n==n and math.abs(n)<10000000 end
function P.integer(n) return type(n)=='number' and n==n and math.abs(n)<=9007199254740991 and n==math.floor(n) end
function P.id(s) return type(s)=='string' and #s<=21 and s:match('^%-?%d+$')~=nil end
function P.distance(a,b) return math.sqrt((a:getX()-b:getX())^2+(a:getY()-b:getY())^2) end
function P.near(p,b,radius)
    return p and not p:isDead() and math.floor(p:getZ())==math.floor(b:getZ()) and P.distance(p,b)<=radius
end
function P.item(inv,id,seen)
    seen=seen or {};if seen[inv] then return nil end;seen[inv]=true
    local rows=inv:getItems()
    for i=0,rows:size()-1 do local item=rows:get(i)
        if item:getID()==id then return item end
        if instanceof(item,'InventoryContainer') then local found=P.item(item:getInventory(),id,seen);if found then return found end end
    end
end
function P.row(s)
    return type(s)=='table' and P.id(s.id) and P.finite(s.x) and P.finite(s.y) and P.finite(s.z)
        and Connection.valid(s.connection,s.vehicleKey,s.point)
        and (not s.active or s.connection.a.kind=='vehicle' or (P.id(s.source) and type(s.parentConnection)=='string'
            and type(s.vehicleKey)=='string' and P.finite(s.sourceX) and P.finite(s.sourceY)
            and P.finite(s.anchorX) and P.finite(s.anchorY)))
        and (s.point==nil or s.point=='feet' or s.point=='neck')
        and P.finite(s.angle) and type(s.active)=='boolean'
        and (not s.active or (P.integer(s.vehicle) and P.finite(s.length) and s.length>=0.1 and s.length<=12
            and P.integer(s.slot) and s.slot>=1 and P.materials[s.gearType] and P.integer(s.gearID)
            and P.finite(s.footX) and P.finite(s.footY)))
end
return P
