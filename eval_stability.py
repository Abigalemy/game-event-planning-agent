"""Stability evaluation: run every demo case several times and score each run.

    python eval_stability.py                 # default plan: 3 runs at T=0, 5 runs at T=0.6
    python eval_stability.py --plan 0:1      # quick check: 1 run at T=0

A run is CORRECT when it ends with an accepted terminal tool AND the ending is
the one the case expects:
  1 revenue        -> proposal recommending coin_sale
  2 participation  -> proposal recommending daily_first_win
  3 installs       -> missing-information report
  4 invalid        -> any accepted ending (Python only accepts it once E3 and
                      the publish request are named), but not a format that
                      ignores the request problems

Drafts are approved automatically; the human step is not what is measured here.
Results go to eval/: one JSON per run, plus eval/summary.md.
"""

import json
import sys
import time
from pathlib import Path

from agent import OllamaModel, human_review, run_agent
from run_demos import CASES
from tools import Toolbox

EXPECTED = {
    "1_increase_revenue": ("proposal", "coin_sale"),
    "2_increase_participation": ("proposal", "daily_first_win"),
    "3_missing_install_data": ("missing_information", None),
    "4_invalid_request": ("any", None),
}


def score(name, run):
    res = run.get("final_result")
    kind, fmt = EXPECTED[name]
    if run["stop_reason"] not in ("finished", "finished_without_summary") or not res:
        return False, "no accepted ending (" + run["stop_reason"] + ")"
    if kind == "any":
        return True, res["kind"]
    if res["kind"] != kind:
        return False, "ended with " + res["kind"]
    if fmt and res["draft"]["recommended_format"] != fmt:
        return False, "recommended " + res["draft"]["recommended_format"]
    return True, res["kind"] if kind != "proposal" else fmt


def stats(run):
    trace = run["trace"]
    tool_steps = [t for t in trace if t["tool_request"]]
    rejected = sum(1 for t in tool_steps if isinstance(t["result"], dict) and t["result"].get("accepted") is False)
    errors = sum(1 for t in tool_steps if isinstance(t["result"], dict) and "error" in t["result"])
    empty = sum(1 for t in trace if "empty reply" in t["python_action"])
    reminders = sum(1 for t in trace if t["python_action"].startswith("rejected answer"))
    steps = max(t["step"] for t in trace)
    return {"steps": steps, "tool_calls": len(tool_steps), "drafts_rejected": rejected,
            "tool_errors": errors, "empty_replies": empty, "reminders": reminders}


def main():
    plan = [(0.0, 3), (0.6, 5)]
    if "--plan" in sys.argv:
        spec = sys.argv[sys.argv.index("--plan") + 1]
        plan = [(float(t), int(n)) for t, n in (p.split(":") for p in spec.split(","))]
    out = Path("eval")
    out.mkdir(exist_ok=True)
    rows = []
    for temperature, repeats in plan:
        model = OllamaModel(temperature=temperature)
        for i in range(1, repeats + 1):
            for name, request in CASES.items():
                started = time.time()
                try:
                    run = run_agent(request, model, Toolbox(), verbose=False)
                    run = human_review(run, decide=lambda d: "APPROVE")
                except Exception as e:  # a crash is a failed run, not a stopped evaluation
                    run = {"request": request, "stop_reason": "crash: " + repr(e)[:200], "final_result": None,
                           "final_answer": None, "trace": [{"step": 0, "tool_request": None,
                                                            "python_action": "crash", "result": None}]}
                ok, why = score(name, run)
                row = {"case": name, "temperature": temperature, "repeat": i, "correct": ok, "outcome": why,
                       "seconds": round(time.time() - started), **stats(run)}
                rows.append(row)
                print(json.dumps(row), flush=True)
                tag = "T{:.1f}_r{}_{}".format(temperature, i, name)
                with open(out / (tag + ".json"), "w", encoding="utf-8") as f:
                    json.dump({**row, "run": run}, f, indent=1, ensure_ascii=False, default=str)
    write_summary(rows, out / "summary.md")


def write_summary(rows, path):
    lines = ["# Stability evaluation", "",
             "Each case run repeatedly with qwen3:8b. Correct = the expected ending was accepted by Python.", "",
             "| Case | Temperature | Correct | Avg steps | Drafts rejected (avg) | Runs with empty replies | Avg seconds |",
             "|---|---|---|---|---|---|---|"]
    for name in CASES:
        for t in sorted({r["temperature"] for r in rows}):
            rs = [r for r in rows if r["case"] == name and r["temperature"] == t]
            if not rs:
                continue
            n = len(rs)
            lines.append("| {} | {} | {}/{} | {:.1f} | {:.1f} | {} | {:.0f} |".format(
                name, t, sum(r["correct"] for r in rs), n, sum(r["steps"] for r in rs) / n,
                sum(r["drafts_rejected"] for r in rs) / n, sum(1 for r in rs if r["empty_replies"]),
                sum(r["seconds"] for r in rs) / n))
    lines += ["", "## Every run", "", "| Case | T | # | Correct | Outcome | Steps | Rejected | Empty | Reminders |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| {case} | {temperature} | {repeat} | {c} | {outcome} | {steps} | {drafts_rejected} | "
                     "{empty_replies} | {reminders} |".format(c="yes" if r["correct"] else "**no**", **r))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
