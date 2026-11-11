-- Straight rope segments on one floor. Cache native tile/edge queries for one
-- authority tick only: opening a door is observed on the very next tick.
local O={blocked='IGUI_CVP_LinkBlocked',unloaded='IGUI_CVP_LinkPathUnloaded'}
function O.new(solver)
    if solver==nil then solver=CVPSolverNative and not CVPSolverUseLua and CVPSolverNative or false end
    return {tiles={},cell=getCell(),native=solver and solver.begin() or nil}
end
local function tile(c,x,y,z)
    local floor=c.tiles[z];if not floor then floor={};c.tiles[z]=floor end
    local column=floor[x];if not column then column={};floor[x]=column end
    local row=column[y]
    if not row then
        local q=c.cell:getGridSquare(x,y,z)
        row={q=q,x=x,y=y,edges={},why=not q and O.unloaded or nil}
        if q and (q:isSolid() or q:isSolidTrans() or not q:TreatAsSolidFloor()) then row.why=O.blocked end
        column[y]=row
    end
    return row
end
-- Body footprints share tile reads with path checks, but trees and directed
-- collision queries retain their own semantics. Never retain this cache across ticks.
function O.bodyTile(c,x,y,z)
    local row=tile(c,x,y,z)
    if row.clear==nil then row.clear=not row.why and not (row.q.HasTree and row.q:HasTree()) end
    return row
end
local function blockedEdge(c,a,b)
    local blocked=a.edges[b]
    if blocked==nil then blocked=a.q:isBlockedTo(b.q);a.edges[b]=blocked end
    return blocked
end
function O.bodyEdge(c,a,b)
    if not a.clear or not b.clear then return false end
    if a.q==b.q then return true end
    return not blockedEdge(c,a,b)
end
-- Cache each tile's required outgoing neighbourhood within this tick. Overlapping
-- swept bounds reuse the exact directed checks, including boundary-only subsets.
function O.bodyRegion(c,minX,maxX,minY,maxY,z)
    for x=minX,maxX do for y=minY,maxY do
        local a=O.bodyTile(c,x,y,z);if not a.clear then return false end
        local left,right=x>minX and -1 or 0,x<maxX and 1 or 0
        local up,down=y>minY and -1 or 0,y<maxY and 1 or 0
        local mask=left+1+right*2+(up+1)*4+down*8
        local regions=a.regions;if not regions then regions={};a.regions=regions end
        if regions[mask]==nil then
            local clear=true
            for dx=left,right do for dy=up,down do
                if (dx~=0 or dy~=0) and not O.bodyEdge(c,a,O.bodyTile(c,x+dx,y+dy,z)) then clear=false end
            end end
            regions[mask]=clear
        end
        if not regions[mask] then return false end
    end end
    return true
end
local function edge(c,x,y,nx,ny,z)
    local a=tile(c,x,y,z);local b=tile(c,nx,ny,z)
    if a.why or b.why then return a.why or b.why end
    local result=blockedEdge(c,a,b) or blockedEdge(c,b,a)
    return result and O.blocked or nil
end
-- A clear rectangle proves every supercover route between its endpoint tiles.
-- Only cardinal edges are relevant to the rope tracer; trees retain the existing
-- rope semantics. A failed proof is never a collision result: trace exactly below.
local function openRectangle(c,a,b,z)
    local width,height=math.abs(a.x-b.x)+1,math.abs(a.y-b.y)+1
    if width*height>64 then return false end
    local paths=a.paths;if not paths then paths={};a.paths=paths end
    if paths[b]~=nil then return paths[b] end
    local minX,maxX=math.min(a.x,b.x),math.max(a.x,b.x)
    local minY,maxY=math.min(a.y,b.y),math.max(a.y,b.y)
    local clear=true
    for x=minX,maxX do for y=minY,maxY do
        local row=tile(c,x,y,z)
        if row.why then clear=false;break end
        if x<maxX then
            if row.right==nil then
                local nextRow=tile(c,x+1,y,z)
                row.right=not nextRow.why and not blockedEdge(c,row,nextRow) and not blockedEdge(c,nextRow,row)
            end
            if not row.right then clear=false;break end
        end
        if y<maxY then
            if row.down==nil then
                local nextRow=tile(c,x,y+1,z)
                row.down=not nextRow.why and not blockedEdge(c,row,nextRow) and not blockedEdge(c,nextRow,row)
            end
            if not row.down then clear=false;break end
        end
    end;if not clear then break end end
    paths[b]=clear
    return clear
end
function O.check(c,a,b,maxDistance)
    if c.native then return CVPSolverNative.check(c.native,a.x,a.y,a.z,b.x,b.y,b.z,maxDistance or 0/0) end
    if math.floor(a.z)~=math.floor(b.z) then return O.blocked end
    local x,y,z=math.floor(a.x),math.floor(a.y),math.floor(a.z)
    local tx,ty=math.floor(b.x),math.floor(b.y)
    local start=tile(c,x,y,z);if start.why then return start.why end
    -- Only the solver supplies a larger budget, derived from its saved span.
    -- Other callers retain the short-link guard against arbitrary world scans.
    local budget=maxDistance and math.max(96,math.ceil(maxDistance*math.sqrt(2))+2) or 96
    if math.abs(tx-x)+math.abs(ty-y)>budget then return O.blocked end
    if openRectangle(c,start,tile(c,tx,ty,z),z) then return end
    local dx,dy=b.x-a.x,b.y-a.y
    local sx,sy=dx<0 and -1 or 1,dy<0 and -1 or 1
    local ix,iy=dx==0 and math.huge or 1/math.abs(dx),dy==0 and math.huge or 1/math.abs(dy)
    local mx=dx==0 and math.huge or (dx<0 and a.x-x or x+1-a.x)*ix
    local my=dy==0 and math.huge or (dy<0 and a.y-y or y+1-a.y)*iy
    for _=1,budget+1 do
        if x==tx and y==ty then return end
        local why
        if math.abs(mx-my)<1e-9 then
            -- Supercover at a corner: neither of the two wall routes may be cut.
            why=edge(c,x,y,x+sx,y,z) or edge(c,x,y,x,y+sy,z)
                or edge(c,x+sx,y,x+sx,y+sy,z) or edge(c,x,y+sy,x+sx,y+sy,z)
            x=x+sx;y=y+sy;mx=mx+ix;my=my+iy
        elseif mx<my then why=edge(c,x,y,x+sx,y,z);x=x+sx;mx=mx+ix
        else why=edge(c,x,y,x,y+sy,z);y=y+sy;my=my+iy end
        if why then return why end
    end
    return O.blocked
end
return O
