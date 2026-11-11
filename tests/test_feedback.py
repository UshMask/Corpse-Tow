"""Progress/cancellation and camera-aware UI: no world mutation on hover."""
import unittest
from test_tie_sequence import setup
from test_stock_visuals import single_player

class FeedbackTests(unittest.TestCase):
    def test_prepared_tether_is_local_and_cancel_removes_it_without_spending_item(self):
        from test_link_actions import scene
        for mp in (False,True):
            l=scene(mp);l.execute("""
                local shown={}
                CVPFreeRopeScene={update=function(id,points) shown[id]=points end,
                    remove=function(id) shown[id]=nil end,vehicle=function() end}
                CVPVisualAttachment={hand=function(p,out) out.x=p:getX();out.y=p:getY();out.z=.4;return true end}
                car.x=6;local job=Actions:create(player,A,C,rope)
                Actions:update();assert(not shown[job.visualId])
                finishStage();Actions:update()
                assert(shown[job.visualId] and rope:getContainer()==storage and next(S.graph.links)==nil)
                require('CVP_Feedback').cancel(player);Actions:update()
                assert(not shown[job.visualId] and rope:getContainer()==storage and next(S.graph.links)==nil)
            """)

    def test_shared_binding_highlight_switch_and_split_screen(self):
        l=single_player();l.execute("""
            local f=require 'CVP_Feedback';local selected={}
            CVPFreeRopeScene={highlight=function(id,player,on)
                selected[player]=selected[player] or {};selected[player][id]=on or nil end}
            local a,b={},{};local ends={linkId='first',bindingA='binding:shared',bindingB='binding:first:b'}
            f.preview(a,{player=0},true,{},nil,false,ends)
            f.preview(a,{player=1},true,{},nil,false,ends)
            assert(selected[0]['binding:shared'] and selected[1]['binding:shared'])
            f.preview(b,{player=0},true,{},nil,false,{linkId='second',bindingA='binding:shared'})
            assert(not selected[0].first and selected[0].second and selected[0]['binding:shared'])
            f.preview(b,{player=0},false,{})
            assert(not selected[0]['binding:shared'] and selected[1]['binding:shared'])
            f.resetHandler();assert(not selected[1]['binding:shared'])
        """)

    def test_rope_selection_clears_previous_and_resets(self):
        l=single_player();l.execute('''
            local f=require 'CVP_Feedback';local selected={}
            CVPFreeRopeScene={highlight=function(id,player,on) selected[id]=on and player or nil end}
            local a,b={},{};local menu={player=0}
            f.preview(a,menu,true,{},nil,false,{linkId='first'})
            assert(selected.first==0 and selected['binding:first:a']==0)
            f.preview(b,menu,true,{},nil,false,{linkId='second'})
            assert(selected.first==nil and selected.second==0)
            f.preview(a,menu,false,{});assert(selected.second==0)
            f.resetHandler();assert(next(selected)==nil)
        ''')

    def test_important_notices_hide_success_but_keep_progress_errors_and_wear(self):
        l=single_player();l.execute('''
            local f=require 'CVP_Feedback';local mode=2;local draws={}
            PZAPI={ModOptions={getOptions=function() return {getOption=function()
                return {getValue=function() return mode end} end} end}}
            function getTextManager() return {DrawStringCentre=function(_,font,x,y,text) draws[#draws+1]=text end} end
            UIFont={Small=1};IsoCamera={getScreenLeft=function() return 0 end,getScreenTop=function() return 0 end,
                getScreenWidth=function() return 800 end,getScreenHeight=function() return 600 end}
            function getNumActivePlayers() return 1 end;function getSpecificPlayer() return player end
            local t=f.begin(player,1);f.draw();assert(#draws==2)
            f.progress(t,1);f.finish(t);draws={};f.draw();assert(#draws==0)
            mode=1;f.draw();assert(#draws==2)
            mode=2
            for _,reason in ipairs({'IGUI_CVP_CancelledQueue','IGUI_CVP_LinkBlocked'}) do
                t=f.begin(player,1);f.finish(t,reason);draws={};f.draw()
                assert(#draws==2 and draws[1]:find(getText(reason),1,true))
            end
            f.last={};draws={}
            f.wearNotice({stage=2,x=player:getX(),y=player:getY(),z=player:getZ()})
            f.draw();assert(#draws==2)
        ''')

    def test_wear_notice_nearby_aggregated_and_reset(self):
        l=setup(single_player());l.execute('''
            local f=require 'CVP_Feedback'
            getNumActivePlayers=function() return 1 end
            getSpecificPlayer=function() return player end
            local data={stage=1,x=player:getX(),y=player:getY(),z=player:getZ()}
            f.wearNotice(data);f.wearNotice(data)
            assert(f.wear[0].count==2 and f.wear[0].stage==1)
            data.x=data.x+100;f.wearNotice(data);assert(f.wear[0].count==2)
            data.x=player:getX();data.stage=2;f.wearHandler('CVP','wearNotice',data)
            assert(f.wear[0].stage==2 and f.wear[0].count==1)
            f.resetHandler();assert(f.wear[0]==nil)
        ''')

    def test_progress_counts_commits_not_hitch_preparation(self):
        l=setup(single_player())
        l.execute("""
            car.x=6;beginBatch()
            local f=require 'CVP_Feedback';local t=f.active[player]
            assert(t.total==2 and t.done==0)
            for i=1,3 do finishStage();assert(t.done==0) end
            finishStage();finishStage();assert(t.done==1)
            finishStage();finishStage();assert(t.done==2 and t.finished and not t.reason)
            assert(not f.active[player] and f.last[player]==t)
        """)

    def test_explicit_cancel_prevents_late_path_or_action_commit(self):
        for stage in range(7):
            l=setup(single_player())
            l.execute(f"""
                car.x=6;beginBatch()
                for i=1,{stage} do finishStage() end
                local n=#CVPTest.links();local old=queued
                local f=require 'CVP_Feedback';local t=f.active[player]
                f.cancel(player);old:perform()
                assert(#CVPTest.links()==n and t.cancelled and t.finished)
                assert(not f.active[player])
            """)

    def test_new_queue_invalidates_old_action_before_commit(self):
        l=setup(single_player())
        l.execute("""
            car.x=6;beginBatch()
            for i=1,4 do finishStage() end
            local old=queued
            beginBatch()
            old:perform()
            assert(#CVPTest.links()==0 and rope.owner==storage)
        """)

    def test_sequence_from_vehicle_starts_at_hitch_and_uses_distinct_animation(self):
        l=setup(single_player())
        l.execute("""
            car.x=6;player.reportEvent=function(_,event) reportedEvent=event end
            batchMenu(true)
            assert(queued.isPath and queued.x>5)
            finishStage();queued:start()
            assert(queued.anim=='VehicleTrailer' and reportedEvent==nil)
            finishStage();assert(queued.isPath and queued.x==body.x)
            finishStage();queued:start()
            assert(queued.anim=='Loot' and reportedEvent=='EventLootItem')
        """)

    def test_preview_switch_and_projection_cull(self):
        l=single_player()
        l.execute("""
            local f=require 'CVP_Feedback';local a,b={},{}
            local menu={player=0,isVisible=function() return true end}
            f.preview(a,menu,true,{body},car,true)
            f.preview(b,menu,true,{body2},car,true)
            f.preview(a,menu,false,{body},car,true)
            assert(f.previews[0].option==b)
            local draws={};function getTextManager() return {DrawStringCentre=function(_,font,x,y,text) draws[#draws+1]=text end} end
            UIFont={Small=1};IsoCamera={getScreenLeft=function() return 0 end,getScreenTop=function() return 0 end,
                getScreenWidth=function() return 800 end,getScreenHeight=function() return 600 end}
            function getNumActivePlayers() return 0 end
            CVPViewpoint={active=function() return true end,project=function() return false end}
            f.draw();assert(#draws==0,'behind-camera marker must not use isometric projection')
            CVPViewpoint.project=function() return true end
            CVPViewpoint.screenX=function() return 100 end;CVPViewpoint.screenY=function() return 100 end
            f.draw();assert(#draws==2,'overlapping queue and attachment labels must not stack')
            menu.isVisible=function() return false end
            f.draw();assert(f.previews[0]==nil)
        """)

if __name__=='__main__': unittest.main()
