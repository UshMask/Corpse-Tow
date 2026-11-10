require 'PZAPI/ModOptions'
local options=PZAPI.ModOptions:getOptions('CorpseProxyLab')
if not options then
    options=PZAPI.ModOptions:create('CorpseProxyLab','Corpse Tow')
    options:addTitle(getText('IGUI_CVP_ControlSettings'))
end
if not options:getOption('PreferredMaterial') then
    local material=options:addComboBox('PreferredMaterial',getText('IGUI_CVP_PreferredMaterial'),getText('IGUI_CVP_PreferredMaterialHint'))
    for _,label in ipairs({'IGUI_CVP_Rope','IGUI_CVP_Chain','IGUI_CVP_HookChain'}) do material:addItem(label) end
end
if not options:getOption('AttachmentPoint') then
    local point=options:addComboBox('AttachmentPoint',getText('IGUI_CVP_PointMenu'),getText('IGUI_CVP_AttachmentPointHint'))
    for _,label in ipairs({'IGUI_CVP_Point_auto','IGUI_CVP_Point_feet','IGUI_CVP_Point_neck'}) do point:addItem(label) end
end
if not options:getOption('ShowRopes') then
    options:addTitle(getText('IGUI_CVP_DisplaySettings'))
    options:addTickBox('ShowRopes',getText('IGUI_CVP_ShowRopes'),true,getText('IGUI_CVP_ShowRopesHint'))
    options:addTickBox('ShowHighlights',getText('IGUI_CVP_ShowHighlights'),true)
end
if not options:getOption('RopeQuality') then
    local quality=options:addComboBox('RopeQuality',getText('IGUI_CVP_RopeQuality'),getText('IGUI_CVP_RopeQualityHint'))
    quality:addItem('IGUI_CVP_QualityNormal');quality:addItem('IGUI_CVP_QualitySimple')
end
if not options:getOption('Notifications') then
    local notices=options:addComboBox('Notifications',getText('IGUI_CVP_Notifications'),getText('IGUI_CVP_NotificationsHint'))
    notices:addItem('IGUI_CVP_NotificationsAll');notices:addItem('IGUI_CVP_NotificationsImportant')
end
if not options:getOption('WorldRules') then
    options:addTitle(getText('IGUI_CVP_RulesSettings'))
    options:addButton('WorldRules',getText('IGUI_CVP_WorldRules'),getText('IGUI_CVP_WorldSettingsHint'),
        function() require('CVP_SettingsMenu').open() end)
end
return options
