"""Three-way solver equivalence oracle: old/new Java and old/new Lua.

Compiles the frozen baseline Java solver (renamed ``TowingSolverBaseline``) beside the
live solver with the same ``javac -encoding UTF-8`` invocation the native validator
uses, then runs ``cvpworld.ValidateSolverEquivalence`` inside the game JVM. The Java
oracle loads the frozen Lua module as a distinct module in the same Kahlua VM and
compares all three implementations through their record contract.

A Java compile/load failure or a stale shipped JAR is a test failure, never a
Lua-only pass. The shipped JAR SHA-256 is reported and its ``cvpworld/TowingSolver.class``
bytes must equal the class compiled from the current source.

Artifacts per run (compile logs, oracle log, report.json) are written under
``local/runs/solver-equivalence-<timestamp>/``.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_JAVA = ROOT / 'tests/fixtures/solver_baseline/TowingSolver.java'
BASELINE_LUA = ROOT / 'tests/fixtures/solver_baseline/CVP_GroupConstraints.lua'
BASELINE_FIXTURE = ROOT / 'tests/fixtures/solver_equivalence/TowingSolverBaseline.java'
LIVE_JAVA = ROOT / 'CorpseProxyLab/source/cvpworld/TowingSolver.java'
LIVE_LUA = ROOT / 'CorpseProxyLab/42/media/lua/shared/CVP_GroupConstraints.lua'
SHIPPED_JAR = ROOT / 'CorpseProxyLab/42/media/java/CorpseProxyWorld.jar'
VALIDATOR = ROOT / 'tests/ValidateSolverEquivalence.java'

BASELINE_JAVA_SHA256 = 'DC04B22E89B820BB18CBE0C261FF21CA4EEC1BA7E7A317616B7FB63F0D24EA87'
BASELINE_LUA_SHA256 = '7E3E20D9686912C4D5AF5781F3C31B7313FC60D17196DA4F51D1929BF68E571F'
GENERATED_HEADER = (
    '// GENERATED test-only copy of tests/fixtures/solver_baseline/TowingSolver.java\n'
    '// The frozen baseline is renamed so it compiles and runs beside the production solver.\n'
    '// Do not edit: regenerate from the frozen baseline (see tests/test_solver_equivalence.py).\n'
)
EXPECTED_TOLERANCE = 1e-13
JAVA_TIMEOUT = 900


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def expected_baseline_fixture():
    """The exact generated copy; a stale fixture must never pass silently."""
    source = BASELINE_JAVA.read_text(encoding='utf-8')
    transformed = source.replace(
        'public final class TowingSolver {',
        'public final class TowingSolverBaseline {',
    ).replace(
        '@LuaClass(name="CVPSolverNative")',
        '@LuaClass(name="CVPSolverNativeBaseline")',
    )
    return GENERATED_HEADER + transformed


def resolve_dependency(value, kind):
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if kind == 'dir' and path.is_dir():
        return path
    if kind == 'file' and path.is_file():
        return path
    return None


def load_settings():
    settings_path = ROOT / 'local/settings.json'
    if not settings_path.is_file():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def find_game(settings):
    game = resolve_dependency(settings.get('Game'), 'dir')
    if game and (game / 'projectzomboid.jar').is_file():
        return game
    return None


def find_jdk(settings):
    jdk = resolve_dependency(settings.get('Jdk'), 'dir')
    if jdk and (jdk / 'bin/javac.exe').is_file():
        return jdk
    candidates = sorted(
        (path for path in (ROOT / 'build/toolchain').glob('jdk-*') if (path / 'bin/javac.exe').is_file()),
        key=lambda path: path.name,
    )
    if candidates:
        return candidates[-1]
    java_home = os.environ.get('JAVA_HOME')
    if java_home and (Path(java_home) / 'bin/javac.exe').is_file():
        return Path(java_home)
    return None


def find_zombie_buddy(settings):
    jar = resolve_dependency(settings.get('ZombieBuddy'), 'file')
    if jar:
        return jar
    return None


def game_java(game):
    return game / 'jre64/bin/java.exe'


def classpath_entries(game, zombie_buddy):
    # Mirrors tools/Project.ps1 Native-Checks: projectzomboid.jar, every jar in the
    # game directory (the '*' wildcard is expanded by javac/java), ZombieBuddy.
    entries = [str(game / 'projectzomboid.jar'), str(game / '*'), str(zombie_buddy)]
    return ';'.join(entries)


def run(command, log_path, timeout=JAVA_TIMEOUT):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
    )
    elapsed = time.time() - started
    text = 'STDOUT\n' + process.stdout + '\nSTDERR\n' + process.stderr
    log_path.write_text(text, encoding='utf-8')
    return process, elapsed


def tail(path, lines=40):
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return '<missing>'
    return '\n'.join(content.splitlines()[-lines:])


def parse_header(output):
    match = re.search(r'=== SOLVER EQUIVALENCE HEADER ===\n(.*?)\n=== END SOLVER EQUIVALENCE HEADER ===', output, re.S)
    if not match:
        raise AssertionError('oracle header missing: the Java validator did not start normally')
    header = {}
    for line in match.group(1).splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            header[key.strip()] = value.strip()
    return header


class SolverEquivalenceTests(unittest.TestCase):
    maxDiff = None

    def test_three_way_oracle(self):
        settings = load_settings()
        game = find_game(settings)
        jdk = find_jdk(settings)
        zombie_buddy = find_zombie_buddy(settings)
        missing = []
        if game is None:
            missing.append('projectzomboid.jar (configure Game in local/settings.json)')
        if jdk is None:
            missing.append('JDK with javac (configure Jdk or build/toolchain/)')
        if zombie_buddy is None:
            missing.append('ZombieBuddy.jar (configure ZombieBuddy in local/settings.json)')
        if missing:
            message = 'native solver verifier unavailable: ' + '; '.join(missing)
            if os.environ.get('CVP_REQUIRE_NATIVE') == '1':
                self.fail(message + ' (CVP_REQUIRE_NATIVE=1 forbids skipping)')
            raise unittest.SkipTest(message)
        java = game_java(game)
        self.assertTrue(java.is_file(), f'missing game JVM: {java}')

        # Frozen baseline and generated fixture integrity.
        baseline_java_sha = sha256_file(BASELINE_JAVA)
        baseline_lua_sha = sha256_file(BASELINE_LUA)
        self.assertEqual(BASELINE_JAVA_SHA256, baseline_java_sha,
                         'frozen baseline Java was modified; restore the a892 source')
        self.assertEqual(BASELINE_LUA_SHA256, baseline_lua_sha,
                         'frozen baseline Lua was modified; restore the a892 source')
        expected = expected_baseline_fixture()
        self.assertTrue(BASELINE_FIXTURE.is_file(), f'missing generated baseline fixture: {BASELINE_FIXTURE}')
        actual_fixture = BASELINE_FIXTURE.read_text(encoding='utf-8')
        self.assertEqual(expected, actual_fixture,
                         'TowingSolverBaseline.java is stale: regenerate it from the frozen baseline '
                         '(tests/test_solver_equivalence.py expected_baseline_fixture)')
        current_java_sha = sha256_file(LIVE_JAVA)
        current_lua_sha = sha256_file(LIVE_LUA)
        jar_sha = sha256_file(SHIPPED_JAR)

        stamp = time.strftime('%Y%m%d-%H%M%S')
        run_dir = ROOT / 'local/runs' / f'solver-equivalence-{stamp}'
        classes = run_dir / 'classes'
        validators = run_dir / 'validators'
        home = run_dir / 'home'
        for directory in (classes, validators, home):
            directory.mkdir(parents=True, exist_ok=True)
        classpath = classpath_entries(game, zombie_buddy)
        javac = jdk / 'bin/javac.exe'

        source_files = [
            LIVE_JAVA,
            ROOT / 'CorpseProxyLab/source/cvpworld/SolverEnvironment.java',
            ROOT / 'CorpseProxyLab/source/cvpworld/BodySpacing.java',
        ]
        compile_command = [
            str(javac), '-encoding', 'UTF-8', '-cp', classpath,
            '-sourcepath', str(ROOT / 'CorpseProxyLab/source'),
            '-d', str(classes),
            *map(str, source_files),
        ]
        process, compile_seconds = run(compile_command, run_dir / 'compile-solver.log')
        self.assertEqual(0, process.returncode,
                         'live solver did not compile as a native backend (a Lua-only pass is forbidden):\n'
                         + tail(run_dir / 'compile-solver.log'))
        self.assertTrue(any(classes.glob('cvpworld/TowingSolver.class')),
                        'compile produced no cvpworld/TowingSolver.class')

        validator_command = [
            str(javac), '-encoding', 'UTF-8', '-cp', f'{classes};{classpath}',
            '-d', str(validators),
            str(BASELINE_FIXTURE), str(VALIDATOR),
        ]
        process, validator_compile_seconds = run(validator_command, run_dir / 'compile-validator.log')
        self.assertEqual(0, process.returncode,
                         'equivalence validator did not compile beside the solver (Java failure must not '
                         'look like a Lua pass):\n' + tail(run_dir / 'compile-validator.log'))
        self.assertTrue((validators / 'cvpworld/TowingSolverBaseline.class').is_file(),
                        'baseline class was not compiled')

        oracle_command = [
            str(java),
            '--enable-native-access=ALL-UNNAMED',
            f'-Duser.home={home}',
            f'-Dcvp.game={game}',
            f'-Dcvp.jar={SHIPPED_JAR}',
            '-Dfile.encoding=UTF-8',
            '-Dstdout.encoding=UTF-8',
            '-Dstderr.encoding=UTF-8',
            '-cp', f'{validators};{classes};{classpath}',
            'cvpworld.ValidateSolverEquivalence',
        ]
        process, oracle_seconds = run(oracle_command, run_dir / 'oracle.log')
        output = process.stdout
        failures = []
        if process.returncode != 0:
            failures.append(f'oracle process exited {process.returncode}')
        if 'PASS oracle 1/3 java-vs-java' not in output:
            failures.append('old Java vs new Java oracle did not pass')
        if 'PASS oracle 2/3 lua-vs-lua' not in output:
            failures.append('old Lua vs new Lua oracle did not pass')
        if 'PASS oracle 3/3 java-vs-lua' not in output:
            failures.append('new Java vs new Lua oracle did not pass')
        if 'oracleResult=PASS' not in output:
            failures.append('oracleResult=PASS marker missing')

        report = {
            'status': 'passed' if not failures else 'failed',
            'oracle': 'three-way solver equivalence',
            'command': ' '.join(oracle_command),
            'runDir': str(run_dir),
            'baseline': {
                'javaPath': str(BASELINE_JAVA),
                'javaSha256': baseline_java_sha,
                'luaPath': str(BASELINE_LUA),
                'luaSha256': baseline_lua_sha,
                'generatedBaselineFixture': str(BASELINE_FIXTURE),
            },
            'current': {
                'javaPath': str(LIVE_JAVA),
                'javaSha256': current_java_sha,
                'luaPath': str(LIVE_LUA),
                'luaSha256': current_lua_sha,
            },
            'jar': {'path': str(SHIPPED_JAR), 'sha256': jar_sha},
            'environment': {
                'game': str(game),
                'jdk': str(jdk),
                'zombieBuddy': str(zombie_buddy),
            },
            'timing': {
                'compileSolverSeconds': round(compile_seconds, 3),
                'compileValidatorSeconds': round(validator_compile_seconds, 3),
                'oracleSeconds': round(oracle_seconds, 3),
            },
            'failures': failures,
        }

        # Verify the header the Java process itself reported: source hashes, JAR path,
        # JAR SHA-256, class-bytes equality and the native backend marker.
        try:
            header = parse_header(output)
        except AssertionError as error:
            report['failures'].append(str(error))
            (run_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            self.fail(f'{error}\n{tail(run_dir / "oracle.log")}')

        header_failures = []
        if header.get('baselineJavaSha256') != BASELINE_JAVA_SHA256:
            header_failures.append(f'header baselineJavaSha256={header.get("baselineJavaSha256")}')
        if header.get('baselineLuaSha256') != BASELINE_LUA_SHA256:
            header_failures.append(f'header baselineLuaSha256={header.get("baselineLuaSha256")}')
        if header.get('currentJavaSha256') != current_java_sha:
            header_failures.append('header currentJavaSha256 does not match the live source')
        if header.get('currentLuaSha256') != current_lua_sha:
            header_failures.append('header currentLuaSha256 does not match the live Lua module')
        reported_jar_sha = header.get('jarFileSha256')
        if reported_jar_sha != jar_sha:
            header_failures.append(f'header jarFileSha256={reported_jar_sha} != {jar_sha}')
        if header.get('jarClassMatchesCompiled') != 'true':
            header_failures.append('shipped JAR is stale: cvpworld/TowingSolver.class differs from the compiled source')
        if header.get('jarClassCheck') != 'enforced':
            header_failures.append('JAR class check was not enforced')
        if header.get('nativeClass') != 'cvpworld.TowingSolver':
            header_failures.append(f'header nativeClass={header.get("nativeClass")}')
        if not header.get('nativeClassSource'):
            header_failures.append('native solver code source missing: Java class did not load')
        if 'in-process-java-native' not in header.get('backend', ''):
            header_failures.append(f'header backend={header.get("backend")}')
        if not header.get('nativeSolverVersion'):
            header_failures.append('native solver version missing: Java class did not load')
        try:
            reported_jar_path = Path(header.get('jarPath', ''))
        except (OSError, ValueError):
            reported_jar_path = None
        if reported_jar_path is None or reported_jar_path != SHIPPED_JAR:
            header_failures.append(f'header jarPath={header.get("jarPath")} != {SHIPPED_JAR}')

        summary_match = re.search(
            r'PASS solver equivalence: (\d+) compared values, max absolute error=([0-9.eE+-]+), scenarios=(\d+)',
            output,
        )
        if not summary_match:
            header_failures.append('equivalence summary line missing')
        else:
            report['comparedValues'] = int(summary_match.group(1))
            report['maxAbsoluteError'] = float(summary_match.group(2))
            report['scenarios'] = int(summary_match.group(3))
            if report['maxAbsoluteError'] >= EXPECTED_TOLERANCE:
                header_failures.append(
                    f'max absolute error {report["maxAbsoluteError"]} is not below {EXPECTED_TOLERANCE}')
            if report['scenarios'] < 28:
                header_failures.append(f'only {report["scenarios"]} scenarios exercised; expected 28')

        # Controlled-scaling evidence for the optimisation stages: identical 1/2/4 x 32-body
        # chains under the same input, timed on the live native backend.
        scaling = []
        scaling_pattern = re.compile(
            r'SCALING chains=(\d+) bodies=(\d+) ticks=(\d+) stepsPerTick=(\d+) '
            r'solveMs=([0-9.]+) perBodyPerTickUs=([0-9.]+) maxCrossChainError=([0-9.eE+-]+)'
        )
        for line in output.splitlines():
            match = scaling_pattern.search(line)
            if match:
                scaling.append({
                    'chains': int(match.group(1)),
                    'bodies': int(match.group(2)),
                    'ticks': int(match.group(3)),
                    'stepsPerTick': int(match.group(4)),
                    'solveMs': float(match.group(5)),
                    'perBodyPerTickUs': float(match.group(6)),
                    'maxCrossChainError': float(match.group(7)),
                })
        report['scaling'] = scaling
        if [entry['chains'] for entry in scaling] != [1, 2, 4]:
            header_failures.append(f'controlled scaling missing 1/2/4 chains: {scaling}')
        for entry in scaling:
            if entry['maxCrossChainError'] >= EXPECTED_TOLERANCE:
                header_failures.append(
                    f'controlled scaling diverged for {entry["chains"]} chains: {entry["maxCrossChainError"]}')
            if not entry['solveMs'] > 0:
                header_failures.append(f'controlled scaling reported no solve time for {entry["chains"]} chains')

        report['header'] = header
        report['failures'].extend(header_failures)
        report['status'] = 'passed' if not report['failures'] else 'failed'
        (run_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        scaling_text = ', '.join(
            f"{entry['chains']}x32={entry['solveMs']:.3f}ms ({entry['perBodyPerTickUs']:.3f}us/body/tick)"
            for entry in scaling
        )
        summary = (
            f"three-way solver equivalence PASS: {report.get('comparedValues')} compared values, "
            f"max error {report.get('maxAbsoluteError')}, {report.get('scenarios')} scenarios; "
            f"scaling {scaling_text}; "
            f"jar sha256 {jar_sha}; baseline java {baseline_java_sha[:16]}... lua {baseline_lua_sha[:16]}...; "
            f"logs {run_dir}"
        )
        print(summary)

        if failures or header_failures:
            self.fail('\n'.join(failures + header_failures)
                      + f'\n--- oracle log tail ---\n{tail(run_dir / "oracle.log", 80)}')
        self.assertEqual('passed', report['status'])


if __name__ == '__main__':
    unittest.main()
