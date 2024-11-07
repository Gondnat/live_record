import os
import subprocess
import sys


class Popen(subprocess.Popen):
    if sys.platform == 'win32':
        _startupinfo = subprocess.STARTUPINFO()
        _startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        _startupinfo = None

    @staticmethod
    def _fix_pyinstaller_issues(env):
        if not hasattr(sys, '_MEIPASS'):
            return

        # Force spawning independent subprocesses for exes bundled with PyInstaller>=6.10
        # Ref: https://pyinstaller.org/en/v6.10.0/CHANGES.html#incompatible-changes
        #      https://github.com/yt-dlp/yt-dlp/issues/11259
        env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'

        # Restore LD_LIBRARY_PATH when using PyInstaller
        # Ref: https://pyinstaller.org/en/v6.10.0/runtime-information.html#ld-library-path-libpath-considerations
        #      https://github.com/yt-dlp/yt-dlp/issues/4573
        def _fix(key):
            orig = env.get(f'{key}_ORIG')
            if orig is None:
                env.pop(key, None)
            else:
                env[key] = orig

        _fix('LD_LIBRARY_PATH')  # Linux
        _fix('DYLD_LIBRARY_PATH')  # macOS

    def __init__(self, args, *remaining, env=None, text=False, shell=False, **kwargs):
        if env is None:
            env = os.environ.copy()
        self._fix_pyinstaller_issues(env)

        self.__text_mode = kwargs.get('encoding') or kwargs.get('errors') or text or kwargs.get('universal_newlines')
        if text is True:
            kwargs['universal_newlines'] = True  # For 3.6 compatibility
            kwargs.setdefault('encoding', 'utf-8')
            kwargs.setdefault('errors', 'replace')

        if shell and os.name == 'nt' and kwargs.get('executable') is None:
            if not isinstance(args, str):
                args = shell_quote(args, shell=True)
            shell = False
            # Set variable for `cmd.exe` newline escaping (see `utils.shell_quote`)
            env['='] = '"^\n\n"'
            args = f'{self.__comspec()} /Q /S /D /V:OFF /E:ON /C "{args}"'

        super().__init__(args, *remaining, env=env, shell=shell, **kwargs, startupinfo=self._startupinfo)

    def __comspec(self):
        comspec = os.environ.get('ComSpec') or os.path.join(
            os.environ.get('SystemRoot', ''), 'System32', 'cmd.exe')
        if os.path.isabs(comspec):
            return comspec
        raise FileNotFoundError('shell not found: neither %ComSpec% nor %SystemRoot% is set')

    def communicate_or_kill(self, *args, **kwargs):
        try:
            return self.communicate(*args, **kwargs)
        except BaseException:  # Including KeyboardInterrupt
            self.kill(timeout=None)
            raise

    def kill(self, *, timeout=0):
        super().kill()
        if timeout != 0:
            self.wait(timeout=timeout)

    @classmethod
    def run(cls, *args, timeout=None, **kwargs):
        with cls(*args, **kwargs) as proc:
            default = '' if proc.__text_mode else b''
            stdout, stderr = proc.communicate_or_kill(timeout=timeout)
            return stdout or default, stderr or default, proc.returncode