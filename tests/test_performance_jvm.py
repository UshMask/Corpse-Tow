from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from performance_jvm import configuration, summarize, seconds


class JvmTests(unittest.TestCase):
    def test_missing_is_not_zero_and_nested_pauses_are_not_added(self):
        self.assertIsNone(summarize([])['gcPauseMS'])
        def event(name,**values):return dict(type='jdk.'+name,values=values)
        result=summarize([event('GCPhasePause',duration='PT0.002S'),
                          event('GCPhasePauseLevel1',duration='PT0.001S'),
                          event('GarbageCollection',duration='PT1S'),
                          event('Compilation',duration='PT0.003S')])
        self.assertEqual(result['gcPauseMS'],2)
        self.assertEqual(result['compilerThreadElapsedMS'],3)
        self.assertEqual(seconds('PT1M2.5S'),62.5)

    def test_threads_are_not_merged_by_name(self):
        events=[dict(type='jdk.ThreadCPULoad',values=dict(eventThread=dict(javaThreadId=i,javaName='Worker'),user=.2,system=.1)) for i in (1,2)]
        self.assertEqual(len(summarize(events)['threadCpuLoad']),2)

    def test_configuration_overrides_threshold_controls_without_editing_jdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'lib/jfr/profile.jfc';source.parent.mkdir(parents=True)
            xml='<configuration><event name="jdk.Compilation"><setting name="threshold" control="compiler-threshold">100 ms</setting></event><event name="jdk.ThreadCPULoad"/></configuration>'
            source.write_text(xml)
            target=configuration(root/'bin',root)
            setting=ET.parse(target).getroot().find("event[@name='jdk.Compilation']/setting[@name='threshold']")
            self.assertEqual(setting.text,'0 ms');self.assertNotIn('control',setting.attrib)
            self.assertEqual(source.read_text(),xml)
