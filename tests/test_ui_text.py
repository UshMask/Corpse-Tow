"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class UiTextTests(unittest.TestCase):
    def test_translated_menu_and_catalog_coverage(self):
        """UI labels come from translation catalogs, even with a non-UTF-8 Lua loader."""
        from pathlib import Path
        import json
        import re

        base = Path('CorpseProxyLab/42/media/lua')
        catalogs = {lang: json.loads((base/'shared/Translate'/lang/'IG_UI.json').read_text(encoding='utf-8'))
                    for lang in ('RU', 'EN', 'ES', 'ES_MX', 'ES_CL')}
        assert catalogs['RU'].keys() == catalogs['EN'].keys()
        for language in ('ES', 'ES_MX', 'ES_CL'):
            assert catalogs[language].keys() == catalogs['EN'].keys()
        for file in (base/'client/CVP_Client.lua', base/'client/CVP_MPClient.lua', base/'server/CVP_MPServer.lua', base/'client/CVP_Menu.lua', base/'client/CVP_Batch.lua', base/'client/CVP_LinkMenu.lua', base/'client/CVP_LinkActions.lua', base/'client/CVP_Options.lua', base/'shared/CVP_LinkMessages.lua'):
            source = file.read_text(encoding='utf-8')
            keys = set(re.findall(r"'((?:IGUI_CVP_)[A-Za-z]+)'", source))
            assert keys <= catalogs['EN'].keys(), (file, keys - catalogs['EN'].keys())

        from test_link_client import client, SOURCE
        for language in ('RU', 'EN', 'ES', 'ES_MX', 'ES_CL'):
            lua = client(start=False)
            catalog = catalogs[language]
            def translated(key, *args):
                result = catalog[key]
                for n, value in enumerate(args, 1):
                    result = result.replace('%'+str(n), str(value))
                return result
            lua.globals().getText = translated
            lua.globals().getTextOrNull = lambda key: 'Chevalier Dart' if key == 'IGUI_VehicleNameTestCar' else None
            # Reproduce decoding Lua bytes in the wrong code page. ASCII translation keys
            # survive; hardcoded Cyrillic menu labels would fail the exact comparisons.
            lua.execute(SOURCE.read_text(encoding='utf-8').encode('utf-8').decode('latin1'))
            lua.execute('callbacks.OnGameStart();assert(not CVPRuntime.error);R=CVPRuntime.authority;S=R.service;H=R.host;Sim=R.simulation')
            lua.execute('menu()')
            labels = [o['label'] for _, o in lua.globals().options.items()]
            assert all('CVP: ' not in label for label in labels), 'technical prefix in visible menu'
            expected = translated('IGUI_CVP_AttachCar')
            assert any(label.startswith(expected) for label in labels), labels
            lua.execute('link(C,A,rope);link(C,B,chain);menu(body)')
            options = list(lua.globals().options.values())
            assert any(o['label'] == translated('IGUI_CVP_DetachBody') for o in options)
            lua.execute('carMenu()'); options = list(lua.globals().options.values())
            assert any(o['label'] == translated('IGUI_CVP_DetachCargo') for o in options)
            lua.execute('driving=true;menu()')
            assert any(o['notAvailable'] and o['toolTip'] and o['toolTip']['description'].startswith(translated('IGUI_CVP_LeaveVehicle')) for o in lua.globals().options.values())
            print('PASS', language, 'current attach/detach/all and reason despite wrong Lua decoding')
        print('PASS SP/MP translation key coverage and matching RU/EN/Spanish catalogs')

    def test_spanish_catalogs_preserve_keys_and_format_arguments(self):
        from collections import Counter
        from pathlib import Path
        import json
        import re

        root = Path('CorpseProxyLab/42/media/lua/shared/Translate')
        for name in ('IG_UI', 'Sandbox'):
            reference = json.loads((root/'EN'/f'{name}.json').read_text(encoding='utf-8'))
            for language in ('ES', 'ES_MX', 'ES_CL'):
                translated = json.loads((root/language/f'{name}.json').read_text(encoding='utf-8'))
                self.assertEqual(reference.keys(), translated.keys(), (language, name))
                for key, text in reference.items():
                    with self.subTest(language=language, catalog=name, key=key):
                        self.assertTrue(translated[key].strip())
                        self.assertNotRegex(translated[key], r'%(?![1-9])',
                                            (language, name, key))
                        self.assertEqual(Counter(re.findall(r'%\d+', text)),
                                         Counter(re.findall(r'%\d+', translated[key])))

    def test_contextual_body_and_vehicle_actions_are_translated(self):
        from pathlib import Path
        import json
        from test_link_client import client

        root = Path('CorpseProxyLab/42/media/lua/shared/Translate')
        for language in ('RU', 'EN', 'ES', 'ES_MX', 'ES_CL'):
            with self.subTest(language=language):
                catalog = json.loads((root/language/'IG_UI.json').read_text(encoding='utf-8'))
                def translated(key, *args):
                    result = catalog.get(key, key)
                    for index, value in enumerate(args, 1):
                        result = result.replace('%'+str(index), str(value))
                    return result
                lua = client()
                lua.globals().getText = translated
                lua.execute('link(C,A,rope);link(A,B,chain);menu(body)')
                options = list(lua.globals().options.values())
                middle = [o for o in options if o['label'] == translated('IGUI_CVP_DetachBodyMiddle')]
                self.assertEqual(len(middle), 1)
                self.assertEqual(middle[0]['toolTip']['description'], translated('IGUI_CVP_DetachBodyMiddleHint'))
                self.assertFalse(any(o['label'] == translated('IGUI_CVP_LinkRelease') for o in options))
                lua.execute('carMenu()')
                options = list(lua.globals().options.values())
                detach = [o for o in options if o['label'] == translated('IGUI_CVP_DetachFromCar')]
                self.assertEqual(len(detach), 1)
                self.assertEqual(detach[0]['toolTip']['description'], translated('IGUI_CVP_DetachFromHint'))


if __name__ == '__main__':
    unittest.main()

