"""Launch the local API and built Next.js app from one Windows console."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Start the local services and keep their lifecycle tied to the launcher."""
    node = shutil.which("node")
    if not node:
        bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
        node = str(bundled) if bundled.is_file() else None
    if not node:
        raise SystemExit("未找到 Node.js，请安装 Node.js 20.9 或更新版本。")
    next_bin = ROOT / "frontend/node_modules/next/dist/bin/next"
    if not next_bin.is_file():
        raise SystemExit("前端依赖未安装，请按 WEB_APP.md 的说明安装。")
    for port in (8000, 3000):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"端口 {port} 已被占用。若应用已启动，请直接打开 http://127.0.0.1:3000；否则先关闭占用该端口的服务。")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", NEXT_TELEMETRY_DISABLED="1")
    if not (ROOT / "frontend/.next/BUILD_ID").is_file():
        print("首次启动，正在构建前端…", flush=True)
        subprocess.run([node, str(next_bin), "build"], cwd=ROOT / "frontend", env=env, check=True)
    logs = ROOT / "data"
    logs.mkdir(exist_ok=True)
    processes = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with (logs / "backend.log").open("w", encoding="utf-8") as backend_log, (logs / "frontend.log").open("w", encoding="utf-8") as frontend_log:
            commands = [
                ([sys.executable, "-m", "uvicorn", "react_agent.web:app", "--host", "127.0.0.1", "--port", "8000"], ROOT, backend_log),
                ([node, str(next_bin), "start", "--hostname", "127.0.0.1", "--port", "3000"], ROOT / "frontend", frontend_log),
            ]
            for command, cwd, log in commands:
                processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags))
            print("正在启动搜索问答助手…", flush=True)
            ready = False
            for _ in range(60):
                if any(p.poll() is not None for p in processes):
                    break
                try:
                    with urllib.request.urlopen("http://127.0.0.1:3000/api/health", timeout=1) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except Exception:
                    time.sleep(.5)
            if not ready:
                raise RuntimeError("启动未完成，请查看 data/backend.log 和 data/frontend.log。")
            print("\n已启动：http://127.0.0.1:3000\n对话会自动保存到 data/assistant.sqlite3。\n保持本窗口开启，按 Ctrl+C 停止。", flush=True)
            if "--no-browser" not in sys.argv:
                webbrowser.open("http://127.0.0.1:3000")
            while all(p.poll() is None for p in processes):
                time.sleep(.5)
            print("一个服务已停止，请查看 data 下的日志。", flush=True)
    except KeyboardInterrupt:
        print("\n正在停止…", flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        sys.exit(1)
