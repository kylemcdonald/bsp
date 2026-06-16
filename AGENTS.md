# Agent Notes

- This machine has passwordless `sudo` for the `ubuntu` user. Use `sudo systemctl ...` when restarting services such as `plotter.service`.
- Plotter terminology matters:
  - `CENTERING` is the startup-only calibration sequence: define the current logical position, move to min, move to max, then return to home. It relies on the physical bounds/end stops and should not be used as normal recovery.
  - `RETURNING_HOME` is the normal move back to `home_position` after a draw, after an interrupted draw, or from manual min/max positioning.
- Keep the machine control surface small. The intended frontend controls are Min, Home, Max, and Button. Avoid reintroducing arbitrary `/go?x=&y=` or `/stop` controls unless the state machine is redesigned around them.
- TinyG has a small command/planner buffer, roughly on the order of tens of commands. The plotter service drip-feeds paths as TinyG frees buffer space, so "commands accepted" or "queue acceptance" time is expected to track most of the physical drawing time.
- Because TinyG command streaming is paced by that small buffer, a drawing can take longer than `tinyg_idle_timeout_seconds` without triggering the idle timeout. The idle timeout starts after the last draw command has been accepted, when only the tail of TinyG's buffered motion remains.
- If a future long drawing has timeout trouble, prefer adding/checking a separate "no streaming progress" timeout. Do not blindly treat total draw wall time as the TinyG idle wait.
- If TinyG disconnects/resets mid-run, software coordinates may no longer be trustworthy. The safe recovery path is restarting `plotter.service`, which runs startup centering again.
