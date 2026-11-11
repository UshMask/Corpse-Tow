import json
import re
import unittest
from pathlib import Path
from test_link_client import client
from test_live_settings import settings

BASE=Path('CorpseProxyLab/42/media/lua')

def catalog(language):
    result={}
    for name in ('IG_UI','Sandbox'):
        result.update(json.loads((BASE/'shared/Translate'/language/(name+'.json')).read_text(encoding='utf-8-sig')))
    return result

def translate(l,language):
    texts=catalog(language)
    def text(key,*args):
        if key.startswith(('IGUI_CVP_','Sandbox_CorpseProxyLab')):
            value=texts[key]
        else:
            value=key
        for i,arg in enumerate(args,1):value=value.replace('%'+str(i),str(arg))
        return value
    l.globals().getText=text
    return texts

class CurrentLocalizationTests(unittest.TestCase):
    def test_all_catalogs_keys_and_placeholders(self):
        en,ru=catalog('EN'),catalog('RU')
        self.assertEqual(en.keys(),ru.keys())
        for key in en:
            self.assertTrue(en[key].strip() and ru[key].strip(),key)
            self.assertEqual(sorted(re.findall(r'%[0-9]+',en[key])),sorted(re.findall(r'%[0-9]+',ru[key])),key)
            self.assertFalse(re.search('[А-Яа-я]',en[key]),key)
        for path in BASE.rglob('*.lua'):
            keys=set(re.findall(r"['\"](IGUI_CVP_[A-Za-z0-9_]+)['\"]",path.read_text(encoding='utf-8-sig')))
            self.assertFalse({k for k in keys if not k.endswith('_')}-en.keys(),str(path))
        sandbox=Path('CorpseProxyLab/42/media/sandbox-options.txt').read_text()
        for block in re.findall(r'option[^{}]+\{([^{}]+)\}',sandbox):
            key='Sandbox_'+re.search(r'translation\s*=\s*(\w+)',block)[1]
            self.assertIn(key,en);self.assertIn(key+'_tooltip',en)
            count=re.search(r'numValues\s*=\s*(\d+)',block)
            if count:
                for n in range(1,int(count[1])+1):self.assertIn(key+'_option'+str(n),en)

    def test_current_body_vehicle_menus_in_both_languages(self):
        for language in ('RU','EN'):
            with self.subTest(language=language):
                l=client();texts=translate(l,language)
                l.execute("menu(body);choose('IGUI_CVP_AttachCar');completeJob();menu(body2);choose('IGUI_CVP_ContinueTrain');completeJob();carMenu()")
                labels=[row['label'] for row in l.globals().options.values()]
                self.assertTrue(labels)
                self.assertFalse(any('IGUI_CVP_' in label for label in labels))
                if language=='EN':self.assertFalse(any(re.search('[А-Яа-я]',label) for label in labels))

    def test_world_settings_in_both_languages(self):
        for language in ('RU','EN'):
            with self.subTest(language=language):
                l=client();translate(l,language)
                l.globals().settingsMenuSource=(BASE/'client/CVP_SettingsMenu.lua').read_text(encoding='utf-8-sig')
                settings(l)
                l.execute("getPlayer=function() return player end;SettingsMenu.open()")
                rows=list(l.globals().menuRows.values())
                self.assertTrue(rows)
                for row in rows:
                    label=row['label']
                    self.assertNotIn('IGUI_CVP_',label);self.assertNotIn('Sandbox_CorpseProxyLab',label)
                    if language=='EN':self.assertFalse(re.search('[А-Яа-я]',label))
