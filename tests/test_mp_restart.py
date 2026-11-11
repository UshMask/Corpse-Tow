import importlib.util
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'quit_server', Path(__file__).resolve().parents[1] / 'tools/mp-test/quit_server.py')
rcon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rcon)


def packet(request, kind, text=b''):
    body = struct.pack('<ii', request, kind) + text + b'\0\0'
    return struct.pack('<i', len(body)) + body


class Stream:
    def __init__(self, incoming):
        self.incoming = incoming
        self.sent = []

    def recv(self, count):
        chunk, self.incoming = self.incoming[:1], self.incoming[1:]
        return chunk  # Deliberately fragmented TCP reads.

    def sendall(self, data):
        self.sent.append(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class RestartRconTests(unittest.TestCase):
    def run_quit(self, stream):
        with patch.object(rcon.socket, 'create_connection', return_value=stream) as connect:
            rcon.quit_server(17263, 'test-secret')
            connect.assert_called_once_with(('127.0.0.1', 17263), timeout=10)

    def test_fragmented_auth_then_quit(self):
        stream = Stream(packet(1, 2))
        self.run_quit(stream)
        self.assertEqual(stream.sent, [packet(1, 3, b'test-secret'), packet(2, 2, b'quit')])

    def test_optional_empty_auth_response(self):
        stream = Stream(packet(1, 0) + packet(1, 2))
        self.run_quit(stream)
        self.assertEqual(stream.sent[-1], packet(2, 2, b'quit'))

    def test_failed_auth_never_sends_quit(self):
        stream = Stream(packet(-1, 2))
        with self.assertRaises(PermissionError):
            self.run_quit(stream)
        self.assertEqual(len(stream.sent), 1)

    def test_wrong_auth_id_never_sends_quit(self):
        stream = Stream(packet(99, 2))
        with self.assertRaises(ValueError):
            self.run_quit(stream)
        self.assertEqual(len(stream.sent), 1)

    def test_disconnected_auth_never_sends_quit(self):
        stream = Stream(packet(1, 2)[:-1])
        with self.assertRaises(EOFError):
            self.run_quit(stream)
        self.assertEqual(len(stream.sent), 1)

    def test_rejects_invalid_packet_size(self):
        with self.assertRaises(ValueError):
            rcon.receive(Stream(struct.pack('<i', 2**30)))

    def test_empty_password_does_not_connect(self):
        with patch.object(rcon.socket, 'create_connection') as connect:
            with self.assertRaises(ValueError):
                rcon.quit_server(17263, '')
            connect.assert_not_called()
