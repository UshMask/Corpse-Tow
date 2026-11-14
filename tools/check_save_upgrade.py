"""Native249 -> 251 ledger regression; no game/server startup or installation.

Historical ledgers are optional, read-only inputs. The Java validator copies them
into its isolated temporary save, checks migration, then removes only that copy.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'jdk', 'zombie-buddy', 'viewpoint'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--ledger', action='append', default=[], type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    suffix = '.exe' if os.name == 'nt' else ''
    javac = args.jdk.resolve() / 'bin' / ('javac' + suffix)
    java = args.game.resolve() / 'jre64' / 'bin' / ('java' + suffix)
    game = args.game.resolve()
    for path in (javac, java, game / 'projectzomboid.jar', args.zombie_buddy, args.viewpoint, *args.ledger):
        if not path.is_file():
            parser.error('Missing file: ' + str(path))
    output = Path(tempfile.mkdtemp(prefix='corpse-tow-save-upgrade-'))
    classes, tests, home = (output / name for name in ('classes', 'tests', 'home'))
    for path in (classes, tests, home):
        path.mkdir()
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    def run(command, name):
        with (output / (name + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run([str(part) for part in command], cwd=root, stdout=log,
                           stderr=subprocess.STDOUT, creationflags=flags, check=True, timeout=180)

    dependencies = os.pathsep.join(map(str, (game / 'projectzomboid.jar', game / '*',
                                            args.zombie_buddy.resolve(), args.viewpoint.resolve())))
    try:
        run([javac, '-encoding', 'UTF-8', '-cp', dependencies, '-d', classes,
             *sorted((root / 'CorpseProxyLab/source').rglob('*.java'))], 'compile')
        run([javac, '-encoding', 'UTF-8', '-cp', str(classes) + os.pathsep + dependencies,
             '-d', tests, root / 'tests/ValidateSaveUpgrade.java'], 'compile-test')
        run([java, '--enable-native-access=ALL-UNNAMED', '-Duser.home=' + str(home),
             '-cp', os.pathsep.join((str(tests), str(classes), dependencies)),
             'cvpworld.ValidateSaveUpgrade', root / 'tests/fixtures/save_upgrade/rope-249.txt',
             *[p.resolve() for p in args.ledger]], 'ValidateSaveUpgrade')
    finally:
        print('Logs: ' + str(output))
    print('PASS native save upgrade; no live world/registry/ownership acceptance claim')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
