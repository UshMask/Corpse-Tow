require 'ISUI/ISContextMenu'
local S=require 'CVP_Settings'
local M={}
function M.open()
    local player=getPlayer()
    local menu=ISContextMenu.get(player and player:getPlayerNum() or 0,getMouseX(),getMouseY())
    if not player then
        menu:addOption(getText('IGUI_CVP_SettingsNeedWorld'),nil,nil);return
    end
    local editable=not isClient() and not isServer()
    menu:addOption(getText(editable and 'IGUI_CVP_SettingsLive' or 'IGUI_CVP_SettingsServer'),nil,nil)
    local rules=SandboxVars.CorpseProxyLab or {}
    local function tip(option,key)
        local t=ISWorldObjectContextMenu.addToolTip()
        t.description=getText('Sandbox_CorpseProxyLab_'..key..'_tooltip');option.toolTip=t
    end
    local function boolean(parent,key)
        local enabled=key=='BodyWear' and rules[key]==true or key~='BodyWear' and rules[key]~=false
        local label=getText('Sandbox_CorpseProxyLab_'..key)..': '..getText(enabled and 'IGUI_CVP_SettingOn' or 'IGUI_CVP_SettingOff')
        local option=parent:addOption(label,nil,editable and function() S.set(key,not enabled);M.open() end or nil)
        tip(option,key)
    end
    local function submenu(parent,label)
        local option=parent:addOption(label,nil,nil)
        local sub=ISContextMenu:getNew(parent);parent:addSubMenu(option,sub)
        return sub,option
    end
    local function rate(parent,key,enabledKey)
        local current=rules[key] or 2
        local label=getText('Sandbox_CorpseProxyLab_'..key)..': '..getText('Sandbox_CorpseProxyLab_'..key..'_option'..current)
        local enabled=enabledKey=='BodyWear' and rules[enabledKey]==true or enabledKey~='BodyWear' and rules[enabledKey]~=false
        if not editable or not enabled then
            local option=parent:addOption(label,nil,nil);option.notAvailable=not enabled;tip(option,key)
            if not enabled then option.toolTip.description=getText('IGUI_CVP_EnableEffectFirst')..' <LINE> '..option.toolTip.description end
            return
        end
        local sub,option=submenu(parent,label);tip(option,key)
        for value=1,3 do
            local opt=sub:addOption(getText('Sandbox_CorpseProxyLab_'..key..'_option'..value),nil,function() S.set(key,value);M.open() end)
            sub:setOptionChecked(opt,value==current)
        end
    end
    local towing=submenu(menu,getText('IGUI_CVP_TowingRules'))
    for _,key in ipairs({'Enabled','VehicleDrag','HorseTowing'}) do boolean(towing,key) end
    boolean(towing,'BodySpread')
    rate(towing,'BodySpreadWidth','BodySpread');rate(towing,'BodySpreadStrength','BodySpread')
    local limits=submenu(menu,getText('IGUI_CVP_LimitRules'))
    for _,key in ipairs({'AllowPlayerCorpses','AllowDetachOthers'}) do boolean(limits,key) end
    local limit=rules.MaxBodiesPerChain or 32
    local option=limits:addOption(getText('Sandbox_CorpseProxyLab_MaxBodiesPerChain')..': '..tostring(limit),nil,editable and function()
        require 'ISUI/ISTextBox'
        local dialog=ISTextBox:new(0,0,320,180,getText('IGUI_CVP_ChainLimitPrompt'),tostring(limit),nil,function(_,button)
            if button.internal=='OK' then S.set('MaxBodiesPerChain',tonumber(button.parent.entry:getText()));M.open() end
        end,player:getPlayerNum())
        dialog:initialise();dialog:addToUIManager();dialog:setOnlyNumbers(true)
        dialog:setValidateFunction(nil,function(_,text) return S.validLimit(tonumber(text)) end)
        dialog:setValidateTooltipText(getText('IGUI_CVP_ChainLimitPrompt'))
    end or nil);tip(option,'MaxBodiesPerChain')
    local effects=submenu(menu,getText('IGUI_CVP_TraceRules'))
    boolean(effects,'BloodTrails');rate(effects,'BloodTrailDensity','BloodTrails');boolean(effects,'CosmeticWear')
    local wear=submenu(menu,getText('IGUI_CVP_WearRules'))
    boolean(wear,'ClothingWear');rate(wear,'ClothingWearRate','ClothingWear')
    boolean(wear,'CarcassWear');rate(wear,'CarcassWearRate','CarcassWear')
    boolean(wear,'BodyWear');rate(wear,'BodyWearRate','BodyWear')
end
return M
