-- Retired controller menu actions, used only by the pre-graph test fixture.
local M=require 'CVP_Menu'
local begin=M.begin
function M.begin(p,context,objects,focused,available)
    local scope=begin(p,context,objects,focused,available)
    function scope:materialMenu()
        if focused or self.materialOption then return end
        self.materialOption=M.sub(self.root,getText('IGUI_CVP_MaterialMenu',getText(M.labels[self.material])))
        for _,t in ipairs(M.types) do
            local opt=self.materialOption:addOption(getText(M.labels[t]),nil,function() p:getModData().CVPMaterial=t end)
            M.reason(opt,not self.available[t] and getText('IGUI_CVP_NeedGear') or nil)
        end
    end
    scope.detach={}
    function scope:detachMenu(car)
        if not self.detach[car] then self.detach[car]=M.sub(self:vehicleMenu(car),getText('IGUI_CVP_DetachMenu')) end
        return self.detach[car]
    end
    return scope
end
