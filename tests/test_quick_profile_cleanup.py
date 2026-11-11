"""Run only the cleanup function in PowerShell; never execute the launcher."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows launcher')
class QuickProfileCleanupTests(unittest.TestCase):
    def test_removes_only_known_benchmark_files_and_is_repeatable(self):
        launcher = Path('tools/Quick-Test.ps1').resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root/'mods/CVPQuickStart/42/media'
            removed = [root/'Lua/CVPBenchmark-mode.txt', base/'java/Benchmark.jar']
            removed += [base/f'lua/client/{name}.lua' for name in (
                'CVP_Benchmark', 'CVP_Acceptance', 'CVP_Drive', 'CVP_Performance', 'Release076Review')]
            kept = [base/'lua/client/CVP_QuickStart.lua', base/'lua/client/VisualInspect.lua',
                    root/'Saves/Sandbox/PZT_VehicleLab/players.db', root/'Lua/PZTest/response.txt']
            for path in removed + kept:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('preserve content')
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            script = f"""
                $ErrorActionPreference='Stop'
                $tokens=$null;$errors=$null
                $ast=[System.Management.Automation.Language.Parser]::ParseFile({quote(launcher)},[ref]$tokens,[ref]$errors)
                if($errors.Count){{throw 'Launcher parse failed'}}
                $fn=$ast.Find({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Clear-BenchmarkFiles'}},$true)
                Invoke-Expression $fn.Extent.Text
                Clear-BenchmarkFiles {quote(root)}
                Clear-BenchmarkFiles {quote(root)}
            """
            subprocess.run(['powershell.exe','-NoProfile','-Command',script],check=True,capture_output=True)
            self.assertTrue(all(not p.exists() for p in removed))
            self.assertTrue(all(p.read_text() == 'preserve content' for p in kept))
