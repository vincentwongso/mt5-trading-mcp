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
terminal is never touched. The copy is logged into the user's own account,
which may be real money. No EA can trade from it: no charts are copied, and
every run switches algo trading off (`[Experts] Enabled=0`,
`AllowLiveTrading=0`). That only stops automated trading. While a test runs
the terminal window is a normal login, so anyone could still place a manual
order in it. Tell the user before running `--setup` against a real-money
login.

Report labels must be in English: with another terminal language a run exits
`2` saying so.

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
   Prints a `settings:` line (symbol, period, dates, model, deposit,
   leverage), then `net_profit` (in the deposit currency), `profit_factor`,
   `max_drawdown_pct`, `trades`, `win_rate_pct`, `sharpe`, ... one
   `key: value` per line, then `json:` and `report:`. Quote the settings with
   the numbers. Use the broker's real symbol name (check with the MCP
   `get_symbols` tool).
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

The `json:` file (or `--json`, which prints it instead of the summary) holds
everything about the run. Read it rather than the summary when you need to
check where the result came from:
- `settings` and `metrics`: as in the summary, plus the inputs used.
- `deals`: every deal (time, type, in/out, volume, price, commission, swap,
  profit, balance, comment). `sl`/`tp` are the stops set when the position
  opened; later changes are not in the report. A closing deal's comment says
  why it closed (`sl 1.15863`, `tp 1.15770`, `end of test`).
- `balance` and `drawdowns`: the balance after each deal, and drawdown periods
  (peak, lowest point, recovery or `null`, depth, days), deepest first.
  These are closed-trade drawdowns; `metrics.max_drawdown_pct` is MT5's
  equity figure and includes open trades.
- `costs`: total commission and swap.
- `journal`: this run's tester log: `started` (`null` if the log does not
  say), `crashed` and `crash_error` (the line that stopped it), `errors`, and
  `ea_lines` (the EA's own `Print` output). Read it whenever `trades` is 0 or
  a result looks wrong. `--json` still prints the document when the run exits
  `2` because the EA failed to start or crashed.
Times are the broker's time as the report prints it, not UTC.
`mt5-mcp backtest --read <report.htm|.xml>` prints the JSON for an old report
(no journal) and writes nothing.

Where the EA and its compiled files come from:
- An EA inside the live `MQL5\Experts` tree runs from its own folder in the
  tester, so a library kept next to it (`#import "MyLib.ex5"`) loads there too.
  An EA from anywhere else is copied to the tester's `Experts\Agent\`.
- Before each run the tester's compiled Experts, Indicators and Libraries are
  synced from the live terminal, and any `.ex5` there with no live original is
  deleted. Don't put files into the tester copy by hand; build them live.
- When `trades` is 0 or the log has errors, the summary adds a `journal:`
  block with the EA's last log lines; the full set is in the JSON.
- Reports stay in the tester folder's `reports\` and are never pruned.

`--model ohlc` (default, 1-minute OHLC) is fast enough to iterate; confirm a
final candidate with `--model real` (real ticks). A month of H1 takes seconds;
full grids take minutes. `--timeout` defaults to 600 seconds, so raise it for
long optimisations. A run that is retried (see below) can take up to twice
`--timeout`, so keep your shell's own timeout above `2 x --timeout` plus a
minute; otherwise the shell can kill the CLI before it stops the terminal.

If the terminal exits cleanly without writing a report (seen on the first
run that downloads a symbol's history), the run is retried once and says so on
stderr.

Exit codes: `0` finished (zero trades is still `0`: read `trades` and the
`journal:` block), `2` could not run or the EA failed. A `2` prints why, often
with the tester's log: not set up, MT5 updated (re-run `--setup`), another
backtest running, timeout, no report written, `EA failed to start` (`OnInit`
returned an error), `EA hit a runtime error` (for example array out of range;
the numbers only cover the part before the crash), or an input in your `.set`
the EA does not have (MT5 silently
ignores unknown names, so the run is refused instead). Optimisation reports
list only the `||Y` inputs, so there the fixed inputs cannot be checked: a
`note:` on stderr names them. Double-check their spelling.

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
