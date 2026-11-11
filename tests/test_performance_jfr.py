import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from performance_jfr import record


class JfrTests(unittest.TestCase):
    def exercise(self,body_error=False,start_error=False,stop_error=False,wrong_pid=False):
        with tempfile.TemporaryDirectory(prefix='jfr space ') as tmp:
            root=Path(tmp);runtime=root/'client';runtime.mkdir();folder=root/'output';folder.mkdir()
            binary=root/'jdk/bin';binary.mkdir(parents=True)
            for name in ('jcmd.exe','jfr.exe','java.exe'):(binary/name).touch()
            (binary.parent/'lib/jfr').mkdir(parents=True)
            (binary.parent/'lib/jfr/profile.jfc').write_text('<configuration><event name="jdk.Compilation"/><event name="jdk.ThreadCPULoad"/></configuration>')
            (runtime/'process.json').write_text(json.dumps(dict(pid=123,runtime=str(runtime),jdk=str(binary.parent))))
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                if args[1]=='summary':
                    kwargs['stdout'].write('jdk.GarbageCollection 1\n')
                    return subprocess.CompletedProcess(args,0)
                self.assertEqual(args[1],'123')
                command=args[2]
                if command=='VM.command_line':text='other JVM' if wrong_pid else '-cachedir='+str(runtime/'cache')
                elif command=='JFR.start':text='Failed' if start_error else 'Started recording 1'
                else:
                    if stop_error:raise subprocess.TimeoutExpired(args,20)
                    (folder/'java.jfr').write_bytes(b'FLR\x00test')
                    text='Stopped recording'
                return subprocess.CompletedProcess(args,0,text,'')
            with patch('performance_jfr.subprocess.run',side_effect=run),patch('performance_jfr.summarize_sample') as sample,patch('performance_jfr.extract'):
                if body_error or start_error or stop_error or wrong_pid:
                    expected=ValueError if body_error else subprocess.TimeoutExpired if stop_error else RuntimeError
                    with self.assertRaises(expected):
                        with record(runtime,folder):
                            if body_error:raise ValueError('drive failed')
                else:
                    with record(runtime,folder):pass
                    self.assertIn('GarbageCollection',(folder/'java-summary.txt').read_text())
                if wrong_pid:self.assertEqual(len(calls),1)
                else:
                    self.assertEqual(sum('JFR.stop' in c for c in calls),1)
                    start=next(c for c in calls if 'JFR.start' in c)
                    self.assertIn('duration=120s',start);self.assertIn(f'settings="{folder / "diagnostic.jfc"}"',start)
                    self.assertIn(f'filename="{folder / "java.jfr"}"',start)
                    self.assertIn('dumponexit=true',start)
                self.assertEqual(sample.call_count,0 if body_error or start_error or stop_error or wrong_pid else 1)
            return calls

    def test_recording_and_summary(self):self.exercise()
    def test_stop_on_drive_failure(self):self.exercise(body_error=True)
    def test_failed_start_is_not_silent(self):self.exercise(start_error=True)
    def test_wrong_process_is_not_modified(self):self.exercise(wrong_pid=True)
    def test_stop_failure_is_reported(self):self.exercise(stop_error=True)
    def test_cleanup_failure_preserves_original_error(self):self.exercise(body_error=True,stop_error=True)


if __name__=='__main__':unittest.main()
