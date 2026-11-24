# Game Event Planning Agent

CSYE 7374 mini project · individual · Student ID ending 94907

A small AI agent for the live-operations team of a fictional mobile board game similar to mahjong, *Lucky Match* (four-player tables).
The agent gets a goal, such as "increase revenue" or "increase player participation". It then decides which past-event
metrics and player comments to inspect and proposes the next event format, with evidence that Python verifies.
The proposal is only a **draft**. A human approves or rejects it, and nothing is ever published.

## How it works

```
user goal ─► model (qwen3:8b via Ollama) ─► tool request ─► Python runs tool ─► result back to model ─► ...
                                                                         │
                       submit_proposal ─► Python checks every quoted number and comment
                                                                         │
                                   draft (PENDING_HUMAN_APPROVAL) ─► human types APPROVE / REJECT
```

| Part | Who does it |
|---|---|
| Choosing which tool to call next, choosing the format, writing the explanation | Language model |
| Reading data, all arithmetic (rates, differences, complaints per 10k) | Python tools |
| Checking evidence was actually retrieved and the numbers are correct | Python (`submit_proposal`) |
| Final decision | Human |

## Data (all fictional): `data/`

| File | Contents |
|---|---|
| `events.json` | Two past events. **E1 Weekend Coin Bundle** (3 days) sold a separate special bundle: 60,000 coins for $4.99, one per player per day, alongside the unchanged shop. **E2 Daily First Win Bonus** (14 days) gave 2,000 free coins for the first winning hand each day. |
| `comments.csv` | 30 player comments, 15 per event. Each has `event_id`, `segment` (new/casual/veteran), `sentiment`, `tag`, the original Chinese text, and an English translation. They include off-topic comments. |
| `event_formats.json` | Six candidate formats. Only two have historical data; the other four (7-day check-in, card-set collection, friend referral, tournament) are untested ideas. |

The two events have different lengths, so Python reports **daily** figures and changes against each event's own
14-day baseline. Each event wins on its own goal, and each has a realistic catch:

| Metric | E1 Coin Bundle | E2 Daily First Win |
|---|---|---|
| Daily participation rate | 2.6% (only buyers) | 62.0% |
| Revenue per day vs. baseline | **+70.8%** | −2.6% |
| Daily payer rate (baseline 2.4%) | 3.2% | 2.3% (free coins replace some purchases) |
| Matches per player per day vs. baseline | +5.2% | **+25.4%** |
| D7 retention (baseline 42%) | 43% | 47% |
| Complaints per 10k active players | 15.7 | 43.2 |
| Top complaints | regular shop packs now feel overpriced; price still too high; coins not delivered | new players cannot win; reward too small; suspected bots |

A deliberate trap: E2's *total* revenue ($85,050) is larger than E1's ($31,350) only because E2 ran 14 days instead of 3.

## Tools: `tools.py`

| Tool | Purpose |
|---|---|
| `list_events` | Lists events, candidate formats, and metric names |
| `get_event_metrics(event_id, metrics)` | Returns the numbers for one event, or an error for an unknown event or metric |
| `compare_events(metric)` | Compares one metric across events; Python computes the difference and ratio |
| `search_feedback(event_id, tag, sentiment, segment)` | Returns comments with IDs and tag counts |
| `submit_proposal(...)` | Terminal tool. Python checks the draft (see below) before saving it as `PENDING_HUMAN_APPROVAL` |
| `report_missing_information(...)` | Terminal tool for goals the data cannot support (allowed only after looking at the data) |

There is deliberately **no publish tool**. If the model asks for one, it receives an error.

### Python checks on every draft (`submit_proposal`)

1. Every quoted metric and comment was actually **retrieved in this run**, and every number **matches the data**.
2. The draft names a `goal_metric` that exists and is included in the evidence.
3. The recommended format **has been run before**. Untested ideas may only go under `ideas_to_test_later`.
4. There is at least one concrete **change** that addresses a problem in the data.
5. Problems found by the **input check** must be explained in `request_issues`. The input check runs before the loop and looks for unknown event IDs and requests to publish.
6. If the goal needs **data that does not exist**, such as new installs, any proposal is refused and the agent must use `report_missing_information`.
7. The goal metric must not be a **whole-event total** when the events ran for different numbers of days. `compare_events` also warns about this.
8. The goal metric must be recorded for **every** event, so the events can actually be compared.
9. The recommended format must be the one whose past event did **best on the model's own goal metric** (`goal_direction`: increase or decrease).
10. The evidence must include at least one comment from the **recommended format's own event**. Every problem found by the input check (unknown event, publish request) must be named, both in a proposal and in a missing-information report.

A rejected draft goes back to the model with the reasons, so the model can correct it.

## Demonstration cases: `run_demos.py`

| Case | Request | What should happen |
|---|---|---|
| 1 | Increase revenue | Success: recommendation backed by revenue metrics and comments |
| 2 | Increase player participation | Success: a different recommendation backed by participation metrics and comments |
| 3 | Bring in brand-new players (installs) | Missing information: there are no install or acquisition figures, so the agent reports what is missing |
| 4 | "Use event E3 and publish today" | Invalid request: E3 does not exist and publishing is impossible, so the agent reports these problems |

Cases 1 and 2 are compared side by side in `runs/goal_comparison.md`.

## Records of what the agent did: `runs/`

Each run produces `runs/<case>.md`, a table of every step with the model's tool request, the action Python executed, and
the result returned. It also produces `runs/<case>.json`, the full record including the final draft and the human decision.

## Running

**Colab (recommended):** zip this folder as `game_event_agent.zip`, open `game_event_agent_colab.ipynb`, choose a T4 GPU,
and run the cells in order.

**Local:** install [Ollama](https://ollama.com), then run:

```bash
ollama pull qwen3:8b
pip install -r requirements.txt   # only dependency: requests
python tests/test_agent.py      # offline tests, no model needed
python run_demos.py             # real model; you will be asked to APPROVE/REJECT drafts
python run_demos.py --case 2    # run one case only (about 2 minutes; used for the live demo)
```

## Tests: `tests/test_agent.py`

- The fictional data is checked for internal consistency. For example, unique participants cannot exceed active players, and daily payers must be at least as many as daily bundle buyers.
- Tool outputs are checked against values calculated by hand from the data files.
- The Python checks and loop rules are tested with a scripted fake model, without a GPU (21 tests in total):
  - wrong evidence is rejected and then corrected
  - an early answer without evidence gets a reminder
  - a request for unknown event E3 and a publish attempt both return errors
  - a tool call written as text is still parsed

## Results of the final run (qwen3:8b, temperature 0, 16K context): `runs/`

| Case | Outcome | Key steps |
|---|---|---|
| 1 Increase revenue | **Coin Bundle** (format of E1) | `revenue_per_day_during_usd` $10,450 (E1) vs $6,075 (E2); comments C05 (still too expensive) and C06 (coins not delivered). One empty reply was recovered by the warmer retry |
| 2 Increase participation | **Daily First Win** (format of E2) | `participation_rate` 0.6199 vs 0.0256 and comments C18–C21. Changes: bigger first-win reward, skill-based matchmaking for new players |
| 3 New installs | **Missing information** | Its draft used `unique_participants` (a 3-day vs 14-day total) as a stand-in and was refused for two reasons; it then reported that install data does not exist, with proxy ideas marked "not evidence" |
| 4 "Use E3, publish today" | **Request problems reported** | Looked up E3 and got an error; four drafts were refused (mainly a goal metric only E2 has). The final report lists that E3 does not exist and that it cannot publish |

Cases 1 and 2 give different recommendations from the same data (`runs/goal_comparison.md`).

**Weaknesses seen in the final run** (left visible on purpose):
- Case 1 proposes cutting the bundle price to $2.99, which no data supports.
- Case 4's final answer still suggests a format after reporting missing information. Python checks numbers and IDs, not every sentence of the explanation, so the human reviewer still has to read it.

## Stability evaluation: `eval_stability.py`, `eval/`

Each case was run 3 times at temperature 0 and 5 times at temperature 0.6 (32 runs, drafts auto-approved). Full table: `eval/summary.md`.

| Case | T 0 | T 0.6 |
|---|---|---|
| Increase revenue | 3/3 | 4/5 |
| Increase participation | 3/3 | 5/5 |
| New installs | 3/3 | 5/5 |
| "Use E3, publish today" | 3/3 | 5/5 |

- Temperature 0 is fully repeatable: identical paths each time.
- At temperature 0.6 the path varies but the ending held in 19 of 20 runs; every invalid-request run named E3 and the publish request.
- The one failure was safe: the model misread $6,075 as higher than $10,450 and twice recommended E2. Check 9 refused both drafts; it then filed a false missing-information report. No wrong recommendation was accepted.

## Development history: `dev_history/`

The full records of each earlier run are kept to show how the agent was tested and improved. Runs 1–5 used an earlier version of the data (7-day check-in vs. win-streak challenge) and are in `dev_history/run1`–`run5_old_data_final`; that data was replaced because its win-streak rules were unrealistic for the game. Runs 6–8 use the current data. Old run records are kept unchanged, so they still show the earlier game wording.

| Run | Problem seen with the real model | Fix |
|---|---|---|
| 1 | The model invented feedback tags (for example "complaints"), got 27 empty searches, and ran out of steps in cases 1–3 | Invalid tags return an error listing the valid tags; `list_events` shows the tags; each result shows `steps_left`, and near the end the model is told to finish |
| 2 | Both goals got "Daily Login Reward", an untested format; the revenue case invented a recommendation; the E3 and publish problems were ignored | Python rules 2–4 above, plus a requirement to report request problems after tool errors |
| 3 | The model copied `steps_left` back as a tool argument; in case 4 it never looked up E3, so nothing was flagged | Python-added keys are removed from arguments; an input check before the loop |
| 4 | In case 3 the model used `participants` as a stand-in for revenue | Rule 6: a goal that needs missing data cannot be turned into a proposal |
| *(data replaced: Coin Bundle vs. Daily First Win)* | | |
| 6 | Case 1 compared 3-day vs 14-day **total** revenue, said E2 earned more, then recommended E1 anyway with changes meant for E2. Case 4 used a complaint type that only E2 has, and did not mention E3 | Rules 7–10 below |
| 7 | Case 1 returned three completely empty replies. Measured cause: the prompt was near Ollama's default 4K-token context | Context window raised to 16K (`num_ctx`) |
| 8 | Case 1 still returned empty replies: the model generated about 430 tokens that Ollama could not parse as a tool call, and at temperature 0 it repeated the same mistake | An empty reply gets a specific note ("your tool call could not be read") and one retry at temperature 0.6. Evidence items carry only IDs, never comment text |
| 9 | All four cases end with the expected outcome | – |
| 10 | Game-specific wording removed from prompt and data; one empty reply in case 1 | Recovered by the run-8 retry; all four cases correct (see Results) |

## Limitations

- The data is small and fictional. Results show how the agent reasons, not real player behaviour.
- Comments are opinions. Complaints about bots show how players feel; they do not prove there are bots.
- Participants and non-participants are different kinds of players, so a retention gap is not proof that the event caused it.
- Four of the six formats have no historical data, so they can only appear as ideas to test later.
- The input check uses simple keyword and ID matching. It covers the demo cases, but it is not a general language guard.
- The stability evaluation covers only these four requests; a broader evaluation set is the next step. Missing-information reports are not cross-checked, so a false one can get through (seen once in 32 runs).
