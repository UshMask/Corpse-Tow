"""Context isolation and real action callbacks for nested SP/MP menus."""
import unittest
from test_stock_visuals import single_player
from test_multiplayer import vm

class ContextMenus(unittest.TestCase):
    def runtime(self, mp=False):
        lua=vm(False) if mp else single_player()
        lua.execute('''
            function getMouseX() return 0 end
            function getMouseY() return 0 end
            function findMenu(node,label)
                for _,o in ipairs(node.children or {}) do
                    if o.label==label then return o end
                end
            end
            function chooseBatch(mode,material)
                local types={IGUI_CVP_Rope='Base.Rope',IGUI_CVP_Chain='Base.HeavyChain',IGUI_CVP_HookChain='Base.HeavyChain_Hook'}
                player:getModData().CVPMaterial=types[material]
                pickedVehicle=car;menu()
                local root=context
                local key='IGUI_CVP_QuickNearby'
                if mode=='IGUI_CVP_SequenceMenu' then root=assert(findMenu(context,getText('IGUI_CVP_OtherWays'))).subMenu;key='IGUI_CVP_QuickSequence' end
                for _,o in ipairs(root.children) do
                    if o.label:find(getText(key,getText(material),''),1,true) then assert(not o.notAvailable);o.run();return end
                end
                -- Match the stable prefix before the numeric count.
                local prefix=assert(getText(key,getText(material),'__COUNT__'):match('^(.-)__COUNT__'))
                for _,o in ipairs(root.children) do if o.label:find(prefix,1,true)==1 then assert(not o.notAvailable);o.run();return end end
                error('material missing')
            end
        ''')
        return lua

    def test_native_corpse_and_vehicle_pickers_use_their_own_zoom_coordinates(self):
        for mp in (False,True):
            for zoom in (0.5,0.9,1.5):
                with self.subTest(mp=mp,zoom=zoom):
                    l=self.runtime(mp)
                    l.globals().cursorZoom=zoom
                    l.execute('''
                        local rawX,rawY=640,360
                        local targetX,targetY=rawX*cursorZoom,rawY*cursorZoom
                        function getMouseX() return rawX end
                        function getMouseY() return rawY end
                        function getMouseXScaled() return rawX*cursorZoom end
                        function getMouseYScaled() return rawY*cursorZoom end
                        local corpseVisible=true
                        IsoObjectPicker.Instance.PickCorpse=function(_,x,y)
                            -- B42 FBO and legacy corpse picking apply zoom internally.
                            if corpseVisible and math.abs(x*cursorZoom-targetX)<1
                                and math.abs(y*cursorZoom-targetY)<1 then return body2 end
                        end
                        local vehiclePicks=0
                        IsoObjectPicker.Instance.PickVehicle=function(_,x,y)
                            vehiclePicks=vehiclePicks+1
                            -- Vehicle picking converts these coordinates straight to world space.
                            if math.abs(x-targetX)<1 and math.abs(y-targetY)<1 then return car end
                        end
                        local ground={kind='IsoObject',getSquare=function() return body:getSquare() end}
                        callbacks.OnFillWorldObjectContextMenu(0,context,{ground},false)
                        assert(#options==1 and options[1].body==body2,'zoomed native corpse hit was lost')
                        assert(vehiclePicks==0,'corpse hit must retain priority')
                        corpseVisible=false;options={};context.children={}
                        callbacks.OnFillWorldObjectContextMenu(0,context,{ground},false)
                        assert(vehiclePicks==1)
                        assert(not findMenu(context,getText('IGUI_CVP_TowingMenu')),'zoomed vehicle hit was lost')
                        assert(findMenu(context,getText('IGUI_CVP_SelectedBodyMenu')))
                    ''')

    def test_body_click_excludes_vehicle_batches_in_both_modes(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                pickedVehicle=nil;menu(body)
                assert(not findMenu(context,getText('IGUI_CVP_NearbyMenu')))
                assert(not findMenu(context,getText('IGUI_CVP_TowingMenu')))
                assert(#context.children<=2)
                assert(#options==1 and options[1].body==body and not options[1].subMenu)
            ''')

    def test_vehicle_offers_both_modes_and_materials(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                pickedVehicle=car;menu()
                assert(#context.children<=4)
                local n=assert(findMenu(context,getText('IGUI_CVP_OtherWays'))).subMenu
                assert(#n.children==3)
                assert(context.children[1].run and not context.children[1].subMenu)
                assert(findMenu(context,getText('IGUI_CVP_SelectedBodyMenu')))
            ''')

    def test_rope_batch_does_not_consume_chain(self):
        l=self.runtime()
        l.execute('''
            deferAction=false
            chooseBatch('IGUI_CVP_SeparateMenu','IGUI_CVP_Rope')
            assert(#CVPTest.links()==1 and rope.owner~=storage and chain.owner==storage)
        ''')

    def test_chain_batch_does_not_consume_rope(self):
        l=self.runtime()
        l.execute('''
            deferAction=false
            chooseBatch('IGUI_CVP_SeparateMenu','IGUI_CVP_Chain')
            assert(#CVPTest.links()==1 and chain.owner~=storage and rope.owner==storage)
        ''')

    def test_sequence_uses_only_selected_material(self):
        l=self.runtime()
        l.execute('''
            secondRope=item('Base.Rope');storage:AddItem(secondRope)
            deferAction=false
            chooseBatch('IGUI_CVP_SequenceMenu','IGUI_CVP_Rope')
            local r=CVPTest.links();assert(#r==2 and r[2].parent==r[1])
            assert(chain.owner==storage)
        ''')

    def test_mp_material_reaches_request(self):
        l=self.runtime(True)
        l.execute('''
            chooseBatch('IGUI_CVP_SeparateMenu','IGUI_CVP_Chain')
            assert(#clientPackets==1 and clientPackets[1].args.gear==chain.id)
            assert(rope.owner==storage)
        ''')

    def test_unavailable_reasons_are_tooltips(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                storage:Remove(rope);storage:Remove(chain);menu(body)
                assert(#options>0)
                for _,o in ipairs(options) do
                    assert(o.notAvailable and o.toolTip and #o.toolTip.description>0)
                    assert(not o.label:find(o.toolTip.description,1,true))
                end
            ''')

    def test_clicked_vehicle_excludes_other_vehicle_targets(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute(''' 
                local other={};for k,v in pairs(car) do other[k]=v end
                other.x=3;other.getId=function() return 8 end
                other.getScript=function() return {getName=function() return 'OtherCar' end} end
                cell.getVehicles=function() return {iterator=function()
                    local rows={car,other};local i=0
                    return {hasNext=function() return i<2 end,next=function() i=i+1;return rows[i] end}
                end} end
                pickedVehicle=car;menu()
                for _,o in ipairs(options) do assert(not o.label:find('OtherCar',1,true)) end
                local selected=assert(findMenu(context,getText('IGUI_CVP_SelectedBodyMenu'))).subMenu
                selected.children[1].subMenu.children[1].run()
                if CVPMPClient then assert(clientPackets[1].args.vehicle==7)
                else assert(queued.vehicle==nil or queued.vehicle==car) end
            ''')

    def test_material_selection_persists_and_changes_direct_action(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                menu(body)
                local settings=assert(findMenu(context,getText('IGUI_CVP_MaterialMenu',getText('IGUI_CVP_Rope')))).subMenu
                findMenu(settings,getText('IGUI_CVP_Chain')).run()
                assert(player:getModData().CVPMaterial=='Base.HeavyChain')
                menu(body)
                assert(context.children[1].label:find(getText('IGUI_CVP_Chain'),1,true))
                context.children[1].run()
                if CVPMPClient then assert(clientPackets[1].args.gear==chain.id)
                else assert(queued.item==nil or queued.item==chain) end
                package.loaded.CVP_Menu=nil
                assert(require('CVP_Menu').material(player)=='Base.HeavyChain')
            ''')

    def test_missing_material_falls_back_without_overwriting_preference(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                player:getModData().CVPMaterial='Base.HeavyChain'
                storage:Remove(chain);menu(body)
                assert(context.children[1].label:find(getText('IGUI_CVP_Rope'),1,true))
                assert(player:getModData().CVPMaterial=='Base.HeavyChain')
                storage:AddItem(chain);menu(body)
                assert(context.children[1].label:find(getText('IGUI_CVP_Chain'),1,true))
            ''')

    def test_equipped_material_is_not_silently_consumed(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                player:getModData().CVPMaterial='Base.Rope'
                player.getPrimaryHandItem=function() return rope end
                menu(body)
                assert(context.children[1].label:find(getText('IGUI_CVP_Chain'),1,true))
                assert(not context.children[1].notAvailable)
            ''')

    def test_body_action_walks_from_nonadjacent_square_and_path_failure_keeps_items(self):
        for mp in (False,True):
            for blocked in (False,True):
                with self.subTest(mp=mp,blocked=blocked):
                    l=self.runtime(mp)
                    l.globals().noPath=blocked
                    l.execute('''
                        player.x=3;car.x=6;deferPath=true;deferAction=true
                        -- Native canReachTo checks immediate interaction, not a walkable route.
                        for x=-1,8 do for y=-1,1 do local q=gridSquare(x,y,0)
                            q.canReachTo=function(s,other)
                                return math.abs(s.x-other.x)<=1 and math.abs(s.y-other.y)<=1 and s.z==other.z
                            end
                        end end
                        assert(not player:getSquare():canReachTo(body:getSquare()))
                        menu(body);local option=context.children[1]
                        assert(not option.notAvailable,'nonadjacent corpse must allow an approach')
                        option.run();assert(queued.isPath)
                        queued:start();queued:perform()
                        if not noPath then
                            assert(queued.endpoint=='body')
                            for i=1,3 do queued:start();queued:perform() end
                        end
                        if CVPMPClient then
                            assert(#clientPackets==(noPath and 0 or 1))
                            assert(rope.owner==storage and not body.md.CVPTether)
                        else
                            assert(#CVPTest.links()==(noPath and 0 or 1))
                            assert(rope.owner==(noPath and storage or CVPEquipmentRuntime.container))
                        end
                    ''')

    def test_ground_fallback_has_one_root(self):
        for mp in (False,True):
            l=self.runtime(mp)
            l.execute('''
                pickedVehicle=nil;options={};context.children={}
                callbacks.OnFillWorldObjectContextMenu(0,context,{},false)
                assert(#context.children==1 and context.children[1].label==getText('IGUI_CVP_TowingMenu'))
            ''')

if __name__=='__main__': unittest.main()
