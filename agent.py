"""Game Event Planning Agent: the agent loop.

The loop is written in plain Python, the same pattern as the class
Agent Airways script:

    ask the model -> model requests a tool -> Python runs the tool
    -> the result goes back to the model -> repeat until a terminal tool succeeds

The model only makes decisions. Python owns the data, the arithmetic,
the evidence checks, the trace, and the human approval step.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from tools import TOOL_SCHEMAS, Toolbox

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:8b"

SYSTEM_PROMPT = """You are an event planning assistant for the live-operations team of a mobile game.
Your job: recommend the format of the NEXT in-game event for the goal the user gives you.

How to work:
1. Call list_events first to see the past events, the candidate formats, and the metric names.
2. Decide which metrics matter for THIS goal and look them up with get_event_metrics or compare_events.
3. Decide which player comments matter for THIS goal and read them with search_feedback.
   Use only tag names listed by list_events. Two or three searches are normally enough.
4. Pick the recorded metric that measures the goal (goal_metric) and whether the goal wants it to
   increase or decrease. Events ran for different numbers of days, so use per-day or rate metrics, not totals.
   Choose the TESTED format whose past event did best on that metric, and add changes that fix the
   problems players complained about in THAT event.
   Untested formats have no evidence; you may only list them under ideas_to_test_later.
5. Finish with exactly one of these:
   - submit_proposal: a draft recommendation. Its evidence must quote metric values and comment_ids
     that you actually retrieved, including the goal_metric for each event. Python will check every number.
     Evidence items are short: {type, event_id, metric, value} or {type, comment_id}. Never copy comment text.
   - report_missing_information: when no recorded metric measures the goal (for example revenue,
     if there is no revenue metric) or the request depends on data that does not exist.
     Do not guess or invent numbers.
6. After the terminal tool is accepted, write a short final answer for the user that explains
   which observations support the choice and every part of the request you could not do.

Rules:
- You cannot publish, schedule, or change anything in the game. A human makes the final decision.
- Only use facts returned by tools. Player comments are opinions, not proof. For example,
  complaints about bots or a rigged game show how players feel, not that the game is broken.
- If a tool returns an error, read it and adjust your next request.
"""


# ----------------------------------------------------------------------
# Talking to the model
# ----------------------------------------------------------------------

class OllamaModel:
    """Calls a local Ollama server, as in the class notebooks."""

    def __init__(self, model=MODEL, url=OLLAMA_URL, temperature=0.0, think=False, timeout=300, num_ctx=16384):
        self.model, self.url = model, url
        self.temperature, self.think, self.timeout = temperature, think, timeout
        # Ollama's default context is about 4K tokens. A full run (tool list, results, comments in two
        # languages) grows past that, and the model's reply then comes back empty. Found in run 7.
        self.num_ctx = num_ctx

    def chat(self, messages, tools):
        import requests  # imported here so tests can run without it
        body = {"model": self.model, "messages": messages, "tools": tools, "stream": False,
                "think": self.think, "options": {"temperature": self.temperature, "num_ctx": self.num_ctx}}
        reply = requests.post(self.url, json=body, timeout=self.timeout)
        reply.raise_for_status()
        return reply.json()["message"]


def clean_text(text):
    """Remove <think>...</think> blocks that some Qwen models add."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def extract_tool_calls(message):
    """Return a list of (name, arguments) the model asked for.

    Normally Ollama gives structured tool_calls. Small models sometimes write the
    call as JSON text instead, so we also look for that. Anything we cannot parse
    is reported back to the model as an error rather than silently ignored.
    """
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_unparseable_arguments": args}
        calls.append((fn.get("name"), args))
    if calls:
        return calls
    text = clean_text(message.get("content"))
    for block in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, flags=re.DOTALL):
        try:
            obj = json.loads(block)
            calls.append((obj.get("name"), obj.get("arguments", {})))
        except json.JSONDecodeError:
            pass
    return calls


# ----------------------------------------------------------------------
# The agent loop
# ----------------------------------------------------------------------

PUBLISH_WORDS = ("publish", "launch", "go live", "push to all", "release to", "schedule", "send to all")

# Goals that need a kind of data. If the request mentions one and no metric name
# contains these words, the goal cannot be measured with this data.
DATA_NEEDS = {
    "revenue or player spending": ("revenue", "spend", "money", "paid", "purchase", "earn", "sales", "monetiz"),
    "event budget or cost": ("budget", "cost"),
    "new player acquisition (installs)": ("install", "acquisition", "acquire", "referral", "invite", "download"),
}
MISSING_DATA_PREFIX = "missing data: "


def check_request(user_request, toolbox):
    """Plain Python input check, run before the model sees anything.

    It does not answer the request. It only records problems that the final
    draft must mention: event IDs that do not exist, and requests to publish.
    """
    flags = []
    for event_id in sorted(set(re.findall(r"\bE\d+\b", user_request))):
        if event_id not in toolbox.events_by_id:
            flags.append("event " + event_id + " does not exist in the data")
    lowered = user_request.lower()
    if any(word in lowered for word in PUBLISH_WORDS):
        flags.append("the request asks to publish or schedule, which this agent is not allowed to do")
    metric_names = " ".join(set().union(*[set(m) for m in toolbox.metrics_by_id.values()]))
    for concept, words in DATA_NEEDS.items():
        if any(w in lowered for w in words) and not any(w in metric_names for w in words):
            flags.append(MISSING_DATA_PREFIX + concept + " is not recorded for any event")
    return flags


# Keys that Python adds to tool results. Small models sometimes copy them back as arguments.
PYTHON_ADDED_KEYS = ("steps_left", "instruction")


def run_agent(user_request, model, toolbox=None, max_steps=15, max_reminders=2, finish_warning_at=5, verbose=True):
    toolbox = toolbox or Toolbox()
    toolbox.reset_run()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_request}]
    trace = []
    final_answer = None
    stop_reason = "max_steps_reached"
    reminders = 0
    previous_calls = {}
    retry_temperature = False

    def log(record):
        trace.append(record)
        if verbose:
            print_step(record)

    toolbox.request_flags = check_request(user_request, toolbox)
    log({"step": 0, "model_seconds": 0, "model_text": "", "tool_request": None,
         "python_action": "input check before the loop", "result": {"request_flags": toolbox.request_flags}})

    for step in range(1, max_steps + 1):
        started = time.time()
        if retry_temperature and hasattr(model, "temperature"):
            saved = model.temperature
            model.temperature = 0.6
            try:
                message = model.chat(messages, TOOL_SCHEMAS)
            finally:
                model.temperature = saved
        else:
            message = model.chat(messages, TOOL_SCHEMAS)
        retry_temperature = False
        seconds = round(time.time() - started, 1)
        text = clean_text(message.get("content"))
        calls = extract_tool_calls(message)

        assistant_msg = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            assistant_msg["tool_calls"] = message["tool_calls"]
        messages.append(assistant_msg)

        if not calls:
            if toolbox.final_result is not None:
                final_answer = text
                stop_reason = "finished"
                log({"step": step, "model_seconds": seconds, "model_text": text,
                     "tool_request": None, "python_action": "accepted final answer", "result": None})
                break
            reminders += 1
            if not text:
                # Found in run 8: the model wrote a tool call Ollama could not parse (e.g. invalid JSON),
                # and Ollama returned an empty message. At temperature 0 it repeats the same mistake,
                # so the next attempt uses a slightly higher temperature.
                note = ("Your last reply arrived empty: your tool call could not be read, probably because its "
                        "JSON was invalid. Try again with short arguments: evidence items only need "
                        "type, event_id, metric, value or type, comment_id (do not copy comment text), "
                        "and keep rationale under 80 words.")
                action = "empty reply (unreadable tool call); sent note and raised temperature for retry"
                retry_temperature = True
            else:
                note = ("You have not finished. Call submit_proposal or report_missing_information "
                        "(after checking the data) before giving a final answer.")
                action = "rejected answer without a terminal tool; sent reminder"
            log({"step": step, "model_seconds": seconds, "model_text": text, "tool_request": None,
                 "python_action": action, "result": note})
            if reminders > max_reminders:
                stop_reason = "model_stopped_without_terminal_tool"
                break
            messages.append({"role": "user", "content": note})
            continue

        for name, args in calls:
            if isinstance(args, dict):
                args = {k: v for k, v in args.items() if k not in PYTHON_ADDED_KEYS}
            key = json.dumps([name, args], sort_keys=True, default=str)
            previous_calls[key] = previous_calls.get(key, 0) + 1
            if previous_calls[key] > 2:
                result = {"error": "You already made this exact request twice. Use the earlier result or try something else."}
                action = "blocked repeated call"
            else:
                result = toolbox.run(name, args)
                action = "ran " + str(name)
            # Budget awareness: small models otherwise keep searching until they run out of steps.
            steps_left = max_steps - step
            if toolbox.final_result is None and isinstance(result, dict):
                result = dict(result, steps_left=steps_left)
                if steps_left <= finish_warning_at:
                    result["instruction"] = ("Stop gathering data. Use what you already retrieved and call "
                                             "submit_proposal or report_missing_information now.")
                    action += "; told model to finish"
            log({"step": step, "model_seconds": seconds, "model_text": text,
                 "tool_request": {"name": name, "arguments": args},
                 "python_action": action, "result": result})
            messages.append({"role": "tool", "tool_name": str(name),
                             "content": json.dumps(result, ensure_ascii=False)})

    if final_answer is None and toolbox.final_result is not None:
        final_answer = "(The model did not write a summary. See the accepted draft.)"
        stop_reason = "finished_without_summary"

    return {"request": user_request, "stop_reason": stop_reason, "final_answer": final_answer,
            "final_result": toolbox.final_result, "trace": trace}


# ----------------------------------------------------------------------
# Human approval (Python, never the model)
# ----------------------------------------------------------------------

def human_review(run, decide=None):
    """Show the draft to a person. decide(draft) -> 'APPROVE' or 'REJECT'.

    Approval only marks the draft as approved for planning. Nothing is published.
    """
    result = run.get("final_result")
    if not result or result["kind"] != "proposal":
        return run
    draft = result["draft"]
    print("\n=== DRAFT FOR HUMAN REVIEW ===")
    print(json.dumps(draft, indent=2, ensure_ascii=False))
    if decide is None:
        answer = input("Type APPROVE to accept this draft for planning, anything else to reject: ")
    else:
        answer = decide(draft)
    draft["status"] = "APPROVED_BY_HUMAN" if answer.strip().upper() == "APPROVE" else "REJECTED_BY_HUMAN"
    draft["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    draft["published"] = False
    print("Status:", draft["status"], "(nothing was published)")
    return run


# ----------------------------------------------------------------------
# Trace output
# ----------------------------------------------------------------------

def short(obj, limit=400):
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + " ...(truncated)"


def print_step(r):
    print("-" * 70)
    print("Step", r["step"], "(" + str(r["model_seconds"]) + "s)")
    if r["model_text"]:
        print("Model said:", r["model_text"][:300])
    if r["tool_request"]:
        print("Model requested:", r["tool_request"]["name"], short(r["tool_request"]["arguments"], 300))
    print("Python:", r["python_action"])
    if r["result"] is not None:
        print("Result:", short(r["result"]))


def save_run(run, out_dir, name):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / (name + ".json"), "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2, ensure_ascii=False, default=str)
    lines = ["# Run: " + name, "", "**Request:** " + run["request"], "",
             "**Stop reason:** " + run["stop_reason"], "",
             "| Step | Model's tool request | Python action | Result (shortened) |",
             "|---|---|---|---|"]
    for r in run["trace"]:
        req = (r["tool_request"]["name"] + " " + short(r["tool_request"]["arguments"], 150)) if r["tool_request"] else "(no tool)"
        res = short(r["result"], 220) if r["result"] is not None else ""
        lines.append("| " + " | ".join([str(r["step"]), req, r["python_action"], res]).replace("\n", " ") + " |")
    lines += ["", "## Final answer", "", run["final_answer"] or "(none)", "",
              "## Final result", "", "```json", json.dumps(run["final_result"], indent=2, ensure_ascii=False), "```"]
    with open(out_dir / (name + ".md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_dir / (name + ".md")
