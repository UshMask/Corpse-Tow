-- One authority transaction at a time. Only immutable native save snapshots leave the game thread.
local Jobs={}
local active
function Jobs.call(name,...)
    local native=CVPEquipmentPersistence
    if not active or coroutine.running()~=active.thread then return pcall(native[name],...) end
    local fn=native[name..'Async'];if not fn then return false,'asynchronous persistence unavailable' end
    local ok,ticket=pcall(fn,...);if not ok then return false,tostring(ticket) end
    -- Java exposure can log an exception and return nil despite a successful pcall.
    if ticket==nil then return false,'equipment backend unavailable' end
    if name=='write' then active.committed=true end
    while true do
        local checked,state=pcall(native.poll,ticket)
        if not checked then return false,tostring(state) end
        if state~=0 and state~=1 then return false,'equipment checkpoint not acknowledged' end
        if state==1 then
            if active.cancelled and not active.committed then return false,active.cancelled end
            local done,result=pcall(native.result,ticket)
            if done and result==nil then return false,'equipment checkpoint not acknowledged' end
            return done,result
        end
        -- Yield OUTSIDE pcall: Kahlua cannot suspend a protected call.
        coroutine.yield()
    end
end
function Jobs.new(run,callback,valid)
    local job={callback=callback,valid=valid}
    job.thread=coroutine.create(run);return job
end
function Jobs.advance(job)
    if job.done then return true end
    if not job.committed and job.valid then
        local why=job.valid()
        if why then
            if not job.started then job.done=true;job.callback(false,nil,why);return true end
            job.cancelled=why
        end
    end
    job.started=true;active=job
    local resumed,ok,value,reason=coroutine.resume(job.thread)
    active=nil
    if not resumed or coroutine.status(job.thread)=='dead' then
        job.done=true
        if not resumed then job.callback(false,nil,tostring(ok)) else job.callback(ok,value,reason) end
    end
    return job.done==true
end
return Jobs
