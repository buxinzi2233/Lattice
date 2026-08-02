from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import time
from pathlib import Path

from . import paths
from .config import ConfigError, ToolConfig, default_shell, delete, load_all, save
from .procs import ProcManager, ProcessError
from .util import disp_width, fmt_duration, pad


def _tools_or_report() -> dict[str, ToolConfig]:
    tools, issues = load_all()
    for issue in issues:
        print(f"警告：{issue.path.name}: {issue.message}", file=sys.stderr)
    return tools


def _find(tools: dict[str, ToolConfig], tool_id: str) -> ToolConfig:
    try:
        return tools[tool_id]
    except KeyError as exc:
        raise ConfigError(f"工具 {tool_id} 不存在") from exc


def _parse_env(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise ConfigError(f"环境变量必须使用 KEY=VALUE 格式：{item}")
        key, value = item.split("=", 1)
        if not key:
            raise ConfigError("环境变量名不能为空")
        result[key] = value
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tooldeck", description="本地工具总控台")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="列出工具及状态")

    for name in ("start", "stop", "restart"):
        command = sub.add_parser(name, help={"start": "启动工具", "stop": "停止工具", "restart": "重启工具"}[name])
        command.add_argument("id")

    logs = sub.add_parser("logs", help="查看工具日志")
    logs.add_argument("id")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("-n", "--lines", type=int, default=100)

    add = sub.add_parser("add", help="添加工具")
    add.add_argument("id")
    add.add_argument("--name", required=True)
    add.add_argument("--group", default="")
    add.add_argument("--cmd", required=True)
    add.add_argument("--cwd", required=True)
    add.add_argument("--shell", default=default_shell())
    add.add_argument("--env", action="append", metavar="KEY=VALUE")
    add.add_argument("--autostart", action="store_true")
    add.add_argument("--stop-signal", default="TERM")
    add.add_argument("--stop-timeout", type=float, default=10.0)

    edit = sub.add_parser("edit", help="修改工具")
    edit.add_argument("id")
    edit.add_argument("--name")
    edit.add_argument("--group")
    edit.add_argument("--cmd")
    edit.add_argument("--cwd")
    edit.add_argument("--shell")
    edit.add_argument("--env", action="append", metavar="KEY=VALUE")
    edit.add_argument("--autostart", choices=("true", "false"))
    edit.add_argument("--stop-signal")
    edit.add_argument("--stop-timeout", type=float)

    remove = sub.add_parser("remove", help="删除工具配置")
    remove.add_argument("id")

    location = sub.add_parser("path", help="显示数据目录")
    location.add_argument("kind", nargs="?", choices=("config", "state", "logs"), default="config")
    return parser


def _print_list(manager: ProcManager, tools: dict[str, ToolConfig]) -> None:
    headers = ("ID", "名称", "分组", "状态", "PID", "运行时间")
    rows: list[tuple[str, ...]] = []
    state_names = {"running": "运行中", "stopping": "停止中", "stopped": "已停止", "exited": "已退出"}
    for tool in tools.values():
        status = manager.status(tool.id)
        rows.append(
            (
                tool.id,
                tool.name,
                tool.group or "未分组",
                state_names[status.state],
                str(status.pid or "-"),
                fmt_duration(status.uptime),
            )
        )
    widths = [max([disp_width(headers[i]), *(disp_width(row[i]) for row in rows)]) for i in range(len(headers))]
    print("  ".join(pad(value, widths[i]) for i, value in enumerate(headers)))
    for row in rows:
        print("  ".join(pad(value, widths[i]) for i, value in enumerate(row)))


def _tail_lines(path: Path, count: int) -> bytes:
    if count <= 0:
        return b""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return b""
    return b"\n".join(data.splitlines()[-count:]) + (b"\n" if data else b"")


def _show_logs(tool_id: str, lines: int, follow: bool) -> None:
    log_path = paths.log_file(tool_id)
    initial = _tail_lines(log_path, lines)
    if initial:
        sys.stdout.buffer.write(initial)
        sys.stdout.buffer.flush()
    if not follow:
        return
    position = log_path.stat().st_size if log_path.exists() else 0
    try:
        while True:
            try:
                size = log_path.stat().st_size
                if size < position:
                    position = 0
                if size > position:
                    with log_path.open("rb") as handle:
                        handle.seek(position)
                        chunk = handle.read()
                        position = handle.tell()
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
            except FileNotFoundError:
                position = 0
            time.sleep(0.2)
    except KeyboardInterrupt:
        return


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.action is None:
        from .gui.app import run_gui

        return run_gui()
    try:
        tools = _tools_or_report()
        manager = ProcManager()
        if args.action == "list":
            _print_list(manager, tools)
        elif args.action == "start":
            status = manager.start(_find(tools, args.id))
            print(f"已启动 {args.id}（PID {status.pid}）")
        elif args.action == "stop":
            manager.stop_blocking(_find(tools, args.id))
            print(f"已停止 {args.id}")
        elif args.action == "restart":
            tool = _find(tools, args.id)
            manager.stop_blocking(tool)
            status = manager.start(tool)
            print(f"已重启 {args.id}（PID {status.pid}）")
        elif args.action == "logs":
            _find(tools, args.id)
            _show_logs(args.id, args.lines, args.follow)
        elif args.action == "add":
            tool = ToolConfig(
                id=args.id,
                name=args.name,
                group=args.group,
                cmd=args.cmd,
                cwd=args.cwd,
                shell=args.shell,
                env=_parse_env(args.env),
                autostart=args.autostart,
                stop_signal=args.stop_signal,
                stop_timeout=args.stop_timeout,
            )
            save(tool, overwrite=False)
            print(f"已添加 {tool.id}")
        elif args.action == "edit":
            old = _find(tools, args.id)
            changes = {
                key: value
                for key, value in {
                    "name": args.name,
                    "group": args.group,
                    "cmd": args.cmd,
                    "cwd": args.cwd,
                    "shell": args.shell,
                    "stop_signal": args.stop_signal,
                    "stop_timeout": args.stop_timeout,
                }.items()
                if value is not None
            }
            if args.env is not None:
                changes["env"] = _parse_env(args.env)
            if args.autostart is not None:
                changes["autostart"] = args.autostart == "true"
            save(dataclasses.replace(old, **changes))
            print(f"已更新 {old.id}")
        elif args.action == "remove":
            tool = _find(tools, args.id)
            if manager.status(tool.id).active:
                raise ProcessError("工具仍在运行，请先停止")
            delete(tool.id)
            print(f"已删除 {tool.id}")
        elif args.action == "path":
            selected = {"config": paths.config_dir(), "state": paths.state_dir(), "logs": paths.logs_dir()}[args.kind]
            print(selected)
    except (ConfigError, ProcessError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
