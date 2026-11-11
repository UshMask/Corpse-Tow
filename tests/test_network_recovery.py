"""Bounded authoritative recovery; no camera-specific exceptions or teleports."""
import unittest
from test_link_multiplayer import vm
from test_link_obstacles import WORLD


def environment(reverse=False, shared=False):
    l=vm(True);l.globals().reverse=reverse;l.globals().shared=shared
    l.execute('''
        logs={};print=function(message) logs[#logs+1]=tostring(message) end
        if shared then
            beside(C);local token=assert(S:prepare(player,C,rope:getID(),true))
            beside(A);local ok,id=R:create(player,token,A);assert(ok,id);root=id
        else root=reverse and link(A,C,rope) or link(C,A,rope) end
        tail=link(A,B,chain)
        car.getCurrentSpeedKmHour=function() return 54 end
        side=reverse and 'b' or 'a'
        function run() now=now+50;CVPMPServer.tick();assert(not CVPMPServer.error,CVPMPServer.error) end
        function attached() return S.graph.links[root][side].kind=='vehicle' end
        function warm() for i=1,8 do car.x=car.x+.75;run() end end
        function delayed(distance)
            for i=1,39 do
                local x,y=body.x,body2.x;run()
                assert(math.abs(body.x-x)<2 and math.abs(body2.x-y)<2,'body jumped while waiting for packet')
            end
            local before=body.x
            car.x=car.x+distance;run()
            return before
        end
        function hasLog(text)
            for _,line in ipairs(logs) do if line:find(text,1,true) then return true end end
            return false
        end
        function intact()
            for _,b in ipairs({body,body2}) do
                assert(worldCount(b)==1 and b.inv:getItems():size()==1)
                assert(b.inv:getItems():get(0):getFullType()=='Base.Watch')
            end
            assert(E.get(S.graph.links[root].equipment)==rope)
            assert(E.get(S.graph.links[tail].equipment)==chain)
        end
        E=require 'CVP_Equipment'
    ''')
    return l


class NetworkRecoveryTests(unittest.TestCase):
    def test_regular_vehicle_packets_produce_continuous_hitch_travel(self):
        for speed in (54,90,180):
            with self.subTest(speed=speed):
                l=environment();l.globals().speed=speed;l.execute('''
                    car.getCurrentSpeedKmHour=function() return speed end
                    local previous;local step=speed/3.6*.05
                    for i=1,60 do
                        if i%3==1 then car.x=car.x+3*step end
                        run();assert(attached())
                        local x=R.simulation.records[root].ax
                        if previous then assert(math.abs(x-previous)<=step*1.5+.001,'unbounded hitch catch-up') end
                        -- Start-at-full-speed first takes up the existing slack/recovery.
                        if i>30 then assert(math.abs(x-previous-step)<.001,'packet cadence leaked into hitch motion') end
                        previous=x
                    end
                    intact()
                ''')

    def test_confirmed_turn_does_not_extrapolate_previous_heading(self):
        l=environment();l.execute('''
            for i=1,30 do if i%3==1 then car.x=car.x+2.25 end;run() end
            local endpoint=R.host.sample(S.graph.links[root][side]);local previous
            for i=1,30 do
                if i%3==1 then car.y=car.y+2.25 end
                run();assert(attached());local r=R.simulation.records[root]
                assert(r.ax<=endpoint.x+.001)
                if i>6 then assert(math.abs(r.ay-previous-.75)<.001) end
                previous=r.ay
            end
            intact()
        ''')

    def test_hitch_stops_at_last_confirmation_when_packets_stop(self):
        l=environment();l.execute('''
            for i=1,30 do if i%3==1 then car.x=car.x+2.25 end;run() end
            local endpoint=R.host.sample(S.graph.links[root][side]);local previous=R.simulation.records[root].ax
            -- Stale reported speed must not move a stopped or disconnected car.
            for i=1,50 do
                run();local x=R.simulation.records[root].ax
                assert(x>=previous-.001 and x<=endpoint.x+.001);previous=x
            end
            assert(math.abs(previous-endpoint.x)<.001 and attached());intact()
        ''')

    def test_sp_does_not_buffer_hitch_positions(self):
        l=environment();l.execute('''
            function isServer() return false end
            for i=1,20 do
                car.x=car.x+.75;run()
                local r=R.simulation.records[root];local endpoint=R.host.sample(S.graph.links[root][side])
                assert(math.abs(r.ax-endpoint.x)<.001 and not r.networkMotion)
            end
            intact()
        ''')

    def test_unavailable_body_preserves_history_for_bounded_recovery(self):
        for root_missing in (False,True):
            with self.subTest(root_missing=root_missing):
                l=environment();l.globals().rootMissing=root_missing
                l.execute("""
                    warm();local missing=rootMissing and body or body2
                    local saved=missing.sq;local old=R.simulation.records[root]
                    local before=body.x;missing.sq=nil;R.host.discover()
                    for i=1,20 do car.x=car.x+.75;run();assert(attached()) end
                    assert(body.x==before and R.simulation.records[root]==old)
                    missing.sq=saved
                    for i=1,60 do car.x=car.x+.75;run();assert(attached()) end
                    assert(body.x>before+30)
                    assert(hasLog('[CVP recovery] start') and hasLog('[CVP recovery] complete'));intact()
                """)

    def test_unavailable_body_does_not_bypass_recovery_limits_or_obstacles(self):
        cases={
            'expired':(50,''),
            'teleport':(10,'car.x=car.x+100'),
            'reverse':(10,'car.x=car.x-40'),
            'wall':(10,'wallX=12'),
            'solid':(10,'solidX=12'),
            'unloaded_path':(10,'missingX=12'),
            'floor':(10,'car.z=1'),
        }
        for name,(ticks,change) in cases.items():
            with self.subTest(name=name):
                l=environment();l.execute(WORLD);l.globals().ticks=ticks
                l.execute("""
                    warm();before=body.x;local saved=body2.sq
                    body2.sq=nil;R.host.discover()
                    for i=1,ticks do car.x=car.x+.75;run() end
                    body2.sq=saved
                """)
                l.execute(change+'\nrun();assert(body.x==before);intact()')
                if name in ('wall','solid','unloaded_path'):
                    l.execute('assert(R.simulation.obstacles[root]);car.x=car.x+10;run();assert(body.x==before);intact()')
                l.execute('assert(not attached())')

    def test_slow_tick_catchup_remains_bounded_and_respects_obstacles(self):
        l=environment();l.execute('''
            car.getCurrentSpeedKmHour=function() return 90 end;warm()
            local solver=require 'CVP_GroupConstraints';local step=solver.step;local calls=0
            solver.step=function(...) calls=calls+1;return step(...) end
            now=now+500;car.x=car.x+12.5;CVPMPServer.tick()
            assert(calls==50 and attached());intact() -- 500 ms at the shared 100 Hz authority clock.
            calls=0;now=now+10000;CVPMPServer.tick()
            assert(calls<=50,'long stall created unbounded catch-up work');intact()
        ''')
        for obstruction in ('wallX=12','solidX=12','missingX=12'):
            with self.subTest(obstruction=obstruction):
                l=environment(shared=True);l.execute(WORLD)
                l.execute('car.getCurrentSpeedKmHour=function() return 90 end;warm();before=body.x')
                l.execute(obstruction+';now=now+500;car.x=car.x+12.5;CVPMPServer.tick()')
                l.execute('assert(body.x==before and not CVPMPServer.error);intact()')

    def test_stall_boundary_keeps_bounded_progress_without_time_debt(self):
        positions=[]
        for interval in (500,501,1000,10000):
            with self.subTest(interval=interval):
                l=environment();l.globals().interval=interval
                l.execute("""
                    warm();local solver=require 'CVP_GroupConstraints'
                    local step=solver.step;calls=0
                    solver.step=function(...) calls=calls+1;return step(...) end
                    local before=body.x
                    now=now+interval;car.x=car.x+.75;CVPMPServer.tick()
                    assert(not CVPMPServer.error,CVPMPServer.error)
                    assert(calls==50,'stall lost bounded simulation time')
                    assert(attached() and body.x>before);intact()
                    progressed=body.x
                    calls=0;now=now+50;car.x=car.x+.75;CVPMPServer.tick()
                    assert(calls==5,'stall left catch-up debt');intact()
                """)
                positions.append(l.globals().progressed)
        for position in positions[1:]:
            self.assertAlmostEqual(position,positions[0],places=6)

    def test_slow_server_ticks_keep_up_without_losing_materials(self):
        for shared in (False,True):
            for interval in (200,500):
                with self.subTest(shared=shared,interval=interval):
                    l=environment(shared=shared);l.globals().interval=interval
                    l.execute('''
                        car.getCurrentSpeedKmHour=function() return 90 end;warm()
                        local before=body.x;local start=car.x
                        for i=1,30 do
                            now=now+interval;car.x=car.x+25*interval/1000;CVPMPServer.tick()
                            assert(not CVPMPServer.error,CVPMPServer.error)
                            assert(attached(),'normal slow server tick detached train')
                        end
                        assert(body.x-before>car.x-start-3,'bodies accumulated movement debt')
                        assert(not hasLog('[CVP recovery] start'));intact()
                    ''')

    def test_live_short_interval_corrections_recover_without_moving_loot(self):
        for speed,jump,interval in ((87.1,14.02,16),(72.2,15.34,23)):
            for reverse in (False,True):
                with self.subTest(speed=speed,reverse=reverse):
                    l=environment(reverse)
                    l.globals().speed=speed;l.globals().jump=jump;l.globals().interval=interval
                    l.execute('''
                        S.graph.links[root].length=6;car.getCurrentSpeedKmHour=function() return speed end
                        warm();local before=body.x
                        car.x=car.x+jump;now=now+interval;CVPMPServer.tick()
                        -- A 16 ms packet can precede the next 60 Hz solve by <1 ms.
                        now=now+2;CVPMPServer.tick()
                        assert(not CVPMPServer.error,CVPMPServer.error)
                        assert(attached(),'live correction released root')
                        assert(body.x-before<4,'correction teleported body')
                        assert(hasLog('[CVP recovery] start'))
                        for i=1,60 do car.x=car.x+speed/3.6*.05;run();assert(attached()) end
                        assert(hasLog('[CVP recovery] complete'));intact()
                    ''')

    def test_short_correction_still_rejects_warps_and_obstacles(self):
        cases={
            'large':'car.x=car.x+17',
            'opposite':'car.x=car.x-30',
            'sideways':'car.y=car.y+20',
            'stopped':'car.getCurrentSpeedKmHour=function() return 0 end;car.x=car.x+14',
            'too_slow':'car.getCurrentSpeedKmHour=function() return 10 end;car.x=car.x+14',
            'floor':'car.z=1;car.x=car.x+14',
            'wall':'wallX=12;car.x=car.x+14',
            'solid':'solidX=12;car.x=car.x+14',
            'unloaded':'missingX=12;car.x=car.x+14',
        }
        for name,code in cases.items():
            with self.subTest(name=name):
                l=environment();l.execute(WORLD)
                l.execute('S.graph.links[root].length=6;car.getCurrentSpeedKmHour=function() return 72.2 end;warm();before=body.x')
                l.execute(code+';now=now+23;CVPMPServer.tick()')
                l.execute('assert(not attached() and not hasLog("[CVP recovery] start"));assert(body.x==before);intact()')

    def test_repeated_short_correction_cancels_recovery(self):
        l=environment();l.execute('''
            S.graph.links[root].length=6;car.getCurrentSpeedKmHour=function() return 72.2 end;warm()
            car.x=car.x+15.34;now=now+23;CVPMPServer.tick();assert(attached())
            local before=body.x
            car.x=car.x+14;now=now+23;CVPMPServer.tick()
            assert(not attached() and body.x==before);intact()
        ''')

    def test_delayed_update_keeps_continuous_rope_after_first_body_is_removed(self):
        l=environment();l.execute('''
            assert(S:unloadBody('A',{x=body.x,y=body.y,z=.05}))
            warm();delayed(30)
            assert(attached(),'empty junction prevented delayed update recovery')
            for i=1,60 do car.x=car.x+.75;run();assert(attached()) end
            intact()
        ''')

    def test_reloaded_vehicle_does_not_inherit_network_history(self):
        l=environment();l.execute('''
            warm();for i=1,39 do run() end
            local replacement=setmetatable({},{__index=car})
            car=replacement;R.host.discover() -- exercise the real loaded registry replacement
            car.x=car.x+30;run()
            assert(not attached() and not hasLog('[CVP recovery] start'),
                'reloaded vehicle inherited motion history');intact()
        ''')

    def test_delayed_update_recovers_moving_train_without_teleport_or_item_loss(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                l=environment(reverse);l.execute('''
                    warm();local before=delayed(30)
                    assert(attached(),'delayed update released root')
                    assert(body.x-before<4,'body jumped with vehicle')
                    assert(hasLog('[CVP recovery] start'))
                    for i=1,60 do
                        local x,y=body.x,body2.x;car.x=car.x+.75;run()
                        assert(attached(),'recovery failed while vehicle kept moving')
                        assert(body.x-x<2 and body2.x-y<2,'recovery teleported a body')
                    end
                    assert(hasLog('[CVP recovery] complete') and not hasLog('[CVP detach]'))
                    intact()
                ''')

    def test_normal_authority_pause_can_use_same_bounded_recovery(self):
        l=environment();l.execute('''
            warm();now=now+1950;car.x=car.x+30;run()
            assert(attached());for i=1,40 do run() end
            assert(attached() and hasLog('[CVP recovery] complete'));intact()
        ''')

    def test_teleports_stationary_warps_reverse_and_long_gaps_do_not_get_grace(self):
        cases={
            'instant': 'warm();car.x=car.x+30;run()',
            'stationary': 'car.getCurrentSpeedKmHour=function() return 0 end;delayed(30)',
            'large': 'warm();delayed(80)',
            'opposite': 'warm();delayed(-30)',
            'too_late': 'warm();for i=1,59 do run() end;car.x=car.x+30;run()',
            'new_link': 'delayed(30)',
        }
        for name,code in cases.items():
            with self.subTest(name=name):
                l=environment();l.execute(code);l.execute('''
                    assert(not attached() and not hasLog('[CVP recovery] start'))
                    assert(hasLog('[CVP detach]') and hasLog('reason=excess_gap'))
                    assert(S.graph.links[tail].a.kind=='body');intact()
                ''')

    def test_wall_solid_tile_and_unloaded_path_never_receive_recovery_movement(self):
        for obstruction in ('wallX=12','solidX=12','missingX=12'):
            with self.subTest(obstruction=obstruction):
                l=environment();l.execute(WORLD);l.execute('warm();for i=1,39 do run() end;before=body.x')
                l.execute(obstruction);l.execute('''
                    car.x=car.x+30;run()
                    assert(not attached() and body.x==before)
                    assert(not hasLog('[CVP recovery] start') and hasLog('[CVP detach]'))
                    intact()
                ''')

    def test_new_wall_and_second_teleport_cancel_active_recovery(self):
        for failure in ('wallX=12','car.x=car.x+30'):
            with self.subTest(failure=failure):
                l=environment();l.execute(WORLD);l.execute('warm();delayed(30);assert(attached());before=body.x')
                l.execute(failure);l.execute('''
                    run();assert(not attached() and body.x==before and hasLog('[CVP detach]'));intact()
                ''')

    def test_stalled_recovery_times_out_without_extending_deadline(self):
        l=environment();l.execute('''
            warm();delayed(30);assert(attached())
            -- A very slow server cannot complete catch-up inside the grace budget.
            for i=1,3 do now=now+950;car.x=car.x+4;run() end
            assert(not attached() and hasLog('reason=recovery_timeout'));intact()
            local starts=0;for _,line in ipairs(logs) do if line:find('[CVP recovery] start',1,true) then starts=starts+1 end end
            assert(starts==1,'later corrections renewed the recovery budget')
        ''')

    def test_floor_change_detaches_even_after_delayed_movement(self):
        l=environment();l.execute('''
            warm();for i=1,39 do run() end
            car.z=1;car.x=car.x+30;run()
            assert(not attached() and hasLog('reason=floor_change'));intact()
        ''')

    def test_diagnostics_log_successful_release_once_and_include_motion_context(self):
        l=environment();l.execute('''
            warm();car.x=car.x+30;run();for i=1,10 do run() end
            local count=0
            for _,line in ipairs(logs) do if line:find('[CVP detach]',1,true) then
                count=count+1
                for _,field in ipairs({'reason=excess_gap','gap=','jump=30.00','anchorIdleMs=50','tickMs=50','speedKmh=54.0'}) do
                    assert(line:find(field,1,true),'missing diagnostic '..field)
                end
            end end
            assert(count==1)
        ''')

    def test_failed_save_does_not_log_release_until_retry_succeeds(self):
        l=environment();l.execute('''
            warm();local edit=E.editLinks
            E.editLinks=function() return false,'injected save failure' end
            car.x=car.x+30;now=now+50;CVPMPServer.tick()
            assert(CVPMPServer.error and attached() and not hasLog('[CVP detach]'))
            E.editLinks=edit;now=now+5000;CVPMPServer.tick()
            assert(not CVPMPServer.error and not attached() and hasLog('[CVP detach]'));intact()
        ''')

    def test_singleplayer_does_not_acquire_network_grace(self):
        from test_link_runtime import environment as singleplayer
        l=singleplayer();l.execute('''
            local root=link(C,A,rope);car.getCurrentSpeedKmHour=function() return 54 end
            for i=1,8 do car.x=car.x+.75;run() end
            now=now+1950;car.x=car.x+30;run()
            assert(S.graph.links[root].a.kind=='ground');intact(body)
        ''')


if __name__=='__main__':unittest.main()

