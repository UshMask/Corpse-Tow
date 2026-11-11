import unittest
import test_context_menus

class CursorTests(unittest.TestCase):
    def test_native_corpse_hit_beats_vehicle_and_other_tile_body(self):
        for mp in (False,True):
            lua=test_context_menus.ContextMenus().runtime(mp)
            lua.execute('''
                pickedVehicle=car
                IsoObjectPicker.Instance.PickCorpse=function() return body2 end
                menu(body)
                assert(not menuBranch(context,getText('IGUI_CVP_SelectedBodyMenu')))
                assert(#options==1 and options[1].body==body2)
            ''')

    def test_ground_tile_does_not_select_all_corpses_on_it(self):
        for mp in (False,True):
            lua=test_context_menus.ContextMenus().runtime(mp)
            lua.execute('''
                IsoObjectPicker.Instance.PickCorpse=function() return nil end
                pickedVehicle=nil;context.children={};options={}
                local ground={kind='IsoObject',getSquare=function() return body:getSquare() end}
                callbacks.OnFillWorldObjectContextMenu(0,context,{ground},false)
                assert(#context.children==1 and context.children[1].label==getText('IGUI_CVP_TowingMenu'))
            ''')

    def test_batch_highlight_is_limited_by_selected_equipment_and_clears(self):
        for mp in (False,True):
            lua=test_context_menus.ContextMenus().runtime(mp)
            lua.execute('''
                local calls={}
                ISWorldObjectContextMenu.initWorldItemHighlightOption=function(o,b)
                    o.body=b;o.onHighlightParams={b}
                    o.onHighlight=function(_,_,on,target) calls[#calls+1]={target,on} end
                end
                pickedVehicle=car;menu()
                local option=assert(menuBranch(context,getText('IGUI_CVP_QuickNearby',getText('IGUI_CVP_Rope'),'1')))
                option.onHighlight(option,context,true)
                option.onHighlight(option,context,false)
                assert(#calls==2 and calls[1][1]==calls[2][1] and calls[1][2] and not calls[2][2])
                assert(option.toolTip.description==getText('IGUI_CVP_HintVehicleFirst','1'))
            ''')

    def test_all_batch_variants_preview_and_clear(self):
        for mp in (False,True):
            lua=test_context_menus.ContextMenus().runtime(mp)
            lua.execute("""
                ISWorldObjectContextMenu.initWorldItemHighlightOption=function(o,b)
                    o.body=b;o.onHighlightParams={b}
                    o.onHighlight=function(_,_,on,target) target.preview=on end
                end
                pickedVehicle=car;menu()
                local more=assert(menuBranch(context,getText('IGUI_CVP_OtherWays'))).subMenu
                for i,opt in ipairs(more.children) do
                    opt.onHighlight(opt,context,true)
                    local n=(body.preview and 1 or 0)+(body2.preview and 1 or 0)
                    assert(n==(i==1 and 1 or 2),'wrong batch preview')
                    opt.onHighlight(opt,context,false)
                    assert(not body.preview and not body2.preview)
                end
                local batch=require 'CVP_Batch'
                local picked=batch.preview({body,body2},1,car,true)
                assert(#picked==1)
                local o={notAvailable=true,toolTip={description='reason'}}
                require('CVP_Menu').hint(o,'hint');assert(o.toolTip.description=='reason')
            """)

    def test_detach_all_highlights_and_clears_every_attached_body(self):
        lua=test_context_menus.ContextMenus().runtime()
        lua.execute("""
            CVPTest.attach(player,body,car,rope)
            CVPTest.attach(player,body2,car,chain)
            assert(#CVPTest.links()==2)
            ISWorldObjectContextMenu.initWorldItemHighlightOption=function(o,b)
                o.body=b;o.onHighlightParams={b}
                o.onHighlight=function(_,_,on,target) target.preview=on end
            end
            pickedVehicle=car;menu()
            local opt=assert(menuBranch(context,getText('IGUI_CVP_DetachAllMenu','2')))
            opt.onHighlight(opt,context,true)
            assert(body.preview and body2.preview)
            opt.onHighlight(opt,context,false)
            assert(not body.preview and not body2.preview)
        """)

    def test_mp_bulk_preview_respects_vehicle_and_ownership(self):
        lua=test_context_menus.ContextMenus().runtime(True)
        lua.execute("""
            CVPMPClient.bulkDetach=true
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            CVPMPClient.links[body.netID]={body=body,target={vehicle=7,owner='owner'}}
            CVPMPClient.links[body2.netID]={body=body2,target={vehicle=7,owner='friend'}}
            ISWorldObjectContextMenu.initWorldItemHighlightOption=function(o,b)
                o.body=b;o.onHighlightParams={b}
                o.onHighlight=function(_,_,on,target) target.preview=on end
            end
            pickedVehicle=car;menu()
            local opt=assert(menuBranch(context,getText('IGUI_CVP_DetachAllMenu','2')))
            opt.onHighlight(opt,context,true)
            assert(body.preview and not body2.preview)
            opt.onHighlight(opt,context,false)
            assert(not body.preview and not body2.preview)
        """)

if __name__=='__main__': unittest.main()
