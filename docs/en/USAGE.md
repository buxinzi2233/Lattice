# Lattice User Guide

The process index contains group headers and tool rows. Click a group to collapse it, drag group headers to reorder groups, and drag tools within or across groups. Dropping onto a collapsed group appends the tool. Reordering is disabled while search or status filters are active; matching groups expand temporarily without changing saved collapse state.

"Reveal full log" selects the persistent log in the file manager. "Clear view" only clears the window buffer. Interface text scales from 80% to 150%.

The startup experience appears on the first launch of each day by default. Settings can change this to every launch or off, preview it, clear the local image cache, and show copyright/safety terms. Remote content failures never block the main window.

If `layout.json` is damaged, Lattice preserves `layout.json.corrupt-*` and rebuilds a deterministic layout. On Windows, process trees are stopped with `taskkill /T`; on Linux, Lattice signals the validated process group.
