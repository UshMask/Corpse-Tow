-- Retired controller menu actions, used only by the pre-graph test fixture.
local M=require 'CVP_Menu'
local begin=M.begin
function M.begin(p,context,objects,focused,available)
    local scope=begin(p,context,objects,focused,available)
    scope.vehicles={}
    if not focused and not scope.vehicle and not scope.bodyClick then
        local best=36
        local cars=getCell():getVehicles():iterator()
        while cars:hasNext() do local car=cars:next()
            local d=(car:getX()-p:getX())^2+(car:getY()-p:getY())^2
            if car:getSquare() and math.floor(car:getZ())==math.floor(p:getZ()) and d<=best then scope.primary=car;best=d end
        end
    end
    function scope:vehicleMenu(car)
        if self.vehicle or self.primary==car then return self.root end
        if not self.vehicles[car] then
            local name=car:getScript():getName()
            name=(getTextOrNull and getTextOrNull('IGUI_VehicleName'..name)) or name
            self.vehicles[car]=M.sub(self.root,name)
        end
        return self.vehicles[car]
    end
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
