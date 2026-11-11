"""Exercise orchestration without launching or contacting a game client."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import performance_series as runner


class SeriesRunnerTests(unittest.TestCase):
    def test_frozen_build_ignores_worktree_mod_edits_but_not_runner_changes(self):
        values={'CorpseProxyLab/42/a.lua':'a','CorpseProxyViewpoint\\42\\b.lua':'b','tools/pz-test/client.py':'c'}
        with patch.object(runner,'fingerprint',return_value=values):
            self.assertEqual(runner.source_fingerprint(runner.ROOT),values)
            self.assertEqual(runner.source_fingerprint(runner.ROOT/'local/frozen'),{'tools/pz-test/client.py':'c'})
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for mod in ('CorpseProxyLab','CorpseProxyViewpoint'):
                (root/mod/'42').mkdir(parents=True);(root/mod/'common').mkdir()
                (root/mod/'42/mod.info').write_text('id=test')
            original=runner.build_files(root)
            (root/'CorpseProxyLab/42/mod.info').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'build changed'):
                runner.verify_build(root,root,original)

    def test_unresponsive_bridge_stops_only_verified_test_client(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        bridge=Mock();bridge.lock.side_effect=lambda:nullcontext()
        bridge.request.side_effect=TimeoutError('no reply')
        with patch.object(runner.subprocess,'run') as terminate:
            runner.stop_failed_client(bridge,Path('isolated-runtime'))
        script=terminate.call_args.args[0][-1]
        self.assertIn('CreationDate',script)
        self.assertIn("'-cachedir='+$cache",script)
        self.assertIn('identity mismatch',script)
        self.assertIn('Stop-Process -Id $p.ProcessId',script)
        self.assertEqual(terminate.call_args.kwargs['timeout'],20)

    def run_series(self,mode,lost_rope=False,game_profiler=False,jfr=False,report_failure=False,launch_failure=False,assets=None):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);output=root/'result';commands=[]
            seed=root/'local/test-worlds/performance-32-v2';seed.mkdir(parents=True)
            (seed/'manifest.json').write_text('{"archive_sha256":"fixture"}')
            lua=root/'CorpseTowPerf-On/cache/Lua';lua.mkdir(parents=True)
            map_root=root/'CorpseTowPerf-On/cache/mods/PZTProvingGround/42/media/maps/PZT_ProvingGround'
            map_root.mkdir(parents=True)
            for i in range(10): (map_root/f'world_0_{i}.lotpack').write_bytes(b'map fixture')

            class Bridge:
                session='one-client'
                last_id='drive'
                def __init__(self,*args):pass
                def lock(self):
                    from contextlib import nullcontext
                    return nullcontext()
                def request(self,name,arg=''):
                    commands.append((name,arg))
                    if name=='perf.environment':return dict(debug=False,gameProfiler=False,mapHeaders=10)
                    if name=='perf.series.adopt':return dict(ready=True,count=32,uncapped=True)
                    if name=='scene.drive':
                        self.mode=arg
                        for suffix in ('.txt','-present.txt'):(lua/('PZTDrive-drive'+suffix)).write_text('samples')
                    if name=='perf.series.clear':return dict(returned=31 if lost_rope else 32,count=32,clearedSquares=100)
                    return {}
                def wait(self,ident):
                    row=dict(movedBodies=32,seconds=20,warmupSeconds=10,mode=self.mode)
                    if self.mode=='acceptance':row['settling']={'seconds':15}
                    return row

            argv=['performance_series.py','--mode',mode,'--output',str(output)]
            if assets: argv += ['--assets', assets]
            if game_profiler: argv.append('--game-profiler')
            if jfr: argv.append('--jfr')
            @contextmanager
            def stock_recording(*args):
                commands.append(('gameprofiler.start',''))
                try: yield
                finally: commands.append(('gameprofiler.stop',''))
            @contextmanager
            def recording(*args):
                commands.append(('jfr.start',''))
                try: yield
                finally: commands.append(('jfr.stop',''))
            original_write=Path.write_text
            def write(path,*args,**kwargs):
                if report_failure and path.name=='failure.json': raise OSError('disk full')
                return original_write(path,*args,**kwargs)
            with patch.object(Path,'write_text',write),patch.object(sys,'argv',argv),patch.dict(runner.os.environ,{'LOCALAPPDATA':str(root)}), \
                 patch.multiple(runner,ROOT=root,Bridge=Bridge,stopped=lambda:True,restore=lambda *a,**kw:None,
                     ready=lambda *a:None,return_ready=lambda *a:{'ready':True},wait_exit=lambda:None,
                     fingerprint=lambda:{'source':'unchanged'},record_jfr=recording,record_gameprofiler=stock_recording,presented_metadata=lambda *a,**k:None,
                     summarize=lambda *a:{'fps':60}), \
                 patch.object(runner.os,'chdir'),patch.object(runner.subprocess,'run') as launch, \
                 patch('performance_journal.completed') as completed:
                if launch_failure:
                    launch.side_effect=RuntimeError('launcher failed')
                    with self.assertRaisesRegex(RuntimeError,'launcher failed'): runner.main()
                    self.assertEqual(commands,[])
                    completed.assert_not_called()
                    rows=[]
                elif lost_rope:
                    with self.assertRaises(AssertionError):runner.main()
                    completed.assert_not_called()
                    self.assertEqual((output/'failure.json').exists(),not report_failure)
                    self.assertNotIn(('perf.series.quit',''),commands)
                    self.assertIn(('perf.series.abort',''),commands)
                    self.assertLess(commands.index(('perf.series.abort','')),commands.index(('perf.series.inspect','')))
                    rows=[]
                else:
                    runner.main();completed.assert_called_once()
                    rows=json.loads((output/'results.json').read_text())
                launch.assert_called_once()
                command=launch.call_args.args[0]
                if assets:
                    self.assertEqual(command[command.index('-BenchmarkAssets')+1],str(Path(assets).resolve()))
                else:
                    self.assertNotIn('-BenchmarkAssets',command)
            return commands,rows

    def test_modes_reuse_one_client_and_only_diagnostics_instrument(self):
        for mode in ('fps','diagnostic','acceptance'):
            with self.subTest(mode=mode):
                commands,rows=self.run_series(mode)
                n=1 if mode=='acceptance' else 2 if mode=='fps' else 3
                self.assertEqual(len(rows),n)
                self.assertEqual(commands.count(('scene.drive',mode)),n)
                self.assertEqual(commands.count(('perf.series.clear','')),n)
                self.assertEqual(commands.count(('perf.profile.begin','')),n if mode=='diagnostic' else 0)
                self.assertEqual(commands.count(('perf.profile.end','')),n if mode=='diagnostic' else 0)
                self.assertEqual(commands.count(('jfr.start','')),0)
                self.assertEqual(commands.count(('jfr.stop','')),0)
                self.assertEqual({r['session'] for r in rows},{'one-client'})
                self.assertTrue(all(r['test_mode']==mode and r['seed']=='fixture' for r in rows))

    def test_custom_assets_reach_launcher(self):
        self.run_series('fps',assets='custom assets')

    def test_launcher_failure_does_not_contact_previous_client(self):
        self.run_series('fps',launch_failure=True)

    def test_report_write_failure_still_stops_client(self):
        commands,_=self.run_series('fps',lost_rope=True,report_failure=True)
        self.assertIn(('perf.series.abort',''),commands)

    def test_material_loss_stops_series_before_next_trip(self):
        for mode in ('fps','diagnostic','acceptance'):
            commands,_=self.run_series(mode,lost_rope=True)
            self.assertEqual(commands.count(('scene.drive',mode)),1)

    def test_stock_profiler_opt_in_and_separate_protocol(self):
        commands,rows=self.run_series('diagnostic',game_profiler=True)
        self.assertEqual(commands.count(('gameprofiler.start','')),3)
        self.assertEqual(commands.count(('gameprofiler.stop','')),3)
        self.assertTrue(all(r['protocol'].endswith('-gameprofiler1') for r in rows))
        commands,_=self.run_series('diagnostic')
        self.assertNotIn(('gameprofiler.start',''),commands)

    def test_jfr_does_not_enable_lua_wrappers(self):
        commands,rows=self.run_series('fps',jfr=True)
        self.assertEqual(commands.count(('jfr.start','')),2)
        self.assertEqual(commands.count(('jfr.stop','')),2)
        self.assertNotIn(('perf.profile.begin',''),commands)
        self.assertTrue(all(r['profiling'] and '-jfr2-' in r['protocol'] for r in rows))

    def test_fast_config_warms_only_first_trip(self):
        commands,rows=self.run_series('fps')
        self.assertEqual([arg.split() for name,arg in commands if name=='perf.series.config'],
                         [['Tow','fast','0'],['Tow','fast','1']])
        self.assertTrue(all(r['preset']=='fast' for r in rows))

    def test_stock_profiler_rejected_outside_diagnostics(self):
        for mode in ('fps','acceptance'):
            with self.assertRaises(SystemExit): self.run_series(mode,game_profiler=True)


if __name__=='__main__':unittest.main()
