"""Explicit pre-graph controller harness; never loaded by current test fixtures."""
from pathlib import Path
import json
import re
from lua_fixture import create_world


def legacy_operations(name, source):
    """Keep historical methods in their original lexical scope, outside shipped Lua."""
    if name not in ('Connection', 'Equipment'):
        return source
    result = 'Connection' if name == 'Connection' else 'E'
    end = 'return ' + result
    assert source.rstrip().endswith(end)
    operations = Path('tests/fixtures/v031', name.lower() + '_operations.lua').read_text()
    return source.rstrip()[:-len(end)] + operations + end + '\n'


def create_legacy_fixture():
    L=create_world()
    root=Path('CorpseProxyLab/42/media/lua/client')
    archived={'Audio','Batch','Core','Rewire','RewireAction','TieSequence','Viewpoint'}
    shared=('Plow','Horse','Blood','Legacy','LinkObstacles','Geometry','Rope','Load',
            'AttachAction','Connection','SaveJobs','EquipmentData','Equipment','LinkClocks','World','Feedback','Menu')
    for name in shared:
        file='CVP_'+name+'.lua'
        path=root/file
        if not path.exists(): path=root.parent/'shared'/file
        L.execute("package.preload[...]=assert(loadstring(select(2,...)))",'CVP_'+name,
                  legacy_operations(name, path.read_text(encoding='utf-8-sig')))
    # The archived controller used a raw position setter during its own rollback.
    # Keep that historical API here, not in the shipped World module.
    L.execute('''
        local World=require 'CVP_World'
        function World.position(b,x,y,z,sq)
            b:setX(x);b:setY(y);b:setZ(z);b:setSquare(sq);b:setCurrent(sq)
        end
    ''')
    for name in sorted(archived):
        L.execute("package.preload[...]=assert(loadstring(select(2,...)))",'CVP_'+name,
                  Path('tests/fixtures/v031','CVP_'+name+'.lua').read_text(encoding='utf-8-sig'))
    # Pre-0.4 controller exercises legacy saves and shared modules. Current entry
    # points are exercised separately by test_link_client, never by this fixture.
    source=Path('tests/fixtures/v031/CVP_Client.lua').read_text(encoding='utf-8-sig')
    keys=set(re.findall(r"'((?:IGUI_CVP_)[A-Za-z]+)'",source))
    for language in ('EN','RU'):
     catalog=json.loads(Path(f'CorpseProxyLab/42/media/lua/shared/Translate/{language}/IG_UI.json').read_text(encoding='utf-8'))
     assert keys<=set(catalog), (language,keys.symmetric_difference(catalog))
    L.execute(Path('tests/fixtures/v031/menu_adapter.lua').read_text())
    L.execute("function releaseAll() for i=#CVPTest.links(),1,-1 do CVPTest.stop(CVPTest.links()[i],'test') end end")
    return {'L':L,'source':source}


def install_migration_seed(lua):
    """Generate old metadata through the archived core, without replacing current modules."""
    lua.execute("package.preload.CVP_LegacyCore=assert(loadstring(...))", Path('tests/fixtures/v031/CVP_Core.lua').read_text())
    lua.execute('''
        function legacy(version)
            local core=require 'CVP_LegacyCore';local registry=core.registry({})
            local md=core.metadata(World.vehicleKey(car),rope,1,'feet',body);md.owner='player'
            core.fitLength(body,car,rope,md)
            local parent=core.link(body,car,rope,md)
            if version==2 then
                md.version=2;storage:Remove(rope);body.inv:AddItem(rope);body.md.CVPTether=md
            else assert(core.attach(body,rope,md,function() end)) end
            core.register(registry,parent)
            local tail=core.childMetadata(parent,body2,chain,2,'feet');tail.owner='player'
            core.fitLength(body2,car,chain,tail,parent)
            local record=core.link(body2,car,chain,tail,parent)
            if version==2 then
                tail.version=2;storage:Remove(chain);body2.inv:AddItem(chain);body2.md.CVPTether=tail
            else assert(core.attach(body2,chain,tail,function() end)) end
            core.register(registry,record);H.discover()
            return md,tail
        end
    ''')
