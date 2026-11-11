"""Calculated chain poses, native commit bounds and transactional rollback; no timing."""
import unittest
from test_link_runtime import environment as base_environment


def environment(batch=True):
    l=base_environment()
    if batch:
        l.execute("""
            readPasses=0;poseReads=0
            CVPWorldNative.beginRead=function() readPasses=readPasses+1;return {} end
            CVPWorldNative.contains=function(pass,b)
                assert(pass);return b:getSquare()~=nil and b:getStaticMovingObjectIndex()>=0 end
            CVPWorldNative.readPoses=function(pass,records)
                poseReads=poseReads+1
                for _,r in ipairs(records) do local b=r.body
                    assert(CVPWorldNative.contains(pass,b),'world corpse missing before pose read')
                    r.before=r.before or {};local p=r.before
                    p.x=b:getX();p.y=b:getY();p.z=b:getZ();p.angle=b:getAngle();p.square=b:getSquare()
                end
            end
        """)
    return l


class PoseBatchTests(unittest.TestCase):
    def test_render_mode_sampled_once_per_tick_and_refreshed_sp_mp(self):
        for server in (False, True):
            l=environment();l.globals().serverMode=server;l.execute("""
                function isServer() return serverMode end
                function sendRemoveItemFromContainer() end;function sendAddItemToContainer() end
                local checks=0;local fast=true
                CVPDynamicCorpses={canSkipMoveInvalidation=function() checks=checks+1;return fast end}
                link(C,A,rope);link(C,B,chain)
                for _,mode in ipairs({true,false,true}) do
                    fast=mode;checks=0;car.x=car.x+.2
                    Sim:tick(S.graph,S.index,.05,now)
                    assert(checks==1,'one render-mode read across all groups')
                end
                -- No persistent cache: standalone moves/rollback query the live mode.
                checks=0;fast=false;body.invalidations=0
                World.move(body,body:getX()+.001,body:getY(),body:getZ(),body:getSquare())
                assert(checks==1 and body.invalidations==1);intact(body);intact(body2)
            """)

    def test_native_world_renderer_same_square_and_mode_transitions(self):
        for client in (False, True):
            l=environment();l.globals().clientMode=client;l.execute('''
                function isClient() return clientMode end
                local fast=false
                CVPDynamicCorpses={canSkipMoveInvalidation=function() return fast end}
                local sq=body:getSquare();local x,y,z=body:getX(),body:getY(),body:getZ()
                body.invalidations=0
                World.move(body,x+.01,y,z,sq);assert(body.invalidations==1)
                fast=true
                World.move(body,x+.02,y,z,sq);assert(body.invalidations==1 and body:getX()==x+.02)
                -- Same-square rollback still applies the exact position.
                World.move(body,x+.01,y,z,sq);assert(body.invalidations==1 and body:getX()==x+.01)
                fast=false -- camera switched to Viewpoint or baking was enabled
                World.move(body,x+.03,y,z,sq);assert(body.invalidations==2)
                CVPDynamicCorpses=nil
                World.move(body,x,y,z,sq);assert(body.invalidations==3)
                intact(body)
            ''')

    def test_native_world_renderer_preserves_cross_square_failure_rollback(self):
        for client in (False, True):
            l=environment();l.globals().clientMode=client;l.execute('''
                function isClient() return clientMode end
                CVPDynamicCorpses={canSkipMoveInvalidation=function() return true end}
                local old=body:getSquare();local x,y,z=body:getX(),body:getY(),body:getZ()
                local dest=gridSquare(math.floor(x)+1,math.floor(y),z)
                local add=dest.addCorpse
                dest.addCorpse=function() error('injected destination failure') end
                assert(not pcall(World.move,body,x+1,y,z,dest))
                assert(body:getSquare()==old and body:getX()==x and body:getStaticMovingObjectIndex()>=0)
                intact(body)
                dest.addCorpse=add;body.invalidations=0
                World.move(body,x+1,y,z,dest)
                assert(body.invalidations==1 and body:getSquare()==dest)
                World.move(body,x,y,z,old)
                assert(body.invalidations==2 and body:getSquare()==old);intact(body)
            ''')

    def test_native_angle_bridge_is_used_for_commit_and_rollback(self):
        l=environment();l.execute('''
            local calls=0
            CVPWorldNative.setAngle=function(b,angle)
                calls=calls+1
                if b:getAngle()~=angle then b:setForwardDirectionAngle(angle);b:invalidateCorpse() end
            end
            local id=link(C,A,rope);car.x=car.x+.2;Sim:tick(S.graph,S.index,.05,now)
            assert(calls==1)
            local r=Sim.records[id];Sim.pendingPoses={r};Sim:restore()
            assert(calls==2 and body:getAngle()==r.before.angle);intact(body)
        ''')

    def test_commit_reads_coordinates_once_and_cell_once_per_group_sp_mp(self):
        for server in (False,True):
            l=environment();l.globals().serverMode=server;l.execute('''
                function isServer() return serverMode end
                function sendRemoveItemFromContainer() end;function sendAddItemToContainer() end
                link(C,A,rope);link(A,B,chain);Sim:build(S.graph,S.index)
                local group=Sim.groups[1]
                CVPWorldNative.readPoses(CVPWorldNative.beginRead(),group.records)
                local reads={};local originals={}
                for _,r in ipairs(group.records) do
                    r.x=r.before.x+.01
                    local b=r.body;reads[b]={};originals[b]={}
                    for _,name in ipairs({'getX','getY','getZ'}) do
                        local method=b[name];local key=name;originals[b][key]=method
                        b[key]=function(self) reads[self][key]=(reads[self][key] or 0)+1;return method(self) end
                    end
                end
                local cell=getCell;local cellReads=0
                getCell=function() cellReads=cellReads+1;return cell() end
                Sim:apply(group,CVPWorldNative.beginRead())
                getCell=cell;assert(cellReads==1)
                for _,r in ipairs(group.records) do
                    for name,method in pairs(originals[r.body]) do
                        assert(reads[r.body][name]==1,name..' read repeatedly')
                        r.body[name]=method
                    end
                    assert(r.body:getX()==r.x);intact(r.body)
                end
            ''')

    def test_disabled_and_zero_time_restore_before_skipping_preparation_sp_mp(self):
        for server in (False, True):
            for disabled in (False, True):
                l=environment();l.globals().serverMode=server;l.globals().disabled=disabled
                l.execute('''
                    function isServer() return serverMode end
                    function sendRemoveItemFromContainer() end;function sendAddItemToContainer() end
                    local id=link(C,A,rope);Sim:tick(S.graph,S.index,.05,now)
                    local r=Sim.records[id];local x=body:getX()
                    r.before={x=x,y=body:getY(),z=body:getZ(),angle=body:getAngle(),square=body:getSquare()}
                    Sim.pendingPoses={r};r.taut=true;r.loadMass=75;r.spreadSpeed=.2;r.effectTravel=.4
                    Sim.build=function() error('disabled topology preparation') end
                    require('CVP_BodySpread').update=function() error('disabled spread preparation') end
                    require('CVP_LinkObstacles').new=function() error('disabled environment preparation') end
                    SandboxVars.CorpseProxyLab.Enabled=not disabled
                    local native=CVPWorldNative.move;CVPWorldNative.move=function() error('restore temporarily unavailable') end
                    assert(not pcall(Sim.tick,Sim,S.graph,S.index,disabled and .05 or 0,now))
                    assert(Sim.pendingPoses,'disabled towing lost pending rollback')
                    CVPWorldNative.move=native
                    local requests,loads=Sim:tick(S.graph,S.index,disabled and .05 or 0,now)
                    assert(not Sim.pendingPoses and #requests==0 and next(loads)==nil)
                    assert(not r.taut and r.loadMass==0)
                    if disabled then assert(r.spreadSpeed==0 and r.effectTravel==0)
                    else assert(r.spreadSpeed==.2 and r.effectTravel==.4) end
                    assert(body:getX()==x);intact(body)
                ''')

    def test_grouped_reads_match_legacy_poses_loads_and_keep_items_sp_mp(self):
        for server in (False,True):
            results=[]
            for batch in (False,True):
                l=environment(batch);l.globals().serverMode=server
                results.append(l.execute("""
                    function isServer() return serverMode end
                    function sendRemoveItemFromContainer() end;function sendAddItemToContainer() end
                    link(C,A,rope);link(A,B,chain)
                    local values={}
                    for i=1,20 do car.x=car.x+.1;now=now+50
                        local requests,loads=Sim:tick(S.graph,S.index,.05,now)
                        assert(#requests==0)
                        values[#values+1]=string.format('%.17g,%.17g,%.17g,%.17g',body.x,body2.x,body:getAngle(),loads[car] or 0)
                    end
                    intact(body);intact(body2);assert(E.get(S.graph.links[next(S.graph.links)].equipment))
                    if CVPWorldNative.beginRead then assert(readPasses==20 and poseReads==20) end
                    return table.concat(values,';')
                """))
            self.assertEqual(*results)

    def test_read_reuses_validated_body_but_rechecks_next_tick_sp_mp(self):
        for server in (False, True):
            l=environment();l.globals().serverMode=server;l.execute("""
                function isServer() return serverMode end
                function sendRemoveItemFromContainer() end
                function sendAddItemToContainer() end
                link(C,A,rope);link(A,B,chain);Sim:build(S.graph,S.index)
                local resolve=H.body;local reads={};local afterCommit={};local committed=false
                local apply=Sim.apply
                Sim.apply=function(self,group,...)
                    apply(self,group,...);committed=true
                end
                H.body=function(ref,pass)
                    local counts=committed and afterCommit or reads
                    counts[ref.key]=(counts[ref.key] or 0)+1
                    return resolve(ref,pass)
                end
                car.x=car.x+.2;Sim:tick(S.graph,S.index,.05,now)
                assert(reads.A==2 and reads.B==1,'each graph endpoint must resolve once before movement')
                assert(afterCommit.A==1 and afterCommit.B==nil,'resample only the parent endpoint after commit')
                for _,r in pairs(Sim.records) do if r.parent then
                    local current=H.bodyPoint(r.parent.body,r.source.point)
                    assert(r.committedSource.x==current.x and r.committedSource.y==current.y)
                end end
                committed=false
                local sq=body2.sq;local x=body2.x;body2.sq=nil;reads={}
                Sim:tick(S.graph,S.index,.05,now+50)
                assert(reads.B==1 and body2.x==x,'unloaded body must not use previous read')
                body2.sq=sq;car.x=car.x+.2;reads={};Sim:tick(S.graph,S.index,.05,now+100)
                assert(reads.B==1);intact(body);intact(body2)
            """)

    def test_next_group_reads_world_after_previous_commit(self):
        l=environment();l.execute("""
            link(C,A,rope);link(C,B,chain);Sim:build(S.graph,S.index)
            local first=Sim.groups[1].records[1].body;local second=Sim.groups[2].records[1].body
            local apply=Sim.apply;local shifted,observed
            Sim.apply=function(self,group)
                if group==self.groups[2] then
                    observed=group.records[1].before.x
                    assert(observed==shifted,'next group read a pre-commit world')
                end
                apply(self,group)
                if group==self.groups[1] then shifted=second:getX()+.1;move(second,shifted,second:getY()) end
            end
            car.x=car.x+.2;Sim:tick(S.graph,S.index,.05,now)
            assert(observed==shifted);intact(first);intact(second)
        """)

    def test_chain_commits_each_body_once_after_calculation(self):
        for dt in (.016, .1):
            with self.subTest(dt=dt):
                l = environment(); l.globals().dt = dt
                l.execute('''
                    local root=link(C,A,rope);local tail=link(A,B,chain)
                    Sim:tick(S.graph,S.index,dt,now)
                    local native=CVPWorldNative.move;local calls={}
                    local oldX,oldTail=body:getX(),body2:getX()
                    CVPWorldNative.move=function(b,...)
                        calls[b]=(calls[b] or 0)+1
                        return native(b,...)
                    end
                    car.x=car.x+.4;Sim:tick(S.graph,S.index,dt,now)
                    assert(calls[body]==1 and calls[body2]==1)
                    assert(body:getX()>oldX and body2:getX()>oldTail)
                    assert(body:getX()==Sim.records[root].x and body2:getX()==Sim.records[tail].x)
                    intact(body);intact(body2)
                ''')

    def test_second_body_commit_failure_rolls_back_whole_group(self):
        l = environment(); l.execute('''
            link(C,A,rope);link(A,B,chain)
            Sim:tick(S.graph,S.index,.05,now)
            local ax,ay,aa=body:getX(),body:getY(),body:getAngle()
            local bx,by,ba=body2:getX(),body2:getY(),body2:getAngle()
            local native=CVPWorldNative.move;local calls=0
            CVPWorldNative.move=function(...)
                calls=calls+1;if calls==2 then error('injected commit failure') end
                return native(...)
            end
            car.x=car.x+.4;assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now))
            assert(not Sim.pendingPoses)
            assert(body:getX()==ax and body:getY()==ay and body:getAngle()==aa)
            assert(body2:getX()==bx and body2:getY()==by and body2:getAngle()==ba)
            intact(body);intact(body2)
            CVPWorldNative.move=native;Sim:tick(S.graph,S.index,.05,now)
            car.x=car.x+.05;now=now+50;Sim:tick(S.graph,S.index,.05,now)
            assert(body:getX()>ax);intact(body);intact(body2)
        ''')

    def test_rollback_failure_is_retained_and_retried_before_simulation(self):
        l = environment(); l.execute('''
            link(C,A,rope);link(A,B,chain)
            local native=CVPWorldNative.move;local calls=0;local x=body:getX()
            CVPWorldNative.move=function(...)
                calls=calls+1;if calls==2 or calls==3 then error('injected write refusal') end
                return native(...)
            end
            car.x=car.x+.4;assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now))
            assert(Sim.pendingPoses and #Sim.pendingPoses==1 and body:getX()==x)
            intact(body);intact(body2)
            local flush=R.service.flush;local flushes=0
            R.service.flush=function(...) flushes=flushes+1;return flush(...) end
            CVPWorldNative.move=function() error('rollback still unavailable') end
            assert(not R:save() and flushes==0 and Sim.pendingPoses)
            CVPWorldNative.move=native;Sim:tick(S.graph,S.index,.05,now)
            assert(not Sim.pendingPoses);intact(body);intact(body2)
            assert(R:save() and flushes==1)
        ''')

    def test_external_change_during_commit_is_not_overwritten(self):
        l = environment(); l.execute('''
            link(C,A,rope);link(A,B,chain)
            local native=CVPWorldNative.move;local x=body:getX();local calls=0;local external
            CVPWorldNative.move=function(b,...)
                calls=calls+1;local result=native(b,...)
                if calls==1 then
                    external=body2:getX()+.2
                    native(body2,external,body2:getY(),body2:getZ(),body2:getSquare())
                end
                return result
            end
            car.x=car.x+.4;assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now))
            assert(body:getX()==x and body2:getX()==external and not Sim.pendingPoses)
            intact(body);intact(body2)
        ''')

    def test_calculation_failure_leaves_world_untouched_and_can_retry(self):
        l = environment(); l.execute('''
            link(C,A,rope);link(A,B,chain)
            Sim:tick(S.graph,S.index,.05,now)
            local solver=require 'CVP_GroupConstraints';local step=solver.step;local calls=0
            local x,y=body:getX(),body2:getX()
            solver.step=function(...)
                calls=calls+1;if calls==2 then error('injected calculation failure') end
                return step(...)
            end
            car.x=car.x+.4;assert(not pcall(Sim.tick,Sim,S.graph,S.index,.05,now))
            assert(body:getX()==x and body2:getX()==y and Sim.calculating)
            solver.step=step;Sim:tick(S.graph,S.index,.05,now)
            assert(not Sim.calculating and not Sim.pendingPoses)
            car.x=car.x+.05;now=now+50;Sim:tick(S.graph,S.index,.05,now)
            assert(body:getX()>x)
            intact(body);intact(body2)
        ''')

    def test_slow_anchor_moves_chain_and_it_settles_after_stop(self):
        l=environment();l.execute('''
            link(C,A,rope);link(A,B,chain);Sim:tick(S.graph,S.index,.05,now)
            local x,y=body:getX(),body2:getX()
            for i=1,20 do car.x=car.x+.01;now=now+50;Sim:tick(S.graph,S.index,.05,now) end
            assert(body:getX()>x+.1 and body2:getX()>y+.1)
            local stopped,tail=body:getX(),body2:getX()
            for i=1,100 do now=now+50;Sim:tick(S.graph,S.index,.05,now) end
            -- Keep the existing short-stop displacement bound, then also check
            -- that motion has substantially settled in the following second.
            assert(math.abs(body:getX()-stopped)<.051 and math.abs(body2:getX()-tail)<.051)
            local settled,settledTail=body:getX(),body2:getX()
            for i=1,20 do now=now+50;Sim:tick(S.graph,S.index,.05,now) end
            assert(math.abs(body:getX()-settled)<.002 and math.abs(body2:getX()-settledTail)<.002)
            -- Static friction must release when the vehicle pulls again.
            local restart,restartTail=body:getX(),body2:getX()
            for i=1,30 do car.x=car.x+.01;now=now+50;Sim:tick(S.graph,S.index,.05,now) end
            assert(body:getX()>restart+.1 and body2:getX()>restartTail+.1)
            intact(body);intact(body2)
        ''')


if __name__ == '__main__':
    unittest.main()
