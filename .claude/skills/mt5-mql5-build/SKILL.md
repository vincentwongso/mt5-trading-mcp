---
name: mt5-mql5-build
description: Use when the user wants to write, compile, or fix MQL5 code for MetaTrader 5 - an Expert Advisor (EA), indicator, script, service or library - or asks to "build an EA", "compile this .mq5", "fix the compile errors", "make an indicator for MT5", "backtest this EA", "optimise the inputs". Covers the edit / compile / fix / backtest loop with the `mt5-mcp compile` and `mt5-mcp backtest` CLIs against the user's locally installed MT5, where the build lands, and the safety rules for EAs that trade.
---

# Building MQL5 with `mt5-mcp compile`

Compile one `.mq5` file with the user's local MetaEditor and get errors you can
act on. Windows only for now (it needs MetaEditor; under Wine/Docker MetaEditor
currently hangs and the command times out). Then backtest it with
`mt5-mcp backtest` (below).

## The loop

1. Write the source in the user's project (keep it in git), e.g.
   `src/MyEA.mq5`. Project-local includes (`#include "inc/util.mqh"`) and the
   standard library (`#include <Trade\Trade.mqh>`) both resolve.
2. Run:
   ```
   mt5-mcp compile src/MyEA.mq5
   ```
3. Read the output. Each problem is one line:
   ```
   src/MyEA.mq5:42:7: error 256: undeclared identifier 'foo'
   src/inc/util.mqh:3:11: warning 43: possible loss of data due to type conversion from 'double' to 'int'
   Result: 1 error, 1 warning
   ```
   Fix the code at that file, line and column. Errors in an included file
   point at the `.mqh`, not the `.mq5`.
4. Repeat until it exits 0. Fix warnings too unless there is a reason not to.

A compile takes about a second. MetaEditor is killed after `--timeout`
seconds (default 60); keep your shell's own command timeout above that so the
CLI, not your harness, does the killing.

## Exit codes

- `0` - compiled (warnings allowed) and installed.
- `1` - compile errors. Fix the code.
- `2` - could not run: MetaEditor or the data folder not found, timeout,
  unreadable log, install failed. This is a setup problem, not a code problem.
  Read the message; do not start editing the source. If it says several
  installs or data folders were found, ask the user which terminal to use and
  pass `--terminal-path` / `--data-path` (or set `[mt5] terminal_path` /
  `data_path` in the config).

## Where the build goes

The program type is detected from the code (`--kind` overrides):
`#property service` -> Services, `#property library` -> Libraries,
`OnCalculate` -> Indicators, `OnStart` -> Scripts, otherwise Experts.

- Clean builds install to `MQL5\<Kind>\Agent\<name>.ex5` in the terminal's
  data folder (printed as `installed: ...`), so they never overwrite the
  user's own programs. The user sees them in the Navigator under `Agent`.
- Libraries go to `MQL5\Libraries\<name>.ex5` (no `Agent`), because
  `#import "MyLib.ex5"` only searches the caller's folder and the Libraries
  root.
- An EA that uses an agent-built indicator must name the subfolder:
  `iCustom(_Symbol, _Period, "Agent\\MyInd", ...)`.
- A build that already lands in a kind folder (a source under `MQL5\Experts`,
  `MQL5\Indicators`, ..., or an MQL5 Algo Forge `Shared Projects` source,
  which MetaEditor builds into `MQL5\<Kind>\Shared Projects\`) stays where
  it is; nothing is copied.
- `replacing existing: <path>` on stderr means another build with the same
  file name was already installed there (possibly from another project). If
  that EA might be attached to a chart, tell the user.
- `--no-install` leaves the `.ex5` next to the source only.

## Backtest with `mt5-mcp backtest`

Runs the Strategy Tester on a separate copy of MT5, so the user's live
terminal is never touched. The copy is logged into the same account, but no
charts or EAs are copied into it and live algo trading is switched off.

1. Once per machine (and again after an MT5 update, when a run says so):
   ```
   mt5-mcp backtest --setup
   ```
   If several MT5 installs exist, ask the user which one and pass
   `--terminal-path`. If it warns about `[mt5] terminal_path`, tell the user:
   without it the MCP server can attach to the tester copy while a test runs.
2. Single run, on the `installed:` path `compile` printed:
   ```
   mt5-mcp backtest <installed .ex5> --symbol EURUSD --period H1 --from 2026-01-01 --to 2026-11-01
   ```
   Prints `net_profit`, `profit_factor`, `max_drawdown_pct`, `trades`,
   `win_rate_pct`, `sharpe`, ... one `key: value` per line, then `report:`.
   Use the broker's real symbol name (check with the MCP `get_symbols` tool).
3. Inputs go in an MT5 `.set` file (`--set file.set`): `Name=value` per
   line. To optimise an input use `Name=value||start||step||stop||Y`, e.g.
   `MovingPeriod=12||6||2||30||Y`, then add `--optimize full` (every
   combination) or `--optimize genetic` (large grids). It prints a ranked
   table of passes (`--top`, default 20).
4. **Forward test is on by default for `--optimize`**: MT5 optimises on the
   first two thirds of the range and re-runs each pass on the held-out last
   third. Rows are ranked by the forward result. Judge inputs on the forward
   columns: a pass that only shines in the back period is overfit.
   `--forward 1/2|1/4|YYYY-MM-DD` moves the split, `--forward off` disables it.

`--model ohlc` (default, 1-minute OHLC) is fast enough to iterate; confirm a
final candidate with `--model real` (real ticks). A month of H1 takes seconds;
full grids take minutes. `--timeout` defaults to 600 seconds, so raise it for
long optimisations and keep your shell's own timeout above it.

Exit codes: `0` finished (zero trades is still `0`: read `trades`), `2` could
not run. A `2` prints why, often with the tester's log tail: not set up, MT5
updated (re-run `--setup`), another backtest running, timeout, no report
written, or an input in your `.set` the EA does not have (MT5 silently
ignores unknown names, so the run is refused instead).

## Safety rules

- **Never attach, start or stop an EA.** You build it; the user decides
  whether and where it runs. A running EA trades from inside the terminal and
  bypasses every guard the MCP server enforces (consent gate, limits, audit).
- **Rebuilding an EA that is running live changes live trading.** MT5 reloads
  an attached EA when its `.ex5` changes. Before recompiling an EA the user
  has said is attached to a chart, ask them first.
- Do not claim an EA is profitable or "works" because it compiles. It only
  means the code is valid.
- A good backtest is not a reason to attach the EA either. Report the
  numbers (forward ones first) and let the user decide.
