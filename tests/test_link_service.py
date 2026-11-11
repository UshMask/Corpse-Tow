"""Authoritative commands use loaded targets, real item ownership and disk CAS."""
from pathlib import Path
import unittest
from test_link_graph import environment, plain

SOURCE=Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkService.lua').read_text(encoding='utf-8-sig')


def service(saved=None):
    l=environment(saved,storage=True)
    l.globals().serviceSource=SOURCE
    l.execute('''
        Service=assert(loadstring(serviceSource))()
        player.x=0;player.y=0;player.z=0;player.alive=true;player.onFoot=true
        other={key='other-player',x=3,y=0,z=0,alive=true,onFoot=true,others=true}
        targets={A=bodyEnd('A'),B=bodyEnd('B',3),car=carEnd('car',3)}
        enabled=true;limit=32;blocked=false;clock=0;ids=0
        host={now=function() return clock end,uuid=function() ids=ids+1;return 'link-id-'..ids end,
            actor=function(p) return {key=p.key,x=p.x,y=p.y,z=p.z,alive=p.alive,onFoot=p.onFoot,allowOthers=p.others} end,
            enabled=function() return enabled end,maxBodies=function() return limit end,
            canReach=function(p,e) return not blocked end,
            resolve=function(ref,p)
                if type(ref)~='table' then return nil,'invalid target' end
                if ref.kind=='ground' then return ground(p.x,p.y,p.z) end
                local target=targets[ref.key]
                if not target or target.kind~=ref.kind or target.moving then return nil,'unavailable target' end
                return clone(target)
            end,
            sample=function(e,p)
                if e.kind=='ground' then return clone(e) end
                if e.kind=='held' then
                    local actor=e.holder==player.key and player or other
                    return ground(actor.x,actor.y,actor.z)
                end
                return targets[e.key] and clone(targets[e.key])
            end,
            item=function(p,id) if stowed==false then return end;return p.inv and p.inv:getItemWithID(id) end,
            inventory=function(p) return p.inv end,transfer=transfer}
        host.actionSample=function(ref) return host.sample(ref) end
        S=Service.new(E,host);assert(S:load())
        function create(second)
            player.x=0;local token=assert(S:prepare(player,{kind='body',key='A'},42))
            player.x=3;local ok,id=S:create(player,token,second or {kind='ground'})
            assert(ok,id);linkID=id;return id
        end
        function command(op,side,target,p)
            return S:command(p or player,{op=op,id=linkID,revision=S.graph.links[linkID].revision,side=side or 'b',target=target})
        end
    ''')
    return l


class LinkServiceTests(unittest.TestCase):
    def test_two_endpoint_sequence_uses_authoritative_positions_and_original_item(self):
        l=service();l.execute('''
            local token=assert(S:prepare(player,{kind='body',key='A',x=999,y=999},42))
            player.x=3
            local ok,id=S:create(player,token,{kind='body',key='B',x=999,y=999})
            assert(ok and E.links().links[id].a.x==0 and E.links().links[id].b.x==3)
            assert(E.get(E.links().links[id].equipment)==original and #source.rows==0)
            assert(not S:create(player,token,{kind='body',key='B'}))
        ''')

    def test_prepare_requires_reachable_first_endpoint_and_stowed_material(self):
        for setup in ('player.x=20','blocked=true','player.alive=false','player.onFoot=false','enabled=false','stowed=false'):
            with self.subTest(setup=setup):
                l=service();l.execute(setup+''';assert(not S:prepare(player,{kind='body',key='A'},42))
                    assert(original.owner==source and transfers==0)''')

    def test_expired_or_moved_first_endpoint_cannot_complete(self):
        for setup in ('clock=120001','targets.A.x=1.01','targets.A=nil','player.x=20','blocked=true','player.onFoot=false','stowed=false'):
            with self.subTest(setup=setup):
                l=service();l.execute('''token=assert(S:prepare(player,{kind='body',key='A'},42));player.x=3;'''+setup+'''
                    assert(not S:create(player,token,{kind='body',key='B'}))
                    assert(original.owner==source and transfers==0 and next(E.links().links)==nil)''')

    def test_ground_end_cannot_be_taken_through_wall_or_from_another_floor(self):
        for setup in ('blocked=true','player.x=30','player.z=1'):
            l=service();l.execute('create();'+setup+''';assert(not command('take'))
                assert(E.links().links[linkID].b.kind=='ground')''')

    def test_take_walk_drop_and_rebind_preserves_item(self):
        l=service();l.execute('''
            create();assert(command('take'));local material=E.links().links[linkID].equipment
            player.x=8;clock=100
            assert(S:tick({[linkID]={a=targets.A,b=ground(8)}},{[player.key]=true}))
            assert(S.graph.links[linkID].length==8 and S.dirty)
            assert(command('drop'));assert(E.links().links[linkID].b.kind=='ground' and E.links().links[linkID].b.x==8)
            targets.car.x=8
            assert(command('bind','b',{kind='vehicle',key='car',x=99}))
            assert(E.links().links[linkID].b.key=='car' and E.get(material)==original and transfers==1)
        ''')

    def test_failed_binding_never_restores_manually_released_attachment(self):
        l=service();l.execute('''
            create({kind='body',key='B'});assert(command('release'))
            blocked=true;assert(not command('bind','b',{kind='vehicle',key='car'}));blocked=false
            assert(E.links().links[linkID].b.kind=='ground')
            assert(command('remove') and original.owner==source and next(E.links().links)==nil)
        ''')

    def test_bind_requires_loaded_opposite_end_and_fits_its_current_position(self):
        l=service();l.execute('''
            create();local a=targets.A;targets.A=nil
            assert(not command('bind','b',{kind='vehicle',key='car'}))
            assert(E.links().links[linkID].b.kind=='ground')
            targets.A=a;a.x=-2
            assert(command('bind','b',{kind='vehicle',key='car'}))
            assert(E.links().links[linkID].length==5)
        ''')

    def test_delayed_lifecycle_release_cannot_undo_new_player_binding(self):
        l=service();l.execute('''
            create({kind='body',key='B'});local row=S.graph.links[linkID]
            local pending={{id=linkID,revision=row.revision,side='b',where=row.b}}
            assert(command('release'));assert(command('bind','b',{kind='vehicle',key='car'}))
            assert(S:releaseSystem(pending))
            assert(S.graph.links[linkID].b.kind=='vehicle')
        ''')

    def test_two_lifecycle_releases_from_same_observation_both_apply(self):
        l=service();l.execute('''
            create({kind='body',key='B'});local row=S.graph.links[linkID]
            assert(S:releaseSystem({{id=linkID,revision=row.revision,side='a',where=row.a},
                {id=linkID,revision=row.revision,side='b',where=row.b}}))
            assert(S.graph.links[linkID].a.kind=='ground' and S.graph.links[linkID].b.kind=='ground')
            assert(E.get(S.graph.links[linkID].equipment)==original)
        ''')

    def test_remote_competing_or_stale_command_cannot_take_end(self):
        l=service();l.execute('''
            create();local revision=S.graph.links[linkID].revision;assert(command('take'))
            assert(not S:command(other,{op='take',id=linkID,revision=revision,side='b'}))
            assert(not command('drop','b',nil,other))
            assert(not command('remove','b',nil,other))
            assert(E.links().links[linkID].b.holder==player.key)
        ''')

    def test_disabled_block_preserves_links_and_allows_release_and_return(self):
        l=service();l.execute('''
            create({kind='body',key='B'});enabled=false
            assert(command('release'));assert(not command('take'))
            assert(not command('bind','b',{kind='vehicle',key='car'}))
            assert(command('remove') and original.owner==source)
        ''')

    def test_motion_is_saved_in_batches_and_write_failure_retries_with_backoff(self):
        l=service();l.execute('''
            create();assert(command('take'));local before=writes
            for i=1,60 do clock=i*10;player.x=3+i/100
                assert(S:tick({[linkID]={a=targets.A,b=ground(player.x)}},{[player.key]=true}))
            end
            assert(writes==before and S.dirty)
            failWrite=true;clock=2001
            assert(not S:tick({[linkID]={a=targets.A,b=ground(player.x)}},{[player.key]=true}))
            local failed=writes
            for i=1,60 do clock=2001+i*10
                assert(S:tick({[linkID]={a=targets.A,b=ground(player.x)}},{[player.key]=true}))
            end
            assert(writes==failed and S.dirty)
            failWrite=false;clock=7002
            assert(S:tick({[linkID]={a=targets.A,b=ground(player.x)}},{[player.key]=true}))
            assert(not S.dirty and E.links().links[linkID].b.x==player.x)
        ''')

    def test_attached_motion_keeps_saved_snapshot_and_survives_failed_save(self):
        l=service();l.execute('''
            create({kind='body',key='B'})
            local live=S.graph.links[linkID];local saved=E.links()
            local index=S.index;local revision=live.revision;local equipment=live.equipment
            clock=100
            assert(S:tick({[linkID]={a=ground(1),b=ground(4)}},{}))
            assert(S.graph.links[linkID]==live and S.index==index and S.dirty)
            assert(saved.links[linkID].a.x==0 and E.links().links[linkID].a.x==0)
            failWrite=true;clock=2001
            assert(not S:tick({[linkID]={a=ground(2),b=ground(5)}},{}))
            assert(S.dirty and E.links().links[linkID].a.x==0)
            failWrite=false;clock=7002
            assert(S:tick({[linkID]={a=ground(3),b=ground(6)}},{}))
            assert(not S.dirty and E.links().links[linkID].a.x==3)
            local reloaded=Service.new(E,host);assert(reloaded:load())
            assert(reloaded.graph.links[linkID].b.x==6)
            assert(reloaded.graph.links[linkID].revision==revision)
            assert(E.get(equipment)==original)
            assert(command('remove'))
            assert(original.owner==source and next(E.links().links)==nil)
        ''')

    def test_overreach_saves_drop_immediately_without_inventory_transfer(self):
        l=service();l.execute('''
            create();assert(command('take'));player.x=20;clock=1;local before=transfers
            assert(S:tick({[linkID]={a=targets.A,b=ground(20)}},{[player.key]=true}))
            assert(not S.dirty and E.links().links[linkID].b.kind=='ground')
            assert(player.x==20 and targets.A.x==0 and transfers==before)
        ''')

    def test_disconnect_and_fresh_world_remove_holder_claim(self):
        first=service();first.execute('create();assert(command("take"))')
        second=service(plain(first.globals().persisted))
        second.execute("assert(next(S.index.held)==nil);assert(E.links().links['link-id-2'].b.kind=='ground')")
        first.execute('''
            assert(S:disconnect(player.key))
            assert(E.links().links[linkID].b.kind=='ground' and next(S.index.held)==nil)
        ''')


if __name__=='__main__':unittest.main()
