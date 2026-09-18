# Underlying Unusual Volume Scanner

This scanner is the stock-level companion to the unusual options scanner. Its job is to surface tradable names that are actually moving now, not just symbols with permanently high volume.

## Model

The alert score combines:

- Fresh 5-minute share volume.
- Fresh 5-minute dollar volume.
- A burst ratio versus the symbol's own volume pace today.
- Move from prior close.
- Move from the open.
- Fast 5-minute price change.
- Intraday range expansion.
- Position near the active side of the day range.

That gives us a first-pass version of the same families of filters used by serious intraday scanners: relative volume, change from open/close, ATR or bar-size style movement, and position in range. Trade Ideas describes relative volume as comparing today's volume to historical volume at the same time of day, change from open as a volatility-adjusted momentum input, and position in range as a high/low-of-day context filter.

## Defaults

The first version is intentionally tuned for liquid, optionable momentum names:

- Price: `$5` to `$1,000`.
- Daily volume so far: at least `500,000` shares.
- Fresh 5-minute volume: at least `100,000` shares.
- Fresh 5-minute dollar volume: at least `$15,000,000`.
- Burst ratio: at least `2.0x` the symbol's current intraday pace.
- Move from close: at least `1.5%`.
- Move from open: at least `0.8%`.
- 5-minute price move: at least `0.45%`.
- Day range: at least `1.2%`.
- Range position: at least `70%` for upside movers or at most `30%` for downside movers.
- Score needed: `4`.

All of these can be changed with `UVS_*` environment variables.

## Why This Should Catch COIN/HOOD-Type Moves

The scanner is looking for the combination that matters for short-dated options:

- Enough stock liquidity for options spreads to wake up.
- Enough speed that premium can expand quickly.
- A move that is large for the individual name, not just large in raw shares.
- A chart location that says buyers or sellers are pressing the edge of the day range.

It should ignore a mega-cap doing ordinary background volume unless that volume is arriving in a fresh burst with price movement.

## Next Upgrade

The current burst ratio is self-relative to today's pace. The stronger production version should persist 30 sessions of 15-minute volume buckets per symbol and calculate true time-of-day RVOL:

```text
current cumulative volume through bucket / average cumulative volume through same bucket
```

That unlocks a cleaner Trade-Ideas-style filter such as `RVOL >= 2.5`, plus a true ATR ratio:

```text
abs(current price - open price) / 14-day ATR
```

Those two fields should become primary score inputs once the scanner has enough historical bars.
