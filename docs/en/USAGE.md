# Lattice User Guide

The process index contains group headers and tool rows. Click a group to collapse it, drag group headers to reorder groups, and drag tools within or across groups. Dropping onto a collapsed group appends the tool. Reordering is disabled while search or status filters are active; matching groups expand temporarily without changing saved collapse state. The status filter buttons (Running / Idle / Exited) map to active processes, cleanly stopped processes, and exited processes respectively; "Idle" no longer includes exited tools — crashed tools are only visible under "All" or "Exited".

"Reveal full log" selects the persistent log in the file manager. "Clear view" only clears the window buffer. Both workspaces share the settings panel. Below the theme selector, interface scaling supports 80% to 150% through a slider and minus/plus buttons, with a one-click reset to 100%.

To add a tool, select its program or launch script. Lattice detects the entry point, interpreter, working directory, and arguments, then runs the same preflight before saving and before every start. A Python project without a usable environment offers a project-local `.venv` setup after showing the commands, target, and network requirement. Nothing runs until the user confirms; the current command and complete state-directory `setup` log remain visible while preparation runs. Failure or cancellation does not save the tool and never overwrites or deletes an existing environment; an incomplete marker makes the next confirmed attempt resume preparation, and the environment is accepted only after every step succeeds. Commands, shells, environment variables, health endpoints, and timeouts remain under Advanced Settings; legacy tools open in raw-command mode.

A new process first reports Starting. Process-only tools become Running after a stability grace period; explicit or detected local HTTP/TCP endpoints must answer before a service is Ready. A readiness timeout keeps the process alive and continues low-frequency probes for slow model loading. A process that exits during startup reports its exit code, recent output, and complete log path instead of briefly reporting success.

Built-ins include `lattice-day`, `lattice-night`, and `lattice-archive`, which uses the separate archive workspace shell. Place custom themes in `~/.config/tooldeck/themes.d/` (or `%APPDATA%\tooldeck\themes.d\` on Windows). A pack may extend any built-in theme; extending `lattice-archive` also inherits its `archive` shell. Open the theme directory from Settings, write the JSON file, then reload. A malformed pack is reported and isolated without blocking built-in themes.

The default graphical UI is a replaceable frontend. Run `tooldeck frontends` to list installed adapters and `tooldeck --frontend ID` to launch one. `TOOLDECK_FRONTEND` sets the default when no subcommand is provided.

The startup experience appears on the first launch of each day by default. Settings can change this to every launch or off, preview it, clear the local image cache, and show copyright/safety terms. Remote content failures never block the main window.

If `layout.json` is damaged, Lattice preserves `layout.json.corrupt-*` and rebuilds a deterministic layout. On Windows, process trees are stopped with `taskkill /T`; on Linux, Lattice signals the validated process group.

If an existing runtime-state JSON is corrupt, Lattice refuses another start to prevent a duplicate process. After confirming that the original process has exited, back up and move aside the state file named in the error, then retry.
