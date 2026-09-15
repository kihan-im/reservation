"""Windows에서 실제 BAT의 인수 전달과 무인 실행 실패 처리를 확인한다."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import venv


@unittest.skipUnless(os.name == 'nt', 'Windows cmd.exe required')
class WindowsLauncherTest(unittest.TestCase):
    def test_unattended_launch(self):
        # 실제 예약 코드 대신 인수만 기록하는 프로그램을 실행한다.
        with tempfile.TemporaryDirectory(prefix='cip launcher ') as folder:
            root = Path(folder)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'run_automation.bat',
                            root / 'run_automation.bat')
            venv.EnvBuilder(with_pip=False).create(root / 'venv')
            (root / 'requirements.txt').write_text('')
            (root / 'venv' / 'requirements.installed.txt').write_text('')
            (root / 'config.json').write_text('{}')
            (root / 'main.py').write_text(
                'import json, pathlib, sys\n'
                'pathlib.Path("args.json").write_text(json.dumps(sys.argv[1:]))\n'
                'sys.exit(2)\n'
            )

            def run(arguments):
                return subprocess.run(
                    f'cmd.exe /d /c ""{root / "run_automation.bat"}" {arguments}"',
                    cwd=root, input=b'', capture_output=True, timeout=30,
                ).returncode

            self.assertEqual(run('--headless --no-pause --hours 13'), 2)
            self.assertEqual(json.loads((root / 'args.json').read_text()),
                             ['--headless', '--no-pause', '--hours', '13'])
            (root / 'args.json').unlink()
            self.assertEqual(run('--setup-account --no-pause'), 1)
            (root / 'config.json').unlink()
            self.assertEqual(run('--headless --no-pause'), 1)
            (root / 'venv' / 'requirements.installed.txt').unlink()
            self.assertEqual(run('--headless --no-pause'), 1)
            self.assertFalse((root / 'args.json').exists())
