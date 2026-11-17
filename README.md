# GTA VI launch-day Twitch forecast

A program that forecasts how many people watch Grand Theft Auto VI live on
Twitch in each hour of its release day, 2026-11-19 (UTC), from everything
recorded up to the end of the day's first hour.

## How it works

`main.py` (Python 3.13, standard library only) reads one case file
(`makefun/twitch-ccu-case/v1`) and writes, for hours 2 to 24, five
quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent viewers in
the game's Twitch category.

The forecast is built from the case's own comparables — past big game
launches' hourly Twitch curves:

- Each comparable's curve is rescaled by its own first hour, giving a
  log-ratio curve. A launch's audience shape is set by the clock (the
  UTC day's hours fall on the same local times everywhere), not by its
  size, so past curves predict a new launch's shape.
- Only console-only launches are used as the reference set. GTA VI
  launches on PlayStation 5 and Xbox Series X|S at midnight local time,
  rolling region by region; a PC launch that unlocks simultaneously
  worldwide has a near-zero first hour and a ratio curve that explodes
  hundreds-fold later, which is not this launch's shape.
- Per hour, the median log-ratio is the centre and the 5th/25th/75th/95th
  percentiles are the spread, scaled by the case's own first-hour print.
- A launch whose first hour is already huge has less room left to grow:
  across the console-only comparables the log peak ratio falls with the
  log first-hour print (slope about -0.31), so the centre is shifted for
  this case's first-hour size, most at the peak hours, capped at half a
  log unit.
- With no usable comparables, it falls back to holding the first hour's
  print with a spread that widens with the square root of the hours
  elapsed.

No network, no randomness: the same case always writes the same bytes.

## Run

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Local practice score

Scored against SullyGnome's hourly counts for the four practice launches
(Marvel's Wolverine, Red Dead Redemption 2, God of War Ragnarök,
Marvel's Spider-Man 2), mean pinball loss on the log scale:

| entry | loss | typical miss | 90% coverage |
| --- | --- | --- | --- |
| this forecaster | 0.226 | 39.5% | 0.837 |
| house persistence baseline | 0.387 | 82.7% | 0.783 |

## Entry

- Competition: `gta6-twitch-ccu-forecast-01` (make.fun), $250 escrowed,
  20 places paid. Entries close 2026-11-19 01:00 UTC.
- License: MIT.
