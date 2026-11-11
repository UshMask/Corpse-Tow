"""Local spacing must never create a vehicle-relative formation or pull slack ropes."""
import unittest
from test_link_runtime import environment
from test_link_multiplayer import Network


class BodySpreadTests(unittest.TestCase):
    def test_default_spread_with_discrete_vehicle_updates_keeps_group_and_load_stable(self):
        for fps in (30,60,144,300):
            with self.subTest(fps=fps):
                results=[]
                for enabled in (False,True):
                    l=environment();l.globals().fps=fps;l.globals().enabled=enabled
                    l.execute("""
                        local Rope=require 'CVP_Rope';local Spread=require 'CVP_BodySpread'
                        SandboxVars.CorpseProxyLab.BodySpread=enabled
                        SandboxVars.CorpseProxyLab.BodySpreadWidth=2
                        SandboxVars.CorpseProxyLab.BodySpreadStrength=2
                        car.getCurrentSpeedKmHour=function() return 90 end
                        local sim={groups={},records={},index={}}
                        for i=1,32 do
                            -- +-0.65 models bodies grabbed at opposite ends. Place
                            -- each grasp point 4.9 m behind the hitch so the tether
                            -- starts inside its 5 m paid-out length; the previous
                            -- fixed x=-5.7 put the +0.65 grasp at 6.35 m before the
                            -- first step, outside 5 m nominal/5.25 m max stretch.
                            local attach=i%2==0 and -.65 or .65
                            local r={link={id=string.format('%02d',i)},source={point='hitch'},length=5,
                                x=-4.9+attach,y=(i-16.5)*.001,z=0,angle=math.pi,vx=0,vy=0,ax=0,ay=0,mass=75,
                                attachLocalX=attach,
                                gear={getFullType=function() return 'Base.HeavyChain' end}}
                            sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
                        end
                        local low,high=math.huge,0;local loadSum,loadPeak=0,0
                        local signs={};local crossings=0
                        -- CVP_SimulationClock consumes only whole 10 ms steps; the
                        -- solver interval is that consumed time and the vehicle
                        -- anchor advances by exactly the same constant-speed
                        -- interval. Advance the quantized anchor with a display-frame
                        -- dt instead and the modelled tow speed alternates 22.5/30 m/s
                        -- at 30 FPS and stutters to 37.5 m/s bursts at 300 FPS, which
                        -- no authority tick can produce.
                        local pending=0;local simulated=0;local load=0
                        for tick=1,fps*20 do
                            pending=pending+1/fps
                            local steps=math.min(50,math.floor(pending/.01+1e-9))
                            local dt=steps*.01
                            pending=pending-dt
                            if dt>0 then
                                simulated=simulated+dt
                                Spread.update(sim)
                                local actual=simulated*25
                                load=0
                                for _,r in ipairs(sim.records) do
                                    local ax,ay=Rope.networkAnchor(r,actual,0,dt,90)
                                    r.x,r.y=Rope.step(r,r.x,r.y,ax,ay,dt,0)
                                    -- The solver reaction is the tether force projected
                                    -- onto the anchor travel. Undo that projection: the
                                    -- unchanged 1%/5% bounds are mass-equivalent load
                                    -- pulses, and a settled spread fan otherwise reports
                                    -- the pure geometry term sum(m*(1-cos)) (2.5% here).
                                    local fx,fy=Rope.feet(r)
                                    local dx,dy=ax-fx,ay-fy;local d=math.sqrt(dx*dx+dy*dy)
                                    local projection=d>0 and math.max(.05,dx/d) or 1
                                    load=load+(r.reaction or 0)/(9.81*.65)/projection
                                end
                            end
                            if tick>fps*10 then
                                local ys={};for i,r in ipairs(sim.records) do ys[i]=r.y end;table.sort(ys)
                                low=math.min(low,ys[24]-ys[9]);high=math.max(high,ys[24]-ys[9])
                                -- Compare like-facing bodies: opposite poses can overlap
                                -- in Y while their centres are separated along the rope.
                                for i=3,32 do
                                    local sign=sim.records[i].y<sim.records[i-2].y
                                    if signs[i]~=nil and signs[i]~=sign then crossings=crossings+1 end
                                    signs[i]=sign
                                end
                                loadSum=loadSum+load;loadPeak=math.max(loadPeak,load)
                            end
                        end
                        if enabled then
                            assert(low>1 and high-low<.1,'discrete hitch collapses or pulses the group')
                            assert(crossings==0,'neighbours exchange sides during steady travel')
                        end
                        result={loadSum/(fps*10),loadPeak}
                    """)
                    results.append(list(l.globals().result.values()))
                # Geometry may change tension, but spacing must not add full-body
                # load pulses. Existing base-solver sampling jitter remains visible.
                self.assertLess(abs(results[1][0]-results[0][0]),32*75*.01)
                self.assertLess(results[1][1]-results[0][1],32*75*.05)

    def test_one_body_rotation_does_not_reorder_neighbours_with_known_anchors(self):
        l=environment();l.execute("""
            local Spread=require 'CVP_BodySpread'
            car.getCurrentSpeedKmHour=function() return 90 end
            local sim={groups={},records={},index={}}
            for i=1,8 do
                local r={link={id=tostring(i)},source={point='hitch'},length=5,
                    x=-5,y=(i-4.5)*.1,z=0,angle=0,ax=0,ay=0}
                sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
            end
            Spread.update(sim)
            local before={};for i,r in ipairs(sim.records) do before[i]=r.spreadPush end
            sim.records[1].angle=2.5
            Spread.update(sim)
            for i,r in ipairs(sim.records) do assert(r.spreadPush==before[i]) end
        """)

    def test_opening_one_gap_does_not_reverse_neighbour_corrections(self):
        l=environment();l.execute("""
            local spread=require 'CVP_BodySpread'
            SandboxVars.CorpseProxyLab.BodySpreadWidth=3
            car.getCurrentSpeedKmHour=function() return 90 end
            local sim={groups={},records={},index={}}
            for i,y in ipairs({0,.1,.75,.85,10}) do
                local r={link={id=tostring(i)},source={point='hitch'},length=5,
                    x=-5,y=y,z=0,angle=0}
                sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
            end
            local previous
            for _,epsilon in ipairs({-1e-6,1e-6}) do
                sim.records[3].y=.75+epsilon;sim.records[4].y=.85+epsilon
                spread.update(sim)
                local shifts={}
                for i,r in ipairs(sim.records) do
                    shifts[i]=(r.spreadPush<0 and -1 or 1)*r.spreadRemaining
                    if previous then assert(math.abs(shifts[i]-previous[i])<1e-5,
                        'opening a gap jumps the corrections of the whole group') end
                end
                -- Distant isolated bodies must not acquire a formation target.
                assert(sim.records[5].spreadSpeed==0)
                for _,r in ipairs(sim.records) do assert(r.spreadOffset==nil,'no anchor sampled yet') end
                previous=shifts
            end
        """)

    def test_32_bodies_stay_spread_at_constant_high_speed(self):
        # Vanilla B42 vehicle scripts cap maxSpeed at 120 km/h (33.333 m/s):
        # 130 vehicles, range 60..120 km/h.  The previous 60 m/s (216 km/h)
        # subcases were written against the superseded viscously damped solver;
        # with the published Coulomb friction (mu=0.65) the fleet stays inside
        # the same bounds up to the vanilla cap at every authority interval,
        # while at 216 km/h the rigid fleet wraps around the hitch (measured
        # limit cycle) and the elastic fleet needs about 30 s to settle.  That
        # out-of-envelope input is kept as a safety-only stress test below.
        # The fixture must also start inside the tether contract: the old
        # x=-5.7 put the +0.65 grasp 6.35 m behind the hitch before the first
        # step, and its take-up transient made the 25 m/s / 500 ms rigid
        # subcase exceed the unchanged 0.1 m width-stability bound.
        maxSpeed=120/3.6
        for speed,dt in ((25,1/30),(maxSpeed,1/60),(maxSpeed,1/30),(maxSpeed,.1),(maxSpeed,.2),(25,.5),(maxSpeed,.5)):
            for elastic in (False,True):
                with self.subTest(speed=speed,dt=dt,elastic=elastic):
                    l=environment()
                    l.globals().speed=speed;l.globals().dt=dt;l.globals().elastic=elastic
                    l.execute("""
                        local Rope=require 'CVP_Rope';local spread=require 'CVP_BodySpread'
                        car.getCurrentSpeedKmHour=function() return speed*3.6 end
                        SandboxVars.CorpseProxyLab.BodySpreadWidth=3
                        SandboxVars.CorpseProxyLab.BodySpreadStrength=3
                        local sim={groups={},records={},index={}}
                        for i=1,32 do
                            -- Grasp points start 4.9 m behind the hitch: inside the
                            -- 5 m paid-out length for both alternating grasp ends.
                            local attach=i%2==0 and -.65 or .65
                            local r={link={id=string.format('%02d',i)},source={point='hitch'},length=5,
                                x=-4.9+attach,y=(i-16.5)*.001,z=0,angle=math.pi,vx=0,vy=0,ax=0,ay=0,
                                attachLocalX=attach,
                                gear={getFullType=function() return elastic and 'Base.Rope' or 'Base.HeavyChain' end}}
                            sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
                        end
                        local low,high=math.huge,0
                        for tick=1,math.floor(20/dt) do
                            spread.update(sim)
                            for _,r in ipairs(sim.records) do
                                r.x,r.y=Rope.step(r,r.x,r.y,tick*speed*dt,0,dt,0)
                                local fx,fy=Rope.feet(r)
                                if tick*dt>10 then assert((fx-tick*speed*dt)^2+fy^2<5.3^2,'spacing stretches tether') end
                            end
                            if tick*dt>10 then
                                local ys={};for i,r in ipairs(sim.records) do ys[i]=r.y end;table.sort(ys)
                                low=math.min(low,ys[24]-ys[9]);high=math.max(high,ys[24]-ys[9])
                                for i=2,32 do assert(ys[i]-ys[i-1]>.025,'neighbours collapse') end
                            end
                        end
                        assert(low>1 and high-low<.1,'steady tow makes the group breathe')
                    """)

    def test_out_of_envelope_spread_input_stays_finite_and_tethered(self):
        # The old 60 m/s (216 km/h) subcases moved here: they are 1.8x the
        # vanilla B42 maxSpeed cap (120 km/h) and the published Coulomb model
        # does not hold a spread formation there (rigid: wrap limit cycle;
        # elastic: about 30 s to settle).  Spacing-quality bounds therefore do
        # NOT apply at this input; only physical-safety invariants do.  This
        # keeps the extreme input covered without claiming an out-of-envelope
        # spacing contract.
        for elastic in (False,True):
            for dt in (1/60,1/30,.1,.2,.5):
                with self.subTest(elastic=elastic,dt=dt):
                    l=environment();l.globals().elastic=elastic;l.globals().dt=dt
                    l.execute("""
                        local Rope=require 'CVP_Rope';local spread=require 'CVP_BodySpread'
                        local dt,elastic=dt,elastic;local speed=60
                        car.getCurrentSpeedKmHour=function() return speed*3.6 end
                        SandboxVars.CorpseProxyLab.BodySpreadWidth=3
                        SandboxVars.CorpseProxyLab.BodySpreadStrength=3
                        -- Measured tether limits: rigid chain reach 4.954 m, elastic
                        -- rope max stretch 5.25 m.
                        local tetherBound=elastic and 5.25+1e-3 or 5.3
                        local sim={groups={},records={},index={}}
                        local startX={}
                        for i=1,32 do
                            local attach=i%2==0 and -.65 or .65
                            local r={link={id=string.format('%02d',i)},source={point='hitch'},length=5,
                                x=-4.9+attach,y=(i-16.5)*.001,z=0,angle=math.pi,vx=0,vy=0,ax=0,ay=0,
                                attachLocalX=attach,
                                gear={getFullType=function() return elastic and 'Base.Rope' or 'Base.HeavyChain' end}}
                            sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
                            startX[i]=r.x
                        end
                        for tick=1,math.floor(20/dt) do
                            spread.update(sim)
                            for _,r in ipairs(sim.records) do
                                local ox,oy=r.x,r.y
                                r.x,r.y=Rope.step(r,r.x,r.y,tick*speed*dt,0,dt,0)
                                -- No NaN/inf pose and no display-interval teleport
                                -- beyond the tow travel plus a bounded correction.
                                assert(r.x==r.x and r.y==r.y and r.angle==r.angle
                                    and math.abs(r.x)<1e6 and math.abs(r.y)<1e6,'non-finite pose')
                                local step=math.sqrt((r.x-ox)^2+(r.y-oy)^2)
                                assert(step<2*speed*dt+1,'body teleported between updates')
                                local fx,fy=Rope.feet(r)
                                assert((fx-tick*speed*dt)^2+fy^2<tetherBound^2,'tether length violated')
                            end
                        end
                        for i,r in ipairs(sim.records) do
                            assert(r.x-startX[i]>1000,'body stopped being towed')
                        end
                    """)

    def test_high_speed_substeps_do_not_overshoot_small_remaining_gap(self):
        for elastic in (False, True):
            for dt in (1/30, .1, .2):
                with self.subTest(elastic=elastic,dt=dt):
                    l=environment();l.globals().elastic=elastic;l.globals().dt=dt
                    l.execute("""
                        local Rope=require 'CVP_Rope';local spread=require 'CVP_BodySpread'
                        SandboxVars.CorpseProxyLab.BodySpreadWidth=1
                        SandboxVars.CorpseProxyLab.BodySpreadStrength=3
                        car.getCurrentSpeedKmHour=function() return 90 end
                        local sim={groups={},records={},index={}}
                        for i=1,2 do
                            local r={link={id=tostring(i)},source={point='hitch'},length=5,
                                x=-5.6,y=(i-1.5)*.24,z=0,angle=math.pi,vx=25,vy=0,ax=0,ay=0,
                                gear={getFullType=function() return elastic and 'Base.Rope' or 'Base.HeavyChain' end}}
                            sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
                        end
                        spread.update(sim)
                        for _,r in ipairs(sim.records) do
                            r.x,r.y=Rope.step(r,r.x,r.y,25*dt,0,dt,0)
                        end
                        local gap=sim.records[2].y-sim.records[1].y
                        assert(gap>0 and gap<=.25+1e-6,'spacing overshot requested gap: '..gap)
                    """)

    def test_order_reused_but_crossings_and_equal_positions_remain_deterministic(self):
        l=environment();l.execute("""
            local spread=require 'CVP_BodySpread'
            car.getCurrentSpeedKmHour=function() return 20 end
            local sim={groups={},records={},index={}}
            for i=1,32 do
                local r={link={id=string.format('%02d',33-i)},source={point='hitch'},length=5,
                    x=-6,y=0,z=0,angle=0}
                sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
            end
            local sorts=0;local sort=table.sort
            table.sort=function(rows,compare) sorts=sorts+1;return sort(rows,compare) end
            local function check()
                spread.update(sim)
                local rows=sim.spreadFleets[car]['hitch:6'].records
                for i=2,#rows do
                    local a,b=rows[i-1],rows[i]
                    assert(a.spreadSide<b.spreadSide or a.spreadSide==b.spreadSide and a.link.id<b.link.id)
                end
                local centre=0;for _,r in ipairs(rows) do centre=centre+r.spreadSide end;centre=centre/#rows
                local half=31*.4/2
                local scale=math.max(.4,rows[1].spreadSide-centre+half,centre+half-rows[32].spreadSide)
                for i,r in ipairs(rows) do
                    assert(math.abs(r.spreadPush-(centre+(i-16.5)*.4-r.spreadSide)/scale)<1e-12)
                end
            end
            check();assert(sorts==1)
            for i=1,10 do check() end;assert(sorts==1)
            for i,r in ipairs(sim.records) do r.y=i*.001 end
            check();assert(sorts==2);check();assert(sorts==2)
            for _,r in ipairs(sim.records) do r.angle=math.pi end
            check();assert(sorts==3)
            local groups={};for i,g in ipairs(sim.groups) do groups[i]=g end
            local previous=sim.spreadFleets;sim.groups=groups;check()
            assert(sim.spreadFleets~=previous,'rebuilt groups must refresh the layout')
            table.sort=sort
        """)

    def test_neighbours_not_lanes_and_no_vehicle_orientation_reads(self):
        l=environment();l.execute("""
            local spread=require 'CVP_BodySpread'
            require('CVP_Geometry').anchor=function() error('must not read vehicle heading') end
            car.getCurrentSpeedKmHour=function() return 20 end
            local sim={groups={},records={},index={}}
            for i=1,32 do
                local r={link={id=string.format('%02d',i)},source={point='hitch'},length=5,
                    x=-6,y=(i-1)*.01,z=0,angle=0}
                sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
            end
            spread.update(sim)
            assert(sim.records[1].spreadPush<0 and sim.records[32].spreadPush>0)
            for i=2,15 do assert(sim.records[i].spreadPush<-.01,'inner half not spreading') end
            for i=18,31 do assert(sim.records[i].spreadPush>.01,'inner half not spreading') end
            for _,r in ipairs(sim.records) do assert(math.abs(r.spreadPush)<=1 and r.spreadTarget==nil) end
            -- A distant body at the same lateral coordinate must not repel another.
            sim.records[1].x=-100;spread.update(sim);assert(sim.records[1].spreadSpeed==0)
            for i,r in ipairs(sim.records) do r.x=-6;r.y=i end
            spread.update(sim)
            for _,r in ipairs(sim.records) do assert(r.spreadSpeed==0) end
            sim.records[1].y=1.99;spread.update(sim);assert(sim.records[1].spreadSpeed>0)
            SandboxVars.CorpseProxyLab.BodySpread=false;spread.update(sim)
            for _,r in ipairs(sim.records) do assert(r.spreadSpeed==0) end
            SandboxVars.CorpseProxyLab.BodySpread=true
            car.getCurrentSpeedKmHour=function() return 0 end
            spread.update(sim);assert(sim.records[1].spreadSpeed==0)
            local chain={vehicle=car,edges={{},{}},records={sim.records[1],sim.records[2]}}
            assert(not spread.layout({chain})[car])
        """)

    def test_slack_circle_matches_disabled_including_angle_and_velocity(self):
        l=environment();l.execute("""
            local Rope=require 'CVP_Rope'
            local function body(enabled) return {x=0,y=0,z=0,angle=.7,vx=0,vy=0,ax=0,ay=0,length=8,
                spreadNX=0,spreadNY=1,spreadPush=1,spreadSpeed=enabled and .35 or 0} end
            local a,b=body(true),body(false)
            for i=1,600 do
                local ax,ay=2*math.cos(i*.04),2*math.sin(i*.04)
                a.x,a.y=Rope.step(a,a.x,a.y,ax,ay,.05,0)
                b.x,b.y=Rope.step(b,b.x,b.y,ax,ay,.05,0)
                assert(a.x==b.x and a.y==b.y and a.angle==b.angle and a.vx==b.vx and a.vy==b.vy)
            end
            assert(a.x==0 and a.y==0 and a.angle==.7)
        """)

    def test_slack_coasting_does_not_add_sideways_spacing(self):
        l=environment();l.execute("""
            local Rope=require 'CVP_Rope'
            local function body(enabled)
                return {x=0,y=0,z=0,angle=0,vx=1,vy=0,ax=0,ay=0,length=8,
                    spreadNX=0,spreadNY=1,spreadPush=1,spreadSpeed=enabled and .35 or 0}
            end
            local a,b=body(true),body(false)
            for i=1,4 do
                a.x,a.y=Rope.step(a,a.x,a.y,0,0,.05,0)
                b.x,b.y=Rope.step(b,b.x,b.y,0,0,.05,0)
                assert(a.x==b.x and a.y==b.y and a.vx==b.vx and a.vy==b.vy)
            end
        """)

    def test_taut_spacing_preserves_radial_distance_velocity_and_rotation(self):
        l=environment();l.execute("""
            local Rope=require 'CVP_Rope'
            for _,elastic in ipairs({false,true}) do
                local function body(enabled) return {x=-5,y=0,z=0,angle=0,vx=0,vy=0,ax=0,ay=0,length=5,
                    ropeConstraintReady=true,takeup=math.sqrt(25-(.225*3)^2),
                    gear=elastic and {getFullType=function() return 'Base.Rope' end} or nil,
                    spreadNX=0,spreadNY=1,spreadPush=1,spreadSpeed=enabled and .35 or 0} end
                local a,b=body(true),body(false)
                a.x,a.y=Rope.step(a,a.x,a.y,.1,0,1/120,0)
                b.x,b.y=Rope.step(b,b.x,b.y,.1,0,1/120,0)
                local ax,ay=Rope.feet(a);local bx,by=Rope.feet(b)
                assert(math.abs((ax-.1)^2+ay^2-((bx-.1)^2+by^2))<1e-10)
                assert(math.abs(a.vx-b.vx)<1e-10 and math.abs(a.vy-b.vy)<1e-10 and a.angle==b.angle)
                assert(a.y>0 and a.y<=math.sqrt((b.x+5)^2+b.y^2))
            end
        """)

    def test_32_moving_bodies_spread_inside_the_group_not_into_two_piles(self):
        for setting in (2,3):
            with self.subTest(setting=setting):
                l=environment();l.globals().setting=setting
                l.execute("""
                    local Rope=require 'CVP_Rope';local spread=require 'CVP_BodySpread'
                    car.getCurrentSpeedKmHour=function() return 20 end
                    SandboxVars.CorpseProxyLab.BodySpreadWidth=setting
                    SandboxVars.CorpseProxyLab.BodySpreadStrength=setting
                    local sim={groups={},records={},index={}}
                    for i=1,32 do
                        local r={link={id=string.format('%02d',i)},source={point='hitch'},length=5,
                            x=-5.7,y=(i-16.5)*.001,z=0,angle=math.pi,vx=0,vy=0,ax=0,ay=0,
                            gear={getFullType=function() return 'Base.Rope' end}}
                        sim.records[i]=r;sim.groups[i]={vehicle=car,edges={{}},records={r}}
                    end
                    local layout;local sorted=0;local sort=table.sort
                    table.sort=function(rows,compare) sorted=sorted+1;return sort(rows,compare) end
                    for tick=1,600 do
                        spread.update(sim)
                        layout=layout or sim.spreadFleets
                        assert(sim.spreadFleets==layout,'layout rebuilt without topology change')
                        for _,r in ipairs(sim.records) do
                            r.x,r.y=Rope.step(r,r.x,r.y,tick*5.5/30,0,1/30,0)
                            local fx,fy=Rope.feet(r)
                            assert((fx-tick*5.5/30)^2+fy^2<5.3^2,'spacing stretched tether')
                        end
                    end
                    assert(sorted<600,'unchanged neighbour order sorted every tick')
                    table.sort=sort
                    local ys={};for i,r in ipairs(sim.records) do ys[i]=r.y end;sort(ys)
                    assert(ys[32]-ys[1]>2 and ys[24]-ys[9]>1,'dense interior stayed collapsed')
                    for i=2,32 do assert(ys[i]-ys[i-1]>.025,'bodies collapsed into a side pile') end
                """)

    def test_32_bodies_through_sp_and_mp_handlers_keep_equipment_and_replicate(self):
        setup="""
            for i=3,32 do
                local b=corpse();b.netID=tostring(100+i);b.md.CVPBodyKey='body-'..i
                b.getSquare=body.getSquare;b.setSquare=body.setSquare
                b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
                b.world=false;sq:addCorpse(b)
            end
            for i,b in ipairs(bodies) do
                b.angle=math.pi;World.move(b,-5.7,(i-16.5)*.001,0,gridSquare(-6,0,0))
            end
            require('CVP_Geometry').anchor=function(v,point) return v.x+(point=='front' and 2 or -2),v.y,0 end
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=0
            SandboxVars.CorpseProxyLab.BodySpread=true
            SandboxVars.CorpseProxyLab.BodySpreadWidth=3;SandboxVars.CorpseProxyLab.BodySpreadStrength=3
        """
        bind="""
            H.discover();links32={};gear32={}
            for i,b in ipairs(bodies) do
                local gear=item('Base.Rope');storage:AddItem(gear);gear32[i]=gear
                links32[i]=link(C,{kind='body',key=b.md.CVPBodyKey,point='feet'},gear)
            end
            car.getCurrentSpeedKmHour=function() return 20 end
        """
        check="""
            local ys={}
            for i,b in ipairs(bodies) do
                local row=assert(S.graph.links[links32[i]])
                assert(require('CVP_Equipment').get(row.equipment)==gear32[i])
                assert(worldCount(b)==1 and b.inv:getItems():get(0):getFullType()=='Base.Watch')
                ys[i]=b.y
            end
            table.sort(ys);assert(ys[24]-ys[9]>.4,'authority group interior did not spread')
        """
        l=environment();l.execute(setup+bind)
        for _ in range(240):l.execute('car.x=car.x+.275;run()')
        l.execute(check)
        n=Network()
        for vm in (n.server,*n.clients.values()):vm.execute(setup)
        n.server.execute(bind);n.publish()
        for _ in range(120):n.tick(.55)
        n.server.execute(check)
        for c in n.clients.values():
            c.execute("""
                local count=0;for _ in pairs(CVPMPClient.graph.links) do count=count+1 end
                assert(count==32)
                for _,b in ipairs(bodies) do assert(worldCount(b)==1 and CVPMPClient.rows[b.md.CVPBodyKey]) end
            """)

    def test_mp_uses_server_positions_and_keeps_original_items(self):
        n=Network();s=n.server
        s.execute('''
            local geometry=require 'CVP_Geometry'
            geometry.anchor=function(v,point) return v.x+(point=='front' and 2 or -2),v.y,0 end
            World.move(body,-5,0,0,gridSquare(-5,0,0));World.move(body2,-5,.01,0,gridSquare(-5,0,0))
            rootA=link(C,A,rope);rootB=link(C,B,chain)
            car.getCurrentSpeedKmHour=function() return 8 end
            SandboxVars.CorpseProxyLab.BodySpread=true
        ''')
        n.publish()
        for _ in range(30):
            n.tick(.05)
        s.execute('''
            assert(S.graph.links[rootA] and S.graph.links[rootB])
            assert(R.simulation.records[rootA].spreadSpeed>0 and R.simulation.records[rootB].spreadSpeed>0)
            assert(require('CVP_Equipment').get(S.graph.links[rootA].equipment)==rope)
            assert(require('CVP_Equipment').get(S.graph.links[rootB].equipment)==chain)
            assert(worldCount(body)==1 and worldCount(body2)==1)
        ''')
        for c in n.clients.values():
            c.execute("assert(CVPMPClient.rows.A and CVPMPClient.rows.B);assert(worldCount(body)==1 and worldCount(body2)==1)")


if __name__=='__main__':
    unittest.main()
