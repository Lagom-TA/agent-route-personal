"""Durable local notices, with a best-effort macOS notification per new event."""
from pathlib import Path
import subprocess
import time

from .common import atomic_json, identity, read_json


def notify(home, category, event):
    home = Path(home)
    path = home / 'notices.json'
    history = read_json(path, {})
    key = identity({'category': category, 'event': event})
    if key in history:
        return
    script = 'on run argv\ndisplay notification (item 1 of argv) with title "AgentRoute"\nend run'
    messages = {
        'review': '文档、程序或策略需要复查。请打开 AgentRoute 状态.command。',
        'failure': '规则更新未完成或已回退。请打开 AgentRoute 状态.command 查看。',
    }
    attempt = {'category': category, 'event': event, 'time': time.time(), 'desktop_display_verified': False}
    try:
        result = subprocess.run(['/usr/bin/osascript', '-e', script, messages[category]],
                                capture_output=True, timeout=3)
        attempt['notification_command_exit'] = result.returncode
    except (OSError, subprocess.TimeoutExpired):
        attempt['notification_command_exit'] = None
    history[key] = attempt
    atomic_json(path, history)
