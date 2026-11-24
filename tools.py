"""Python tools for the Game Event Planning Agent.

The language model never reads the data files directly. It asks for a tool,
Python runs the tool, and the result is sent back to the model as an observation.

Every tool returns a plain dictionary. Errors are returned as {"error": ...}
instead of raising, so the model can see what went wrong and try something else.

The Toolbox also remembers which metrics and comments were actually returned
during this run. submit_proposal uses that memory to reject evidence the agent
never looked at, or numbers that do not match the data.
"""

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# Metrics that add up over the whole event. Events of different length cannot be compared on these.
PERIOD_TOTALS = ("revenue_total_during_usd", "unique_participants", "active_players_during",
                 "complaints_total", "first_time_payers")


def load_data(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    with open(data_dir / "events.json", encoding="utf-8") as f:
        events = json.load(f)["events"]
    with open(data_dir / "event_formats.json", encoding="utf-8") as f:
        formats = json.load(f)["formats"]
    with open(data_dir / "comments.csv", encoding="utf-8", newline="") as f:
        comments = list(csv.DictReader(f))
    return events, formats, comments


def flat_metrics(event):
    """Turn one event record into a flat {metric_name: number} dictionary.

    Rates such as participation_rate are calculated here in Python, so the
    model never has to do arithmetic itself.
    """
    e = event
    days = e["duration_days"]
    m = {"duration_days": days}

    # Players and participation (daily averages, so events of different length can be compared)
    m["avg_dau_during"] = e["avg_dau_during"]
    m["avg_dau_baseline"] = e["avg_dau_baseline"]
    m["dau_change"] = round(e["avg_dau_during"] / e["avg_dau_baseline"] - 1, 4)
    m["avg_daily_participants"] = e["avg_daily_participants"]
    m["participation_rate"] = round(e["avg_daily_participants"] / e["avg_dau_during"], 4)
    m["unique_participants"] = e["unique_participants"]
    m["active_players_during"] = e["active_players_during"]

    # Revenue (USD)
    base = e["revenue_per_day_baseline_usd"]
    per_day = e["revenue_total_during_usd"] / days
    m["revenue_total_during_usd"] = e["revenue_total_during_usd"]
    m["revenue_per_day_during_usd"] = round(per_day, 1)
    m["revenue_per_day_baseline_usd"] = base
    m["revenue_per_day_change"] = round(per_day / base - 1, 4)
    m["payer_rate_during"] = e["avg_daily_payer_rate_during"]
    m["payer_rate_baseline"] = e["avg_daily_payer_rate_baseline"]
    m["first_time_payers"] = e["first_time_payers"]

    # Engagement and retention
    m["matches_per_player_per_day_during"] = e["avg_matches_per_player_per_day_during"]
    m["matches_per_player_per_day_baseline"] = e["avg_matches_per_player_per_day_baseline"]
    m["matches_per_player_change"] = round(e["avg_matches_per_player_per_day_during"]
                                           / e["avg_matches_per_player_per_day_baseline"] - 1, 4)
    m["d7_retention_during"] = e["d7_retention_during"]
    m["d7_retention_baseline"] = e["d7_retention_baseline"]
    m["d7_retention_lift"] = round(e["d7_retention_during"] - e["d7_retention_baseline"], 4)

    # Complaints
    total = sum(e["complaints_by_category"].values())
    m["complaints_total"] = total
    m["complaints_per_10k_active_players"] = round(total / e["active_players_during"] * 10000, 1)
    for category, count in e["complaints_by_category"].items():
        m["complaints_" + category] = count
    return m


def is_period_total(metric):
    return metric in PERIOD_TOTALS or (metric.startswith("complaints_") and metric != "complaints_per_10k_active_players")


def values_match(claimed, actual):
    """True if a number the model quoted matches the real value.

    Accepts small rounding (2%) and percentages written as 44 instead of 0.44.
    """
    try:
        claimed = float(claimed)
    except (TypeError, ValueError):
        return False
    tolerance = max(abs(actual) * 0.02, 0.005)
    if abs(claimed - actual) <= tolerance:
        return True
    if abs(actual) <= 1 and abs(claimed / 100 - actual) <= tolerance:
        return True
    return False


class Toolbox:
    DATA_TOOLS = ("list_events", "get_event_metrics", "compare_events", "search_feedback")

    def __init__(self, data_dir=DATA_DIR, drafts_dir=None):
        self.events, self.formats, self.comments = load_data(data_dir)
        self.events_by_id = {e["event_id"]: e for e in self.events}
        self.metrics_by_id = {e["event_id"]: flat_metrics(e) for e in self.events}
        self.formats_by_id = {f["format_id"]: f for f in self.formats}
        self.comments_by_id = {c["comment_id"]: c for c in self.comments}
        self.drafts_dir = Path(drafts_dir) if drafts_dir else None
        self.valid_tags = sorted({c["tag"] for c in self.comments})
        self.reset_run()

    def tag_counts_by_event(self):
        counts = {}
        for c in self.comments:
            per_event = counts.setdefault(c["event_id"], {})
            per_event[c["tag"]] = per_event.get(c["tag"], 0) + 1
        return counts

    def reset_run(self):
        """Forget what was seen. Called at the start of every agent run."""
        self.seen_metrics = set()   # (event_id, metric_name)
        self.seen_comments = set()  # comment_id
        self.data_tools_used = []
        self.errors_seen = []       # tool errors returned during this run (e.g. unknown event E3)
        self.request_flags = []     # problems Python found in the user's request before the loop
        self.final_result = None    # set by submit_proposal or report_missing_information

    # ------------------------------------------------------------------
    # Data tools
    # ------------------------------------------------------------------

    def list_events(self):
        self.data_tools_used.append("list_events")
        any_event = self.events[0]["event_id"]
        return {
            "events": [
                {"event_id": e["event_id"], "name": e["name"], "format_id": e["format_id"],
                 "dates": e["start_date"] + " to " + e["end_date"], "how_it_works": e["how_it_works"]}
                for e in self.events
            ],
            "candidate_formats": [
                dict(f, status=("tested in " + f["past_event_id"]) if f["past_event_id"]
                     else "untested idea: no data, can only be listed under ideas_to_test_later")
                for f in self.formats
            ],
            "available_metrics": sorted(set().union(*[set(m) for m in self.metrics_by_id.values()])),
            "feedback_tags_with_comment_counts": self.tag_counts_by_event(),
            "note": "Events ran for different numbers of days. Compare per-day and rate metrics, not totals. "
                    "Complaint categories differ between events, so metrics for " + any_event
                    + " may not exist for other events.",
        }

    def get_event_metrics(self, event_id, metrics=None):
        self.data_tools_used.append("get_event_metrics")
        if event_id not in self.metrics_by_id:
            return {"error": "Unknown event_id '" + str(event_id) + "'.",
                    "valid_event_ids": list(self.metrics_by_id)}
        all_metrics = self.metrics_by_id[event_id]
        if not metrics:
            metrics = list(all_metrics)
        if isinstance(metrics, str):
            metrics = [metrics]
        found, missing = {}, []
        for name in metrics:
            if name in all_metrics:
                found[name] = all_metrics[name]
                self.seen_metrics.add((event_id, name))
            else:
                missing.append(name)
        result = {"event_id": event_id, "event_name": self.events_by_id[event_id]["name"], "metrics": found}
        if missing:
            result["not_available"] = missing
            result["hint"] = "These metrics are not recorded for this event. Call list_events to see available metrics."
        return result

    def compare_events(self, metric):
        self.data_tools_used.append("compare_events")
        values = {}
        for event_id, all_metrics in self.metrics_by_id.items():
            if metric in all_metrics:
                values[event_id] = all_metrics[metric]
                self.seen_metrics.add((event_id, metric))
            else:
                values[event_id] = None
        if all(v is None for v in values.values()):
            return {"error": "Metric '" + str(metric) + "' is not recorded for any event.",
                    "hint": "Call list_events to see available metrics."}
        result = {"metric": metric, "values": values}
        durations = {e["event_id"]: e["duration_days"] for e in self.events}
        if is_period_total(metric) and len(set(durations.values())) > 1:
            result["warning"] = ("This is a total over the whole event, and the events ran different numbers of days "
                                 + str(durations) + ". Totals are not comparable; use a per-day or rate metric instead.")
        known = {k: v for k, v in values.items() if v is not None}
        if len(known) == 2:
            (a, va), (b, vb) = known.items()
            result["difference_" + b + "_minus_" + a] = round(vb - va, 4)
            if va != 0:
                result["ratio_" + b + "_over_" + a] = round(vb / va, 2)
        return result

    def search_feedback(self, event_id=None, tag=None, sentiment=None, segment=None, limit=8):
        self.data_tools_used.append("search_feedback")
        if event_id and event_id not in self.events_by_id:
            return {"error": "Unknown event_id '" + str(event_id) + "'.",
                    "valid_event_ids": list(self.events_by_id)}
        if tag and tag not in self.valid_tags:
            return {"error": "Unknown tag '" + str(tag) + "'.", "valid_tags": self.valid_tags,
                    "hint": "Use one of the valid tags, or leave tag empty to see all comments for an event."}
        if sentiment and sentiment not in ("positive", "neutral", "negative"):
            return {"error": "sentiment must be positive, neutral or negative."}
        if segment and segment not in ("new", "casual", "veteran"):
            return {"error": "segment must be new, casual or veteran."}
        matches = [
            c for c in self.comments
            if (not event_id or c["event_id"] == event_id)
            and (not tag or c["tag"] == tag)
            and (not sentiment or c["sentiment"] == sentiment)
            and (not segment or c["segment"] == segment)
        ]
        tag_counts = {}
        for c in matches:
            tag_counts[c["tag"]] = tag_counts.get(c["tag"], 0) + 1
        try:
            limit = max(1, min(int(limit), 15))
        except (TypeError, ValueError):
            limit = 8
        shown = matches[:limit]
        for c in shown:
            self.seen_comments.add(c["comment_id"])
        result = {"total_matching_comments": len(matches), "tag_counts": tag_counts, "comments": shown}
        if not matches:
            result["hint"] = ("No comments matched all of these filters. Use fewer filters "
                              "(for example only event_id and sentiment).")
        return result

    # ------------------------------------------------------------------
    # Terminal tools: the run ends after one of these succeeds
    # ------------------------------------------------------------------

    def submit_proposal(self, goal, goal_metric, recommended_format, rationale, evidence, changes=None,
                        request_issues=None, ideas_to_test_later=None, goal_direction="increase"):
        problems = []
        all_metric_names = set().union(*[set(m) for m in self.metrics_by_id.values()])
        if goal_metric not in all_metric_names:
            problems.append("goal_metric '" + str(goal_metric) + "' is not a recorded metric. If no recorded metric "
                            "measures this goal, do not recommend anything: call report_missing_information instead.")
        else:
            problems += self.goal_metric_problems(goal_metric, goal_direction, recommended_format)
        fmt = self.formats_by_id.get(recommended_format)
        if fmt is None:
            problems.append("recommended_format '" + str(recommended_format) + "' is not in the format catalog: "
                            + ", ".join(self.formats_by_id))
        elif not fmt["past_event_id"]:
            problems.append("Format '" + recommended_format + "' has never been run, so no evidence supports it. "
                            "Recommend a tested format (with changes) and put this idea in ideas_to_test_later.")
        if not changes:
            problems.append("List at least one concrete change in 'changes' that addresses a problem seen in the data.")
        missing_data = [f for f in self.request_flags if f.startswith("missing data: ")]
        if missing_data:
            problems.append("The goal needs data that does not exist (" + "; ".join(missing_data) + "). "
                            "A proxy metric is not evidence for this goal. Call report_missing_information "
                            "instead; you may mention proxy ideas there.")
        elif self.request_flags:
            not_covered = self.flags_not_covered(request_issues)
            if not_covered:
                problems.append("Python's input check found problems in the user's request that request_issues does "
                                "not mention: " + "; ".join(not_covered) + ". Explain each of them in request_issues.")
        elif self.errors_seen and not request_issues:
            problems.append("Tools returned errors in this run (" + "; ".join(self.errors_seen[:3]) + "). "
                            "If any of these come from the user's request, describe them in request_issues; "
                            "otherwise write request_issues: ['none'].")
        if not isinstance(evidence, list):
            evidence = []
            problems.append("evidence must be a list.")
        checked = []
        for item in evidence:
            if not isinstance(item, dict):
                problems.append("Each evidence item must be an object.")
                continue
            kind = item.get("type")
            if kind == "metric":
                ev, name = item.get("event_id"), item.get("metric")
                actual = self.metrics_by_id.get(ev, {}).get(name)
                if actual is None:
                    problems.append("Metric " + str(ev) + "." + str(name) + " does not exist.")
                elif (ev, name) not in self.seen_metrics:
                    problems.append("Metric " + ev + "." + name + " was never retrieved in this run. Look it up first.")
                elif not values_match(item.get("value"), actual):
                    problems.append("Metric " + ev + "." + name + " was quoted as " + str(item.get("value"))
                                    + " but the data says " + str(actual) + ".")
                else:
                    checked.append({"type": "metric", "event_id": ev, "metric": name, "value": actual})
            elif kind == "comment":
                cid = item.get("comment_id")
                if cid not in self.comments_by_id:
                    problems.append("Comment " + str(cid) + " does not exist.")
                elif cid not in self.seen_comments:
                    problems.append("Comment " + cid + " was never retrieved in this run. Search feedback first.")
                else:
                    c = self.comments_by_id[cid]
                    checked.append({"type": "comment", "comment_id": cid, "event_id": c["event_id"],
                                    "text_zh": c["text_zh"], "text_en": c["text_en"]})
            else:
                problems.append("Evidence type must be 'metric' or 'comment', got " + repr(kind) + ".")
        n_metric = sum(1 for e in checked if e["type"] == "metric")
        n_comment = sum(1 for e in checked if e["type"] == "comment")
        if n_metric < 1 or n_comment < 1:
            problems.append("Include at least one verified metric and one verified comment as evidence.")
        if goal_metric in all_metric_names and not any(e.get("metric") == goal_metric for e in checked):
            problems.append("Include the goal_metric '" + goal_metric + "' itself in the evidence.")
        if fmt and fmt["past_event_id"] and not any(
                e["type"] == "comment" and e["event_id"] == fmt["past_event_id"] for e in checked):
            problems.append("Include at least one player comment from " + fmt["past_event_id"]
                            + ", the event that used the recommended format, so the changes address its real problems.")
        if problems:
            return {"accepted": False, "problems": problems,
                    "instruction": "Fix these problems and call submit_proposal again."}

        draft = {
            "status": "PENDING_HUMAN_APPROVAL",
            "goal": goal,
            "goal_metric": goal_metric,
            "recommended_format": recommended_format,
            "format_name": fmt["name"],
            "historical_data": "Based on past event " + fmt["past_event_id"],
            "rationale": rationale,
            "changes": changes,
            "ideas_to_test_later": ideas_to_test_later or [],
            "request_issues": request_issues or [],
            "verified_evidence": checked,
            "published": False,
        }
        self.final_result = {"kind": "proposal", "draft": draft}
        return {"accepted": True, "status": draft["status"],
                "message": "Draft saved for a human to review. Nothing has been published. "
                           "Now give the user a short final summary."}

    def goal_metric_problems(self, goal_metric, goal_direction, recommended_format):
        """The model chooses the goal metric; Python checks the choice is used consistently."""
        problems = []
        if goal_direction not in ("increase", "decrease"):
            return ["goal_direction must be 'increase' or 'decrease'."]
        values = {ev: m.get(goal_metric) for ev, m in self.metrics_by_id.items()}
        if any(v is None for v in values.values()):
            return ["goal_metric '" + goal_metric + "' is only recorded for some events " + str(values)
                    + ", so it cannot show which event did better. Choose a metric recorded for every event."]
        durations = {e["event_id"]: e["duration_days"] for e in self.events}
        if is_period_total(goal_metric) and len(set(durations.values())) > 1:
            problems.append("goal_metric '" + goal_metric + "' is a total over the whole event, but the events ran "
                            + str(durations) + " days. Use a per-day or rate metric instead.")
            return problems
        best = max(values, key=values.get) if goal_direction == "increase" else min(values, key=values.get)
        fmt = self.formats_by_id.get(recommended_format)
        if fmt and fmt["past_event_id"] and fmt["past_event_id"] != best:
            problems.append("Your own goal_metric (" + goal_metric + ", goal: " + goal_direction + ") favours " + best
                            + ": " + str(values) + ". Recommend the format used in " + best
                            + ", or choose a goal_metric that better measures the goal.")
        return problems

    def flags_not_covered(self, request_issues):
        text = " ".join(str(i) for i in (request_issues or [])).lower()
        missing = []
        for flag in self.request_flags:
            if flag.startswith("event "):
                event_id = flag.split()[1]
                if event_id.lower() not in text:
                    missing.append(flag)
            elif "publish" in flag:
                if not any(w in text for w in ("publish", "schedul", "launch", "release", "go live")):
                    missing.append(flag)
            # "missing data" flags are handled separately: they force report_missing_information
        return missing

    def report_missing_information(self, goal, missing_information, checked_sources=None,
                                   request_issues=None, proxy_ideas=None):
        if not self.data_tools_used:
            return {"accepted": False,
                    "problems": ["You have not inspected any data yet. Check the data before saying information is missing."]}
        if not isinstance(missing_information, list):
            missing_information = [str(missing_information)]
        not_covered = self.flags_not_covered((request_issues or []) + missing_information)
        if not_covered:
            return {"accepted": False,
                    "problems": ["Python's input check found problems in the user's request that you have not "
                                 "mentioned: " + "; ".join(not_covered) + ". List each of them in request_issues."]}
        self.final_result = {"kind": "missing_information",
                             "goal": goal,
                             "missing_information": missing_information,
                             "request_issues": request_issues or [],
                             "proxy_ideas": proxy_ideas or [],
                             "checked_sources": checked_sources or [],
                             "tools_actually_used": sorted(set(self.data_tools_used))}
        return {"accepted": True,
                "message": "Recorded. No proposal was created. Now explain to the user what is missing."}

    # ------------------------------------------------------------------

    def run(self, name, arguments):
        """Run a tool by name. This is the only way the agent touches data."""
        tools = {
            "list_events": self.list_events,
            "get_event_metrics": self.get_event_metrics,
            "compare_events": self.compare_events,
            "search_feedback": self.search_feedback,
            "submit_proposal": self.submit_proposal,
            "report_missing_information": self.report_missing_information,
        }
        if name not in tools:
            result = {"error": "Tool '" + str(name) + "' does not exist. This agent cannot publish or change the game. "
                               "Available tools: " + ", ".join(tools)}
            self.errors_seen.append(result["error"])
            return result
        if not isinstance(arguments, dict):
            return {"error": "Tool arguments must be a JSON object."}
        try:
            result = tools[name](**arguments)
        except TypeError as e:
            result = {"error": "Bad arguments for " + name + ": " + str(e)}
        if isinstance(result, dict) and "error" in result:
            self.errors_seen.append(result["error"])
        return result


# ----------------------------------------------------------------------
# Tool descriptions sent to the model (Ollama / OpenAI function format)
# ----------------------------------------------------------------------

def _tool(name, description, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


EVIDENCE_ITEM = {
    "type": "object",
    "description": "Either {type:'metric', event_id, metric, value} or {type:'comment', comment_id}. "
                   "Give only the comment_id, never the comment text.",
    "properties": {
        "type": {"type": "string", "enum": ["metric", "comment"]},
        "event_id": {"type": "string"},
        "metric": {"type": "string"},
        "value": {"type": "number"},
        "comment_id": {"type": "string"},
    },
    "required": ["type"],
}

TOOL_SCHEMAS = [
    _tool("list_events",
          "List the past events, the candidate event formats, and the metric names that exist. Call this first."),
    _tool("get_event_metrics",
          "Get numeric results for one past event. Leave metrics empty to get all of them.",
          {"event_id": {"type": "string", "description": "E1 or E2"},
           "metrics": {"type": "array", "items": {"type": "string"}}},
          ["event_id"]),
    _tool("compare_events",
          "Compare one metric across all past events. Python calculates the difference and ratio.",
          {"metric": {"type": "string"}}, ["metric"]),
    _tool("search_feedback",
          "Search player comments. Returns matching comments with comment_id and counts by tag. "
          "Use few filters: event_id plus sentiment is usually enough.",
          {"event_id": {"type": "string"},
           "tag": {"type": "string", "enum": sorted({c["tag"] for c in load_data()[2]})},
           "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
           "segment": {"type": "string", "enum": ["new", "casual", "veteran"]},
           "limit": {"type": "integer"}}),
    _tool("submit_proposal",
          "Submit the recommended next event format as a DRAFT for human approval. It does not publish anything. "
          "Evidence must quote metrics and comments you actually retrieved.",
          {"goal": {"type": "string"},
           "goal_metric": {"type": "string",
                           "description": "The recorded metric that measures the goal, e.g. participation_rate"},
           "goal_direction": {"type": "string", "enum": ["increase", "decrease"],
                              "description": "Whether the goal wants goal_metric to go up or down"},
           "recommended_format": {"type": "string", "description": "A TESTED format_id from list_events"},
           "rationale": {"type": "string"},
           "evidence": {"type": "array", "items": EVIDENCE_ITEM},
           "changes": {"type": "array", "items": {"type": "string"},
                       "description": "Concrete design changes compared with the past event, each fixing a problem in the data"},
           "request_issues": {"type": "array", "items": {"type": "string"},
                              "description": "Parts of the user's request that could not be done or do not exist"},
           "ideas_to_test_later": {"type": "array", "items": {"type": "string"},
                                   "description": "Untested formats worth a small trial"}},
          ["goal", "goal_metric", "goal_direction", "recommended_format", "rationale", "evidence", "changes"]),
    _tool("report_missing_information",
          "Use this instead of submit_proposal when the data cannot support a recommendation for the goal.",
          {"goal": {"type": "string"},
           "missing_information": {"type": "array", "items": {"type": "string"}},
           "checked_sources": {"type": "array", "items": {"type": "string"}},
           "request_issues": {"type": "array", "items": {"type": "string"},
                              "description": "Parts of the user's request that could not be done or do not exist"},
           "proxy_ideas": {"type": "array", "items": {"type": "string"},
                           "description": "Optional: indirect signals a human might look at. Not evidence."}},
          ["goal", "missing_information"]),
]
