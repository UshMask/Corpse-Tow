import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

spec = importlib.util.spec_from_file_location('agent', Path(__file__).resolve().parents[1] / 'tools/cvp_agent.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class ClientTests(unittest.TestCase):
    def test_async_result_is_read_by_id_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge=agent.Bridge(tmp,.2);bridge.session='current'
            ident='a'*32
            result=Path(tmp)/f'result-{ident}.json'
            result.write_text(json.dumps(dict(id=ident,session='current',state='done',ok=True,result='finished')))
            (Path(tmp)/'response.txt').write_text('{"result":"unrelated diagnostic"}')
            self.assertEqual(bridge.wait(ident,.2),'finished')
            result.write_text(json.dumps(dict(id=ident,session='previous',state='done',ok=True,result='old')))
            with self.assertRaises(agent.CommandError): bridge.wait(ident,.2)

    def test_pending_timeout_preserves_running_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge=agent.Bridge(tmp,.1);bridge.session='current';ident='b'*32
            request=Path(tmp)/'request.txt';request.write_text('running request')
            (Path(tmp)/f'result-{ident}.json').write_text(json.dumps(dict(id=ident,session='current',state='running',ok=True)))
            with self.assertRaises(TimeoutError): bridge.wait(ident,.1)
            self.assertEqual(request.read_text(),'running request')

    def test_protocol_and_no_blind_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bridge = agent.Bridge(folder, .4)
            def server():
                while not (folder / 'request.txt').exists():
                    time.sleep(.01)
                rows = (folder / 'request.txt').read_text().splitlines()
                self.assertEqual(rows[2:], ['hello', '', 'END'])
                (folder / 'response.txt').write_text('{')
                time.sleep(.05)
                agent.atomic_write(folder / 'response.txt', json.dumps(dict(
                    id=rows[0], session='game1', ok=True, result={'ready': True})).encode())
            worker = threading.Thread(target=server)
            worker.start()
            self.assertTrue(bridge.connect()['ready'])
            worker.join()
            self.assertEqual(bridge.session, 'game1')
            self.assertEqual(len(list((folder / 'results').glob('*.json'))), 1)
            with self.assertRaises(TimeoutError):
                bridge.request('scene-status')
            self.assertEqual((folder / 'request.txt').read_text(), 'CANCELLED\n')

    def test_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = agent.Bridge(tmp)
            with bridge.lock():
                with self.assertRaises(agent.CommandError):
                    with agent.Bridge(tmp).lock():
                        self.fail('Must not acquire twice')
            with bridge.lock():
                pass

if __name__ == '__main__':
    unittest.main()
