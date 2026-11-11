-- Silent compatibility interface for existing client and development reload callers.
if CVPAudio then CVPAudio.clear() end
local Audio={}
function Audio.update() end
function Audio.stop() end
function Audio.clear() end
CVPAudio=Audio
return Audio
