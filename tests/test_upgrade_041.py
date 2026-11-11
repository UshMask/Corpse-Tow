"""Published 0.4.1 -> current source, fresh Lua VMs and exact equipment payloads.

The world/inventory persistence is an engine model, not a live game restart.
"""
from pathlib import Path
import hashlib
import json
import unittest
from test_link_simulation import environment
from test_link_graph import plain

OLD = Path('releases/0.4.1/Workshop/Contents/mods/CorpseProxyLab/42/media/lua')
CURRENT = Path('CorpseProxyLab/42/media/lua')


def version(root, saved=None, poses=None):
    l=environment()
    l.execute('''
        for name in pairs(package.loaded) do
            if string.sub(name,1,4)=='CVP_' then package.loaded[name]=nil end
        end
        CVPEquipmentRuntime=nil
    ''')
    for directory in ('shared','client'):
        for path in (root/directory).glob('CVP_*.lua'):
            l.execute('package.preload[...]=assert(loadstring(select(2,...)))',path.stem,path.read_text(encoding='utf-8-sig'))
    if saved is not None:
        l.globals().saved=l.table_from(saved,recursive=True)
        l.execute('loadEquipment(saved);storage:Remove(rope);storage:Remove(chain)')
    l.execute('''
        E=require 'CVP_Equipment';G=require 'CVP_LinkGraph';World=require 'CVP_World'
        H=require('CVP_LinkHost').new();H.discover();H.actor(player)
        CVPSkeletonNative={version=function() return '2-graph-clocks' end,sync=function() end,retire=function() return false end}
        R=require('CVP_LinkRuntime').new(H);assert(R:start());S=R.service;Sim=R.simulation
        function run() now=now+50;assert(R:tick({player},.05)) end
    ''')
    if poses is not None:
        l.globals().poses=l.table_from(poses,recursive=True)
        l.execute('''
            for i,b in ipairs({body,body2}) do
                local p=poses[i];move(b,p.x,p.y);b.angle=p.angle
                b.inv=container();b.inv.parent=b
                for _,payload in ipairs(p.loot) do b.inv:AddItem(equipmentDecode(payload)) end
            end
        ''')
    return l


def snapshot(l):
    l.execute('''
        assert(R:save());poses={}
        for i,b in ipairs({body,body2}) do
            local loot={};local items=b.inv:getItems()
            for n=0,items:size()-1 do loot[#loot+1]=equipmentEncode(items:get(n)) end
            poses[i]={x=b.x,y=b.y,angle=b.angle or 0,loot=loot}
        end
    ''')
    return plain(l.eval('serializeEquipment()')),plain(l.globals().poses)


class Upgrade041Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release=Path('releases/0.4.1')
        rows=json.loads((release/'manifest.json').read_text())
        for row in rows:
            data=(release/'Workshop'/row['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest()==row['sha256'],row['path']

    def test_published_equipment_survives_upgrade_restart_and_exact_single_return(self):
        for kind in ('attached','ground','held'):
            with self.subTest(kind=kind):
                old=version(OLD);old.globals().kind=kind
                old.execute('''
                    rope.custom='original rope';rope.state={condition=31,wetness=.7};rope.md={nested={tag='rope-041'}}
                    chain.custom='original chain';chain.state={condition=67};chain.md={nested={tag='chain-041'}}
                    body.inv:getItems():get(0).md={playerLoot={name='kept',values={1,2,3}}}
                    body2.inv:getItems():get(0).custom='player watch'
                    expected={equipmentEncode(rope),equipmentEncode(chain)}
                    root=link(C,A,rope);tail=link(A,B,chain)
                    if kind~='attached' then edit(root,'release','a') end
                    if kind=='held' then edit(root,'take','a') end
                    graphBefore=equipmentCopy(S.graph)
                ''')
                expected=list(old.globals().expected.values())
                graph=plain(old.globals().graphBefore)
                saved,poses=snapshot(old)
                new=version(CURRENT,saved,poses)
                for key,row in graph['links'].items():
                    actual=new.globals().S.graph.links[key]
                    self.assertEqual(row['equipment'],actual.equipment)
                    self.assertEqual(row['length'],actual.length)
                    self.assertEqual(row['owner'],actual.owner)
                    # Saving releases a carried end onto the ground, retaining the link/item.
                    self.assertEqual('ground' if kind=='held' and row['a']['kind']=='held' else row['a']['kind'],actual.a.kind)
                    self.assertIsNone(actual.allocation,'legacy individual items must not silently become pooled')
                new.execute('''
                    run();assert(R:save())
                    for _,b in ipairs({body,body2}) do intact(b) end
                ''')
                saved2,poses2=snapshot(new)
                self.assertEqual(poses[1]['loot'],poses2[1]['loot'])
                self.assertEqual(poses[2]['loot'],poses2[2]['loot'])
                reloaded=version(CURRENT,saved2,poses2)
                reloaded.execute('''
                    local rows={};for id,row in pairs(S.graph.links) do rows[#rows+1]={id=id,revision=row.revision} end
                    for _,entry in ipairs(rows) do
                        local row=S.graph.links[entry.id];beside(row.a)
                        assert(R:command(player,{id=entry.id,revision=row.revision,side='a',op='remove'}))
                        assert(not R:command(player,{id=entry.id,revision=entry.revision,side='a',op='remove'}))
                    end
                    assert(next(S.graph.links)==nil);assert(R:save())
                    returned={};local items=storage:getItems()
                    for i=0,items:size()-1 do returned[#returned+1]=equipmentEncode(items:get(i)) end
                    intact(body);intact(body2)
                ''')
                self.assertCountEqual(expected,list(reloaded.globals().returned.values()))


if __name__=='__main__':
    unittest.main()
