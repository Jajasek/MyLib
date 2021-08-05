import subprocess
import sys
import threading
from os import path


class LaunchError(Exception):
    pass


class _Launcher(threading.Thread):
    def __init__(self, file, *args):
        super().__init__()
        self.file = file
        self.args = args
        # self.setDaemon(True)

    def run(self):
        subprocess.run(['python', self.file, *self.args])


def Launch(file, *args):
    if not path.isfile(file) or not file.endswith(".py"):
        raise LaunchError('Invalid file name')
    launcher = _Launcher(file, *args)
    launcher.start()


if __name__ == '__main__':
    print("Launching")
    try:
        file_ = sys.argv[1]
    except IndexError:
        raise LaunchError('No script specified')
    Launch(file_, *sys.argv[2:])
    print("exiting main thread")
