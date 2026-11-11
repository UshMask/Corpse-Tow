"""Native-resource presentation: cancellations cannot mutate tethers or send RPCs."""
from pathlib import Path
import unittest
from test_multiplayer import vm


def single_player():
    from legacy_fixture import create_legacy_fixture
    env = create_legacy_fixture()
    lua = env['L']
    lua.execute(env['source'])
    lua.execute('''
        sounds={};stops={}
        player.playSound=function(_,name) sounds[#sounds+1]=name;return #sounds end
        player.stopOrTriggerSound=function(_,id) stops[#stops+1]=id end
        deferAction=true
    ''')
    return lua


class StockVisualTests(unittest.TestCase):
    def test_attach_sound_cancel_and_perform_only(self):
        lua = single_player()
        lua.execute('''
            menu();click('(верёвка)');local a=queued;a:start()
            assert(#sounds==0 and not body.md.CVPTether)
            a:stop();a:perform();assert(#stops==0 and rope.owner==storage and not body.md.CVPTether)
            menu();click('(верёвка)');a=queued;a:start();a:perform();a:perform();assert(not body.md.CVPTether)
            a=queued;a:start();a:perform();a:perform()
            assert(#CVPTest.links()==1 and rope.owner==CVPEquipmentRuntime.container and #stops==0)
        ''')

    def test_chain_detach_cancellation_and_changed_vehicle(self):
        lua = single_player()
        lua.execute('''
            player:getModData().CVPMaterial='Base.HeavyChain';menu();click('(цепь)');local a=queued;a:start();a:complete();a:perform();a=queued;a:start();a:complete();a:perform()
            assert(#sounds==0 and #CVPTest.links()==1)
            menu();click(getText('IGUI_CVP_DetachNumber',1));a=queued;a:start()
            assert(#sounds==0 and chain.owner==CVPEquipmentRuntime.container)
            a:forceCancel();a:perform();assert(#CVPTest.links()==1 and chain.owner==CVPEquipmentRuntime.container)
            menu();click(getText('IGUI_CVP_DetachNumber',1));a=queued;a:start()
            speed=2;a:perform();assert(#CVPTest.links()==1 and chain.owner==CVPEquipmentRuntime.container)
            speed=0;menu();click(getText('IGUI_CVP_DetachNumber',1));a=queued;a:start();a:perform()
            assert(#CVPTest.links()==0 and chain.owner==storage and #stops==0)
        ''')

    def test_dormant_detach_does_not_release_replaced_tether(self):
        lua = single_player()
        lua.execute('''
            deferAction=false;menu();click('(верёвка)');local old=CVPRuntime.links[1];require('CVP_Core').unregister(CVPRuntime.registry,old)
            deferAction=true;menu();click(getText('IGUI_CVP_Detach'));local a=queued;a:start()
            CVPTest.stop(old,'replacement');CVPTest.attach(player,body,car,chain)
            local replacement=body.md.CVPTether;a:perform()
            assert(body.md.CVPTether==replacement and chain.owner==CVPEquipmentRuntime.container and rope.owner==storage)
        ''')

    def test_native_feet_facing(self):
        lua = single_player()
        lua.execute('''
            Vector2f={new=function() return {} end}
            body.getGrabLegsPosition=function() return {x=function() return .75 end,y=function() return .2 end} end
            player.faceLocationF=function(_,x,y) facingX=x;facingY=y end
            menu();click('(верёвка)');queued:waitToStart();queued:update()
            assert(facingX==.75 and facingY==.2)
        ''')

    def test_mp_waits_until_finish_and_never_edits_items(self):
        lua = vm(False)
        lua.execute('''
            deferAction=true
            CVPMPClient.queueAction('attach',player,body,car,rope)
            local a=queued;a:start();assert(#clientPackets==0 and rope.owner==storage)
            a:stop();a:perform();assert(#clientPackets==0)
            CVPMPClient.queueAction('attach',player,body,car,rope);a=queued;a:start()
            assert(rawget(getmetatable(a),'complete')==nil,'must not register a native server timed action')
            a:perform();a:perform();assert(#clientPackets==0)
            a=queued;a:start();a:perform();a:perform();assert(#clientPackets==1 and clientPackets[1].name=='attach')
            assert(rope.owner==storage and not body.md.CVPTether)
            CVPMPClient.queueAction('attach',player,body,car,rope);a=queued;a:start()
            speed=10;a:perform();assert(#clientPackets==1)
        ''')

    def test_mesh_budget_winding_and_atlas_uv(self):
        import math
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('tether_meshes', 'tools/build_tether_meshes.py')
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        meshes = {}
        module.save = lambda name, vertices, faces: meshes.update({name: (vertices, faces)})
        module.rope(); module.chain()
        self.assertEqual(set(meshes), {'CVPRopeSegment', 'CVPChainSegment'})
        for name, (vertices, faces) in meshes.items():
            self.assertTrue(vertices and faces, name + ' must contain geometry')
            self.assertLessEqual(len(faces), 288, 'static mesh budget per existing draw entry')
            for position, normal, uv in vertices:
                self.assertTrue(all(math.isfinite(v) for v in position+normal+uv))
                self.assertAlmostEqual(sum(v*v for v in normal), 1, places=6)
                self.assertTrue(all(0<v<1 for v in uv))
            for a,b,c in faces:
                self.assertTrue(all(0 <= i < len(vertices) for i in (a,b,c)))
                p,q,r = [vertices[i][0] for i in (a,b,c)]
                u,v = [q[i]-p[i] for i in range(3)], [r[i]-p[i] for i in range(3)]
                cross = (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
                self.assertGreater(sum(cross[i]*vertices[a][1][i] for i in range(3)), 0)

        vertices, faces = meshes['CVPRopeSegment']
        # Match the actual boundary, independent of vertex order, UV duplicates,
        # number of sides, or extra longitudinal rings.
        def point_key(position):
            return tuple(round(v, 7) for v in position)

        from collections import Counter
        edges = Counter()
        for face in faces:
            points = [point_key(vertices[i][0]) for i in face]
            for a,b in zip(points, points[1:]+points[:1]):
                edges[tuple(sorted((a,b)))] += 1
        for (a,b), count in edges.items():
            self.assertIn(count, (1,2), 'non-manifold rope mesh')
            if count == 1:
                self.assertEqual(a[1], b[1], 'open longitudinal seam')
                self.assertIn(a[1], (0,1), 'hole inside rope segment')
        start = {point_key(p)[::2] for p,_,_ in vertices if abs(p[1])<1e-7}
        end = {point_key(p)[::2] for p,_,_ in vertices if abs(p[1]-1)<1e-7}
        self.assertTrue(start and end, 'mesh must reach both attachment planes')
        self.assertEqual(start, end, 'repeated segments must join without gaps')
        for position, normal, uv in vertices:
            self.assertLessEqual(math.hypot(position[0],position[2]), 1)
            self.assertGreaterEqual(position[1],0)
            self.assertLessEqual(position[1],1)


if __name__ == '__main__':
    unittest.main()
