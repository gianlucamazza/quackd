# Flock mode

Several simulated Microducks cooperating on one task. Ships in v0.3, **simulator only**,
and labelled experimental. The demo:

```bash
uvx quackd run flock-kick --provider fake --seed 3
```

Three ducks split the search for a ball, the one that bids the shortest camera distance
wins the kick, and everyone else keeps clear. One GIF, one `flock.jsonl` you can read the
cooperation out of, zero API keys.

## What a flock is

2 to 4 ducks (the four colorways: Cream, Sky, Lavender, Graphite) in one shared arena on
one shared clock, each with its **own** safety executor enforcing the same `.duck`
contract: allowlist, budgets, machine enforced abort rules, per duck transcript. A
deterministic **coordinator** referees. Add a `flock:` block to a `.duck` file or pass
`--flock N` to any duck.

## The bus

All coordination crosses a tiny in process pub/sub bus, one message at a time, and every
message lands in `flock.jsonl`. Six message kinds: `TASK` (the plan), `BID` (a sighting
with the bidder's own camera distance estimate), `CLAIM` (the one kick permit), `ROLE`
(SEARCH a heading sector, KICK, YIELD, STOP), `HB` (heartbeat for the watchdog), `RESULT`
(kicked, miss, search empty, budget, aborted). The bus is a small protocol so a LAN bus
(MQTT) can slot in later for real robots. In v0.3 only the in process implementation
exists, and nobody ever awaits the bus, which keeps the shared clock deadlock free.

## The auction, in one paragraph

Contract Net, the same shape RoboCup teams use. The first `BID` opens a window of 0.4 s
of sim time. When it closes, the lowest camera distance wins, ties break on the member
name, and a previous kicker keeps its claim unless a challenger undercuts it by the
hysteresis margin (20 % by default), which stops role oscillation. The claim carries a
lease (6 s), a fixed fuse from the moment it is granted. A miss or an expired lease
releases the claim and the failed duck sits out a cooldown, during which it may keep
searching but cannot bid. A lost heartbeat also releases the claim, but that duck is
presumed dead and excluded for good. Either way everyone re-scans the full circle (the
ball has moved) and the auction runs again. Ducks cannot fall in the 2D simulator, so
fall handling waits for hardware.

## Roles

- **SEARCH**: orient to your heading sector (if `walk` is allowed), `search_scan` inside
  it, quack on a sighting (the theatrical part), publish a `BID`.
- **KICK**: `walk_to` the target, `kick`, report the result. The contract's criterion is
  total ball displacement, so a rally of short kicks counts.
- **YIELD**: stop, and back away when the coordinator's ground truth check says you are
  inside the minimum separation ring, or as blind courtesy when your own last ball
  estimate was.
- **STOP**: the run is over.

Each role step is one verb through that duck's own executor. A role change mid verb
preempts it cleanly and does not count as a failure.

## What the LLM does, and does not do

At most **one** model call per run: the planner may tune task parameters (target label,
approach distance, scan step, timeout) through a single forced tool call. Numeric
parameters are clamped into the schema's ranges, an invalid field is dropped on its own
(the valid ones survive), and a missing or broken call falls back to deterministic
defaults, logged. With `--provider fake` even that call is skipped and the plan is a pure
function. The auction, the roles and the steering are deterministic code. Per duck LLM
pilots and LLM negotiated bids are deliberately out of scope in v0.3: they would cost N
times the tokens and latency, and the demo does not need them to be honest.
`summary.json` records `planner.llm_calls` (0 or 1) as proof.

## Ground truth

The outcome is judged by the coordinator from sim telemetry (`ball_displacement_m`), not
from any model's claim. A member reporting a kick the world did not record turns the run
into a failure. Duck to duck safety separation is watched from world ground truth: while
a claim is live the coordinator measures every other duck's true distance to the kicker
and orders an intruder to retreat, with the motion still running through that duck's own
executor. The kicker's ball approach uses perception only, exactly like a solo run.

## Reading a flock run

```
runs/<timestamp>-flock-kick/
  flock.jsonl          # the coordinator's log: every bus message, auction, verb
  summary.json         # outcome, kicker, auctions, bids, planner proof, per duck rollup
  run.gif              # world view | the claimant's duck cam, with phase captions
  ducks/duck-0/        # per duck transcript.jsonl and frames/ (no summary.json on purpose)
```

Three annotated lines from a real `flock.jsonl`:

```jsonc
{"sim_t": 2.4, "kind": "bus", "msg": {"kind": "BID", "src": "duck-1", "ball_dist_m": 0.62}}
{"sim_t": 2.8, "kind": "auction_decision", "kicker": "duck-1", "bids": {"duck-1": 0.62}, "tie": false}
{"sim_t": 8.6, "kind": "bus", "msg": {"kind": "RESULT", "src": "duck-1", "status": "kicked", "ball_moved_m": 0.59}}
```

## The shared clock

Sim time is a shared resource: the world advances one tick only while every participant
(each duck and the coordinator) is asleep, and it freezes while anyone thinks. A slow LLM
therefore costs zero sim time, and with `--provider fake` and a fixed seed a flock run is
reproducible. Wall clock heartbeat scheduling is the one nondeterministic input, and it
only influences failure path timing, as in solo runs.

## Status and future work

Sim only. Nothing multi duck has run on hardware, and the acoustic channel stays
theatrical (a quack marks the sighting, Wi Fi would carry the real data). Future work,
labelled as such when it lands: a LAN bus (MQTT) implementing the same `Bus` protocol for
real robots, and hardware flocks once Microducks ship. See
[transport-status.md](transport-status.md) for the wider honesty table.
