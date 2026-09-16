from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from .application import ToolDeckApplication
from .catalog import CatalogError
from .config import ConfigError, ToolConfig, default_shell
from .drafts import parse_env_assignments
from .frontends import FrontendError, discover_frontends, run_frontend
from .groups import display_group_name
from .procs import ProcessError, ToolStatus
from .util import disp_width, fmt_duration, pad
from .tailer import LogTailer, tail_bytes


def _tools_or_report(application: ToolDeckApplication) -> dict[str, ToolConfig]:
    snapshot = application.refresh_catalog()
    for issue in snapshot.issues:
        print(f"警告：{issue.path.name}: {issue.message}", file=sys.stderr)
    return snapshot.tools


def _find(tools: dict[str, ToolConfig], tool_id: str) -> ToolConfig:
    try:
        return tools[tool_id]
    except KeyError as exc:
        raise ConfigError(f"工具 {tool_id} 不存在") from exc


def _parse_env(values: list[str] | None) -> dict[str, str]:
    return parse_env_assignments(values or ())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tooldeck", description="本地工具总控台")
    parser.add_argument(
        "--frontend",
        default=os.environ.get("TOOLDECK_FRONTEND", "qml"),
        help="无子命令时启动的前端（默认：qml）",
    )
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("frontends", help="列出可用前端适配器")
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


def _print_list(
    tools: dict[str, ToolConfig],
    statuses: dict[str, ToolStatus],
) -> None:
    headers = ("ID", "名称", "分组", "状态", "PID", "运行时间")
    rows: list[tuple[str, ...]] = []
    state_names = {
        "starting": "正在启动",
        "running": "运行中",
        "unready": "启动超时",
        "error": "状态异常",
        "stopping": "停止中",
        "stopped": "已停止",
        "exited": "已退出",
    }
    for tool in tools.values():
        status = statuses.get(tool.id, ToolStatus(tool.id, "stopped"))
        rows.append(
            (
                tool.id,
                tool.name,
                display_group_name(tool.group),
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
    return tail_bytes(path, count)


def _show_logs(log_path: Path, lines: int, follow: bool) -> None:
    tailer = LogTailer(log_path)
    end = tailer.seek_lines(lines)
    while tailer.offset < end:
        previous = tailer.offset
        batch = tailer.read_batch()
        chunk = batch.completed + tailer.flush_pending()
        sys.stdout.buffer.write(chunk.encode("utf-8"))
        if batch.reset or tailer.offset <= previous:
            break
    sys.stdout.buffer.flush()
    if not follow:
        return
    try:
        while True:
            chunk = tailer.read() + tailer.flush_pending()
            if chunk:
                sys.stdout.buffer.write(chunk.encode("utf-8"))
                sys.stdout.buffer.flush()
            time.sleep(0.2)
    except KeyboardInterrupt:
        return


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.action is None:
        try:
            return run_frontend(args.frontend)
        except FrontendError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
    if args.action == "frontends":
        for spec in discover_frontends():
            print(f"{spec.id}\t{spec.name}\t{spec.source}")
        return 0
    try:
        application = ToolDeckApplication()
        tools = _tools_or_report(application)
        if args.action == "list":
            runtime = application.inspect_statuses(tools)
            for issue in runtime.issues:
                print(f"警告：{issue.tool_name}: {issue.message}", file=sys.stderr)
            _print_list(tools, runtime.statuses)
        elif args.action == "start":
            _find(tools, args.id)
            status = application.start(args.id)
            message = "已就绪" if status.state == "running" else "正在启动"
            print(f"{message} {args.id}（PID {status.pid}）")
        elif args.action == "stop":
            _find(tools, args.id)
            application.stop_blocking(args.id)
            print(f"已停止 {args.id}")
        elif args.action == "restart":
            _find(tools, args.id)
            status = application.restart_blocking(args.id)
            message = "已重新就绪" if status.state == "running" else "正在重新启动"
            print(f"{message} {args.id}（PID {status.pid}）")
        elif args.action == "logs":
            _find(tools, args.id)
            _show_logs(application.log_path(args.id), args.lines, args.follow)
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
            application.save_tool(tool, overwrite=False)
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
            if args.cmd is not None:
                changes["launch"] = None
            application.save_tool(replace(old, **changes))
            print(f"已更新 {old.id}")
        elif args.action == "remove":
            tool = _find(tools, args.id)
            application.delete_tool(tool.id)
            print(f"已删除 {tool.id}")
        elif args.action == "path":
            print(application.data_path(args.kind))
    except (CatalogError, ConfigError, FrontendError, ProcessError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
