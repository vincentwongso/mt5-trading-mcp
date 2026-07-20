# AgentScreenshot EA (chart screenshot bridge)

`get_chart_screenshot` needs this Expert Advisor running inside a GUI
MetaTrader 5 terminal on Windows. It watches
`<terminal-data>/MQL5/Files/agent_screenshot/` for requests, screenshots the
requested chart, and writes the PNG back.

## Install

1. Open MetaEditor (from the terminal: Tools > MetaQuotes Language Editor).
2. Copy `AgentScreenshot.mq5` into `MQL5/Experts/` under your terminal data
   folder (in the terminal: File > Open Data Folder).
3. In MetaEditor, open `AgentScreenshot.mq5` and press F7 to compile. This
   produces `AgentScreenshot.ex5`.
4. In the terminal, enable Tools > Options > Expert Advisors >
   "Allow automated trading" (the EA does not trade, but MT5 gates EAs behind
   this switch). File access is sandboxed to `MQL5/Files`, no extra setting
   needed.
5. Drag `AgentScreenshot` from the Navigator onto any one chart. A smiley face
   in the top-right of that chart means it is running. Leave the terminal
   open.

## Compiled .ex5

A compiled `AgentScreenshot.ex5` is committed next to the source, so you can
copy it straight into `MQL5/Experts/` and skip the F7 compile in step 3.
Prefer compiling it yourself (step 3) if you do not want to trust a prebuilt
binary. The `.ex5` cannot be built on Linux/CI, so it is compiled on Windows
with MetaEditor and must be recompiled and re-committed whenever
`AgentScreenshot.mq5` changes.

**Upgrading from 1.5.0?** Re-copy `AgentScreenshot.ex5` (or recompile from
source) before using annotations. A 1.5.0-era `.ex5` still runs and still
takes screenshots, but it does not understand annotation lines, so it silently
ignores every `annotations` entry and returns a clean, unannotated chart with
no error.

## Verify

With the MCP server connected and the EA attached, call `get_chart_screenshot`
for a symbol you can trade (e.g. `EURUSD`, `H1`). You should get a PNG back
within a couple of seconds. If you get `SCREENSHOT_TIMEOUT`, the EA is not
attached or the terminal is not running; if `SCREENSHOT_FAILED` with
"ChartOpen failed", check the symbol name/suffix.
