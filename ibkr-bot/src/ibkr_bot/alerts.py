from __future__ import annotations

import shlex
import subprocess


class AlertSink:
    def __init__(self, command: str | None) -> None:
        self.command = command

    def send(self, message: str) -> None:
        if not self.command:
            print(message)
            return
        args = shlex.split(self.command)
        subprocess.run(args, input=message, text=True, check=False)

