import unittest
from test_link_runtime import environment
from test_clothing_wear import setup


def settings(l):
    l.execute('''
        Settings=require 'CVP_Settings';nativeRules={BodySpread=false,BodySpreadWidth=2,BodySpreadStrength=2,BloodTrails=true,CosmeticWear=true,
            ClothingWear=true,BodyWear=false,BodyWearRate=2,HorseTowing=true,VehicleDrag=true,ClothingWearRate=2,BloodTrailDensity=2,
            Enabled=true,AllowPlayerCorpses=true,AllowDetachOthers=true,MaxBodiesPerChain=32}
        function getSandboxOptions() return {
            getOptionByName=function(_,name) return nativeRules[name:sub(16)]~=nil end,
            set=function(_,name,value) nativeRules[name:sub(16)]=value end,
            toLua=function() for k,v in pairs(nativeRules) do SandboxVars.CorpseProxyLab[k]=v end end} end
        package.preload['ISUI/ISContextMenu']=function() end
        function getMouseX() return 1 end;function getMouseY() return 2 end
        player.getPlayerNum=function() return 0 end
        local function newMenu()
            return {children={},addOption=function(self,label,target,fn)
                local opt={label=label,fn=fn};menuRows[#menuRows+1]=opt;self.children[#self.children+1]=opt;return opt end,
                addSubMenu=function(_,opt,sub) opt.subMenu=sub end,
                setOptionChecked=function(_,opt,checked) opt.checked=checked end}
        end
        ISContextMenu={get=function() menuRows={};return newMenu() end,getNew=newMenu}
        ISWorldObjectContextMenu={addToolTip=function() return {} end}
        package.preload.CVP_SettingsMenu=assert(loadstring(settingsMenuSource))
        SettingsMenu=require 'CVP_SettingsMenu'
    ''')


class LiveSettingsTests(unittest.TestCase):
    def test_limit_dialog_validates_and_server_cannot_change_limits(self):
        l=self.env();l.execute('''
            package.preload['ISUI/ISTextBox']=function() end
            ISTextBox={new=function(_,x,y,w,h,label,value,target,click)
                dialog={entry={getText=function() return limitText end},click=click,
                    initialise=function() end,addToUIManager=function() end,setOnlyNumbers=function() end,
                    setValidateFunction=function(self,target,fn) self.validate=fn end,setValidateTooltipText=function() end}
                return dialog
            end}
            SettingsMenu.open()
            for _,opt in ipairs(menuRows) do if opt.label==getText('Sandbox_CorpseProxyLab_MaxBodiesPerChain')..': 32' then opt.fn() end end
            assert(dialog and dialog.validate(nil,'0') and dialog.validate(nil,'100000'))
            for _,value in ipairs({'-1','1.5','100001','abc',''}) do assert(not dialog.validate(nil,value)) end
            limitText='12';dialog.click(nil,{internal='CANCEL',parent=dialog});assert(nativeRules.MaxBodiesPerChain==32)
            dialog.click(nil,{internal='OK',parent=dialog});assert(nativeRules.MaxBodiesPerChain==12)
            assert(Settings.set('MaxBodiesPerChain',0) and nativeRules.MaxBodiesPerChain==0)
            assert(not Settings.set('MaxBodiesPerChain',-1) and nativeRules.MaxBodiesPerChain==0)
            isClient=function() return true end;SettingsMenu.open()
            for _,opt in ipairs(menuRows) do assert(not opt.fn) end
            assert(not Settings.set('Enabled',false) and not Settings.set('MaxBodiesPerChain',32))
        ''')

    def env(self):
        from pathlib import Path
        import json
        l=environment()
        texts={}
        for name in ('IG_UI','Sandbox'):
            texts.update(json.loads(Path(f'CorpseProxyLab/42/media/lua/shared/Translate/EN/{name}.json').read_text(encoding='utf-8-sig')))
        l.globals().getText=lambda key: texts[key]
        l.globals().settingsMenuSource=Path('CorpseProxyLab/42/media/lua/client/CVP_SettingsMenu.lua').read_text(encoding='utf-8-sig')
        settings(l)
        return l

    def test_sp_menu_changes_native_and_live_values_not_other_rules(self):
        l=self.env()
        l.execute('''
            SettingsMenu.open()
            local function row(key)
                for _,opt in ipairs(menuRows) do if opt.label==key then return opt end end
                error('missing setting '..key)
            end
            row(getText('Sandbox_CorpseProxyLab_BloodTrails')..': '..getText('IGUI_CVP_SettingOn')).fn();assert(nativeRules.BloodTrails==false and SandboxVars.CorpseProxyLab.BloodTrails==false)
            row(getText('Sandbox_CorpseProxyLab_ClothingWearRate_option3')).fn();assert(nativeRules.ClothingWearRate==3 and SandboxVars.CorpseProxyLab.ClothingWearRate==3)
            assert(nativeRules.HorseTowing and Settings.set('AllowDetachOthers',true))
            assert(not Settings.set('ClothingWearRate',4) and not Settings.set('BloodTrails',1))
            -- Opening again reads this world's current values, not client preferences.
            SettingsMenu.open();assert(row(getText('Sandbox_CorpseProxyLab_ClothingWearRate_option3')).checked)
            assert(Settings.set('BodyWear',true) and SandboxVars.CorpseProxyLab.BodyWear)
            assert(Settings.set('BodyWearRate',1) and SandboxVars.CorpseProxyLab.BodyWearRate==1)
            local disabled=row(getText('Sandbox_CorpseProxyLab_BloodTrailDensity')..': '..getText('Sandbox_CorpseProxyLab_BloodTrailDensity_option2'))
            assert(disabled.notAvailable and not disabled.fn and not disabled.subMenu)
            assert(Settings.set('BloodTrails',true));SettingsMenu.open()
            row(getText('Sandbox_CorpseProxyLab_BloodTrailDensity_option1')).fn()
            assert(nativeRules.BloodTrailDensity==1 and SandboxVars.CorpseProxyLab.BloodTrailDensity==1)
            assert(not Settings.set('BloodTrailDensity',0))
        ''')

    def test_mp_and_title_screen_cannot_mutate_world(self):
        l=self.env()
        l.execute('''
            isClient=function() return true end
            SettingsMenu.open();for _,opt in ipairs(menuRows) do assert(not opt.fn) end
            assert(not Settings.set('BloodTrails',false) and nativeRules.BloodTrails)
            assert(not Settings.set('BloodTrailDensity',3) and nativeRules.BloodTrailDensity==2)
            isClient=function() return false end;isServer=function() return true end
            assert(not Settings.set('BloodTrails',false))
            isServer=function() return false end;getPlayer=function() return nil end
            SettingsMenu.open();assert(#menuRows==1 and not menuRows[1].fn)
            assert(not Settings.set('ClothingWearRate',1))
        ''')

    def test_body_spread_settings_are_live_in_sp_and_read_only_in_mp(self):
        l=self.env();l.execute('''
            assert(Settings.set('BodySpread',true))
            assert(Settings.set('BodySpreadWidth',3) and Settings.set('BodySpreadStrength',1))
            assert(SandboxVars.CorpseProxyLab.BodySpread and SandboxVars.CorpseProxyLab.BodySpreadWidth==3)
            assert(not Settings.set('BodySpreadStrength',0))
            SettingsMenu.open()
            for _,opt in ipairs(menuRows) do
                if opt.label==getText('Sandbox_CorpseProxyLab_BodySpread')..': '..getText('IGUI_CVP_SettingOn') then opt.fn() end
            end
            assert(not SandboxVars.CorpseProxyLab.BodySpread)
            isClient=function() return true end
            assert(not Settings.set('BodySpread',true))
            assert(not Settings.set('BodySpreadWidth',1))
        ''')

    def test_rates_and_live_toggle_preserve_clothing_contents(self):
        for rate,distance in ((1,40),(2,20),(3,10)):
            l=self.env();setup(l);l.globals().rate=rate;l.globals().distance=distance
            l.execute('''
                assert(Settings.set('ClothingWearRate',rate))
                for i=1,distance-1 do step(1) end;assert(shirt.condition==10)
                step(1);assert(shirt.condition==9);contents()
                assert(Settings.set('ClothingWear',false))
                for i=1,100 do step(4) end;assert(shirt.condition==9);contents()
            ''')


if __name__=='__main__': unittest.main()
