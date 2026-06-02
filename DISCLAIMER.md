# Disclaimer

**Read this before connecting `mt5-trading-mcp` to a live account.**

`mt5-trading-mcp` is **experimental, educational software** provided **as-is**. It
lets an AI agent place, modify, cancel, and close **real orders** on a
MetaTrader 5 terminal. By running it you accept the following.

## It trades real money

- When pointed at a live MetaTrader 5 account, this software sends **real orders
  that move real money**. Orders may fill instantly and are **irreversible**.
- Trading leveraged products (forex, CFDs, futures) can cause losses that exceed
  your initial deposit. **You can lose more than you put in.**
- An AI agent can misunderstand instructions, react to bad or manipulated data,
  or behave unpredictably. The consent and pre-flight checks in this project are
  **UX guardrails to catch mistakes, not guarantees** - they are not a safety net
  and they are explicitly **not a security boundary** (see [SECURITY.md](SECURITY.md)).

## It is not financial advice

- Nothing in this software, its documentation, or its outputs is financial,
  investment, tax, or trading advice, or a recommendation to buy or sell any
  instrument.
- You are **solely responsible** for every order placed through this software,
  whether initiated by you or by an agent you connected to it.

## No warranty

- The software is provided without warranty of any kind, as set out in
  [LICENSE](LICENSE). The authors and contributors are **not liable** for any
  trading losses, missed trades, data errors, downtime, or other damages arising
  from its use.

## Use a demo account first

- **Strongly recommended:** run against a **demo / paper account** until you fully
  understand the behaviour. Only point it at a live account once you have verified
  it does what you expect and you accept the risk.

If you do not agree with all of the above, do not use this software with a live
account.
