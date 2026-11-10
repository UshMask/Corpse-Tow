local Compat={}
if CVPViewpointLoader then
    local ok,why=pcall(CVPViewpointLoader.install)
    if not ok then print('[CVP] Viewpoint integration unavailable: '..tostring(why)) end
end
function Compat.track(body)
    if CVPViewpoint then CVPViewpoint.track(body) end
end
function Compat.untrack(body)
    if CVPViewpoint then CVPViewpoint.untrack(body) end
end
function Compat.clear()
    if CVPViewpoint then CVPViewpoint.clear() end
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
