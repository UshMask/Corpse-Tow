-- Persistent connection identity and endpoint descriptors, independent of native
-- corpse network IDs and SP menu numbers. Vehicle -> body and linear body -> body links.
local Connection={}
local function key(value) return type(value)=='string' and #value>0 and #value<=256 end

function Connection.valid(c,vehicle,point)
    return type(c)=='table' and c.version==1 and key(c.id)
        and type(c.a)=='table' and key(c.a.key)
        and ((c.a.kind=='vehicle' and c.a.point=='hitch' and (vehicle==nil or c.a.key==vehicle))
            or (c.a.kind=='body' and (c.a.point=='feet' or c.a.point=='neck')))
        and type(c.b)=='table' and c.b.kind=='body' and key(c.b.key)
        and (point==nil or c.b.point==point) and (c.b.point=='feet' or c.b.point=='neck')
end

function Connection.matches(expected,current)
    -- Missing identity is accepted only for an older caller/packet.
    return expected==nil or type(current)=='table' and expected.id==current.id
end

function Connection.copy(c)
    if not c then return nil end
    return {version=c.version,id=c.id,
        a={kind=c.a.kind,key=c.a.key,point=c.a.point},
        b={kind=c.b.kind,key=c.b.key,point=c.b.point}}
end

function Connection.bodyMatches(b,c)
    local saved=b:getModData().CVPBodyKey
    return c~=nil and (saved==nil or saved==c.b.key)
end

-- Identity is minted only when a new authoritative connection is created.
function Connection.create(b,vehicle,point)
    local data=b:getModData()
    if not data.CVPBodyKey then data.CVPBodyKey=getRandomUUID() end
    return {version=1,id=getRandomUUID(),
        a={kind='vehicle',key=vehicle,point='hitch'},
        b={kind='body',key=data.CVPBodyKey,point=point or 'feet'}}
end

function Connection.bind(c,b,v)
    assert(Connection.valid(c) and Connection.bodyMatches(b,c),'invalid connection')
    b:getModData().CVPBodyKey=c.b.key
    local live=Connection.copy(c)
    live.a.object=v;live.b.object=b
    return live
end
return Connection
