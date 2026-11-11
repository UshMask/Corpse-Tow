"""Snapshot freshness/identity and unchanged time-integrated load, without timings."""
import unittest
from test_link_simulation import environment


class MotionInputTests(unittest.TestCase):
    def test_snapshot_matches_individual_samples_for_mixed_endpoint_types(self):
        l=environment(); l.execute('''
            H.actor(player)
            local ends={A,B,C,{kind='body',native=body.netID,point='neck'},
                {kind='held',holder='player'},{kind='ground',x=2,y=3,z=.025}}
            local graph={links={}}
            for i,e in ipairs(ends) do graph.links[i]={a=e,b=ends[i%#ends+1]} end
            for pass=1,3 do
                car.x=car.x+.1;move(body,body.x+.1,body.y+.1);body.angle=.3*pass
                player.x=player.x+.2
                local rows,holders=H.samples(graph)
                for id,link in pairs(graph.links) do for _,side in ipairs({'a','b'}) do
                    local expected=assert(H.sample(link[side]));local actual=assert(rows[id][side])
                    for key,value in pairs(expected) do assert(actual[key]==value,key) end
                    for key,value in pairs(actual) do assert(expected[key]==value,key) end
                end end
                assert(holders.player)
            end
            H.players={};local rows,holders=H.samples(graph)
            assert(not holders.player and not rows[5].a)
        ''')

    def test_snapshot_reuses_native_attachment_reads_and_keeps_independent_rows(self):
        l=environment(); l.execute('''
            local graph={links={}}
            for i=1,32 do graph.links[i]={a=C,b=A} end
            local geometry=require 'CVP_Geometry';local anchor=geometry.anchor
            local point=H.bodyPoint;local anchors,points=0,0
            geometry.anchor=function(...) anchors=anchors+1;return anchor(...) end
            H.bodyPoint=function(...) points=points+1;return point(...) end
            local rows=H.samples(graph)
            assert(anchors==1 and points==1)
            local x=rows[2].a.x;rows[1].a.x=999;rows[1].b.x=999
            assert(rows[2].a.x==x and rows[2].b.x~=999,'snapshot rows must not alias')
            car.x=car.x+.5;move(body,body.x+.3,body.y)
            local fresh=H.samples(graph)
            assert(anchors==2 and points==2 and fresh[2].a.x~=x)
            assert(fresh[2].b.x~=rows[2].b.x,'new snapshot must read moved body')
        ''')

    def test_snapshot_separates_attachment_points_and_validates_each_reference(self):
        l=environment(); l.execute('''
            local neck={kind='body',key=A.key,point='neck'}
            local bad={kind='body',key='wrong',native=body.netID,point='feet'}
            local graph={links={one={a=C,b=A},two={a=neck,b=bad}}}
            local rows=H.samples(graph)
            assert(rows.one.b.x~=rows.two.a.x and not rows.two.b)
            local sq=body.getSquare;body.getSquare=function() return nil end
            local fresh=H.samples(graph);assert(not fresh.one.b and not fresh.two.a)
            body.getSquare=sq;assert(H.samples(graph).one.b)
            local carSq=car.getSquare;car.getSquare=function() return nil end
            assert(not H.samples(graph).one.a)
            car.getSquare=carSq;assert(H.samples(graph).one.a)
            body2.md.CVPBodyKey=A.key;H.discover()
            assert(not H.samples(graph).one.b,'ambiguous identity must stay unavailable')
        ''')

    def test_prepared_blend_preserves_slack_ramp_and_variable_frame_intervals(self):
        l=environment(); l.execute('''
            local load=require 'CVP_Load';local r={mass=75};local expected=0
            for i=1,180 do
                local dt=({.016/2,.017/3,.1/12,0,-.01})[i%5+1]
                local taut=i%7~=0;r.mass=i%13==0 and 130 or 75
                if taut then expected=expected+(r.mass-expected)*(1-math.exp(-math.max(0,dt)/.2))
                else expected=0 end
                assert(load.tension(r,taut,dt,load.blend(dt))==expected)
            end
        ''')

if __name__ == '__main__':
    unittest.main()
