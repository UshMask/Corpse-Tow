"""An empty towing scene does no visual/solver work and wakes on new links."""
import unittest
from test_link_runtime import environment
from test_link_presentation import scene
from test_link_client import client


class IdleWorkTests(unittest.TestCase):
    def test_empty_solver_skips_obstacle_cache_and_wakes_for_attachment(self):
        l = environment(); l.execute('''
            local next=next;_G.next=nil
            local obstacles=require 'CVP_LinkObstacles';local create=obstacles.new;local calls=0
            obstacles.new=function(...) calls=calls+1;return create(...) end
            Sim.obstacles.old='blocked';H.joints={old={}};H.freeEnds={old={}}
            for i=1,10 do
                local requests,loads=Sim:tick(S.graph,S.index,.05,now)
                assert(next(requests)==nil and next(loads)==nil)
            end
            assert(calls==0 and next(Sim.obstacles)==nil and next(H.joints)==nil and next(H.freeEnds)==nil)
            local id=link(C,A,rope);car.x=car.x+.1
            Sim:tick(S.graph,S.index,.05,now)
            assert(calls>0 and Sim.records[id])
        ''')

    def test_empty_presentation_clears_old_curves_without_reading_options(self):
        l = scene(); l.execute('''
            local next=next;_G.next=nil
            local id=link(A,B,rope);render();assert(drawn[id])
            PZAPI={ModOptions={getOptions=function() error('idle option read') end}}
            assert(Renderer:update({links={}},{},.05))
            assert(removed[id] and next(Renderer.curves)==nil)
            CVPFreeRopeScene.remove=function() error('repeated clear') end
            for i=1,10 do assert(Renderer:update({links={}},{},.05)) end
        ''')

    def test_empty_client_does_not_collect_presentation_samples(self):
        l = client(); l.execute('''
            local next=next;_G.next=nil
            R.samples=function() return true end -- isolate the visual snapshot
            local calls=0;local samples=H.samples
            H.samples=function(...) calls=calls+1;return samples(...) end
            callbacks.OnTick();assert(calls==0 and not CVPRuntime.visualError)
            link(C,A,rope);callbacks.OnTick()
            assert(calls>0 and next(drawn)~=nil)
        ''')

    def test_empty_and_expired_feedback_do_not_touch_ui(self):
        l = client(); l.execute('''
            local next=next;_G.next=nil
            local f=require 'CVP_Feedback';f.resetHandler()
            getTextManager=function() error('idle text manager read') end
            getNumActivePlayers=function() error('idle player read') end
            f.draw()
            f.last[player]={finished=true,expires=getTimestampMs()-1}
            f.wear[0]={expires=getTimestampMs()-1}
            f.draw();assert(next(f.last)==nil and next(f.wear)==nil)
            f.draw()
        ''')


if __name__ == '__main__':
    unittest.main()
