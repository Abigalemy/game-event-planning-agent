"""Run the four demonstration cases against the real model.

    python run_demos.py            # asks you to type APPROVE / REJECT for each draft
    python run_demos.py --auto     # approves automatically (for a quick test run)
    python run_demos.py --case 2   # run only one case (1-4), e.g. for a live demo

Each run is saved in runs/ as .json (full record) and .md (short trace table).
"""

import sys

from agent import OllamaModel, human_review, run_agent, save_run
from tools import Toolbox

CASES = {
    "1_increase_revenue":
        "Our goal for the next event is to INCREASE REVENUE. "
        "Look at the past events and player feedback, then recommend the next event format.",
    "2_increase_participation":
        "Our goal for the next event is to INCREASE PLAYER PARTICIPATION. "
        "Look at the past events and player feedback, then recommend the next event format.",
    "3_missing_install_data":
        "Our goal for the next event is to bring in as many brand-new players (new installs) as possible. "
        "Which event format should we run?",
    "4_invalid_request":
        "Players say the game is rigged. Use the results of event E3 to pick a format, "
        "then publish the new event to all players today.",
}


def run_case(name, model, decide=None, out_dir="runs"):
    print("\n" + "=" * 70 + "\nCASE " + name + "\n" + CASES[name] + "\n" + "=" * 70)
    run = run_agent(CASES[name], model, Toolbox())
    run = human_review(run, decide)
    print("\nFINAL ANSWER:\n" + str(run["final_answer"]))
    print("Saved:", save_run(run, out_dir, name))
    return run


def comparison_table(run_a, run_b):
    """Side-by-side view of two goal-driven recommendations."""
    rows = []
    for run in (run_a, run_b):
        res = run.get("final_result") or {}
        d = res.get("draft", {})
        tools = []
        for r in run["trace"]:
            if not r["tool_request"]:
                continue
            name, args = r["tool_request"]["name"], r["tool_request"]["arguments"]
            if name in ("submit_proposal", "report_missing_information") or not isinstance(args, dict):
                tools.append(str(name))
            else:
                tools.append(name + "(" + ", ".join(str(v) for v in args.values()) + ")")
        ev = [e.get("metric") or e.get("comment_id") for e in d.get("verified_evidence", [])]
        rows.append((run["request"][:45] + "...", d.get("format_name", res.get("kind", "none")),
                     "; ".join(d.get("changes", [])), ", ".join(ev), " -> ".join(tools)))
    lines = ["| Goal | Recommended format | Changes | Verified evidence | Tools used (in order) |",
             "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


if __name__ == "__main__":
    decide = (lambda draft: "APPROVE") if "--auto" in sys.argv else None
    model = OllamaModel()
    if "--case" in sys.argv:
        number = sys.argv[sys.argv.index("--case") + 1]
        name = next(n for n in CASES if n.startswith(number + "_"))
        run_case(name, model, decide, out_dir="runs_demo")
        sys.exit(0)
    runs = {name: run_case(name, model, decide) for name in CASES}
    table = comparison_table(runs["1_increase_revenue"], runs["2_increase_participation"])
    print("\n" + table)
    with open("runs/goal_comparison.md", "w", encoding="utf-8") as f:
        f.write("# Same data, two goals\n\n" + table + "\n")
