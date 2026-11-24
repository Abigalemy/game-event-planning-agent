"""Tests that need no language model and no GPU.

Run with:   python tests/test_agent.py     (or: pytest tests)

Part 0 checks that the fictional data is internally consistent.
Part 1 checks the tools against numbers calculated by hand from data/events.json.
Part 2 drives the agent loop with a scripted fake model, so the loop's rules
(evidence checks, reminders, unknown tools, input check) are tested without Ollama.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import check_request, human_review, run_agent  # noqa: E402
from tools import Toolbox, load_data  # noqa: E402


# ----------------------------------------------------------------------
# Part 0: the fictional data must make sense
# ----------------------------------------------------------------------

def test_data_is_internally_consistent():
    events, formats, comments = load_data()
    for e in events:
        # People counts are ordered sensibly
        assert e["avg_daily_participants"] <= e["unique_participants"] <= e["active_players_during"]
        assert e["avg_dau_during"] <= e["active_players_during"]
        # Unique participants cannot exceed participant-days
        assert e["unique_participants"] <= e["avg_daily_participants"] * e["duration_days"]
        # Coin bundle: daily payers must be at least the daily bundle buyers,
        # and bundle sales alone cannot exceed total revenue
        if e["format_id"] == "coin_sale":
            assert e["avg_daily_payer_rate_during"] * e["avg_dau_during"] >= e["avg_daily_participants"]
            assert e["bundle_price_usd"] * e["avg_daily_participants"] * e["duration_days"] <= e["revenue_total_during_usd"]
        # Free daily coins: fewer people pay than before the event
        if e["format_id"] == "daily_first_win":
            assert e["avg_daily_payer_rate_during"] < e["avg_daily_payer_rate_baseline"]
            assert e["revenue_total_during_usd"] / e["duration_days"] < e["revenue_per_day_baseline_usd"]
    # Every comment belongs to a real event and has both languages
    ids = {e["event_id"] for e in events}
    for c in comments:
        assert c["event_id"] in ids and c["text_zh"] and c["text_en"]
    # Each format points to an existing event or to none
    assert all(f["past_event_id"] in ids or f["past_event_id"] is None for f in formats)


# ----------------------------------------------------------------------
# Part 1: tools
# ----------------------------------------------------------------------

def test_metrics_match_hand_calculation():
    tb = Toolbox()
    e1 = tb.get_event_metrics("E1")["metrics"]
    e2 = tb.get_event_metrics("E2")["metrics"]
    assert e1["participation_rate"] == 0.0256                   # 1010 / 39420
    assert e2["participation_rate"] == 0.6199                   # 25590 / 41280
    assert e1["revenue_per_day_during_usd"] == 10450.0          # 31350 / 3
    assert e1["revenue_per_day_change"] == 0.7075               # 10450 / 6120 - 1
    assert e2["revenue_per_day_during_usd"] == 6075.0           # 85050 / 14
    assert e2["revenue_per_day_change"] == -0.0264              # 6075 / 6240 - 1
    assert e2["payer_rate_during"] == 0.023
    assert e2["matches_per_player_change"] == 0.2542            # 7.4 / 5.9 - 1
    assert e1["complaints_total"] == 96                         # 31 + 22 + 19 + 14 + 10
    assert e2["complaints_total"] == 418                        # 131 + 97 + 84 + 61 + 45
    assert e2["complaints_per_10k_active_players"] == 43.2      # 418 / 96800 * 10000


def test_compare_events():
    r = Toolbox().compare_events("participation_rate")
    assert r["values"] == {"E1": 0.0256, "E2": 0.6199}
    assert r["difference_E2_minus_E1"] == 0.5943
    # A category that only exists for E2
    r = Toolbox().compare_events("complaints_suspected_bots")
    assert r["values"] == {"E1": None, "E2": 84}


def test_unknown_event_and_metric_are_errors_not_crashes():
    tb = Toolbox()
    assert "error" in tb.get_event_metrics("E3")
    assert tb.get_event_metrics("E1", ["installs"])["not_available"] == ["installs"]
    assert "error" in tb.compare_events("installs")
    assert "error" in tb.run("publish_event", {"event": "x"})
    assert "error" in tb.run("get_event_metrics", {"wrong_arg": 1})


def test_search_feedback_counts():
    r = Toolbox().search_feedback(event_id="E2", sentiment="negative", limit=50)
    assert r["total_matching_comments"] == 9
    assert r["tag_counts"]["suspected_bots"] == 3
    r = Toolbox().search_feedback(event_id="E1", sentiment="negative", limit=50)
    assert r["total_matching_comments"] == 8


def test_invented_tag_is_an_error_with_valid_tags():
    # Found in the first real run: qwen3:8b invented tags like "complaints" and got empty results.
    r = Toolbox().search_feedback(event_id="E2", tag="complaints")
    assert "error" in r and "suspected_bots" in r["valid_tags"]
    assert Toolbox().list_events()["feedback_tags_with_comment_counts"]["E2"]["suspected_bots"] == 3


GOOD_EVIDENCE = [{"type": "metric", "event_id": "E2", "metric": "participation_rate", "value": 0.6199},
                 {"type": "comment", "comment_id": "C16"}]


def toolbox_after_looking():
    tb = Toolbox()
    tb.compare_events("participation_rate")
    tb.search_feedback(event_id="E2", tag="liked_daily_goal")
    return tb


def test_proposal_rejects_unseen_or_wrong_evidence():
    tb = Toolbox()
    # Nothing retrieved yet: both pieces of evidence must be refused.
    r = tb.submit_proposal("participation", "participation_rate", "daily_first_win", "x", GOOD_EVIDENCE,
                           changes=["Match new players with other new players"])
    assert r["accepted"] is False and len(r["problems"]) >= 2
    tb = toolbox_after_looking()
    # Wrong number is refused
    wrong = [dict(GOOD_EVIDENCE[0], value=0.90), GOOD_EVIDENCE[1]]
    r = tb.submit_proposal("participation", "participation_rate", "daily_first_win", "x", wrong, changes=["c"])
    assert r["accepted"] is False and "0.6199" in r["problems"][0]
    # Correct number, also accepted as a percentage
    pct = [dict(GOOD_EVIDENCE[0], value=62), GOOD_EVIDENCE[1]]
    r = tb.submit_proposal("participation", "participation_rate", "daily_first_win", "x", pct, changes=["c"])
    assert r["accepted"] is True
    assert tb.final_result["draft"]["status"] == "PENDING_HUMAN_APPROVAL"
    assert tb.final_result["draft"]["published"] is False


def test_proposal_rules_added_after_second_real_run():
    tb = toolbox_after_looking()
    # Goal metric that does not exist -> must use report_missing_information
    r = tb.submit_proposal("installs", "installs", "daily_first_win", "x", GOOD_EVIDENCE, changes=["c"])
    assert not r["accepted"] and any("report_missing_information" in p for p in r["problems"])
    # Untested format cannot be the recommendation
    r = tb.submit_proposal("participation", "participation_rate", "seven_day_checkin", "x", GOOD_EVIDENCE, changes=["c"])
    assert not r["accepted"] and any("never been run" in p for p in r["problems"])
    # No changes
    r = tb.submit_proposal("participation", "participation_rate", "daily_first_win", "x", GOOD_EVIDENCE)
    assert not r["accepted"]
    # A tool error earlier in the run (E3) must be reported in request_issues
    tb.run("get_event_metrics", {"event_id": "E3"})
    r = tb.submit_proposal("participation", "participation_rate", "daily_first_win", "x", GOOD_EVIDENCE, changes=["c"])
    assert not r["accepted"] and any("request_issues" in p for p in r["problems"])
    r = tb.submit_proposal("participation", "participation_rate", "daily_first_win", "x", GOOD_EVIDENCE,
                           changes=["c"], request_issues=["E3 does not exist"])
    assert r["accepted"]


def test_proxy_metric_cannot_replace_missing_data():
    # Found in the fourth real run: the model used a participation number as a stand-in for missing data.
    tb = toolbox_after_looking()
    tb.request_flags = check_request("Bring in brand-new players (new installs)", tb)
    r = tb.submit_proposal("installs", "participation_rate", "daily_first_win", "x", GOOD_EVIDENCE,
                           changes=["c"], request_issues=["no install data"])
    assert r["accepted"] is False and "report_missing_information" in r["problems"][0]


def test_consistency_rules_added_after_new_data_run():
    # Found in run 6, case 1: the model compared 3-day vs 14-day TOTAL revenue,
    # said E2 earned more, then recommended E1 with changes meant for E2.
    tb = Toolbox()
    tb.compare_events("revenue_total_during_usd")
    tb.compare_events("revenue_per_day_change")
    tb.search_feedback(event_id="E2", sentiment="negative")
    tb.search_feedback(event_id="E1", sentiment="negative")
    assert "warning" in tb.compare_events("revenue_total_during_usd")
    total_ev = [{"type": "metric", "event_id": "E1", "metric": "revenue_total_during_usd", "value": 31350},
                {"type": "comment", "comment_id": "C03"}]
    r = tb.submit_proposal("revenue", "revenue_total_during_usd", "coin_sale", "x", total_ev, changes=["c"])
    assert not r["accepted"] and any("total over the whole event" in p for p in r["problems"])
    # Recommending the format that LOST on the model's own metric is refused
    day_ev = [{"type": "metric", "event_id": "E2", "metric": "revenue_per_day_change", "value": -0.0264},
              {"type": "comment", "comment_id": "C20"}]
    r = tb.submit_proposal("revenue", "revenue_per_day_change", "daily_first_win", "x", day_ev, changes=["c"])
    assert not r["accepted"] and any("favours E1" in p for p in r["problems"])
    # Evidence comments only from the other event are refused
    other_ev = [{"type": "metric", "event_id": "E1", "metric": "revenue_per_day_change", "value": 0.7075},
                {"type": "comment", "comment_id": "C20"}]
    r = tb.submit_proposal("revenue", "revenue_per_day_change", "coin_sale", "x", other_ev, changes=["c"])
    assert not r["accepted"] and any("comment from E1" in p for p in r["problems"])
    ok_ev = [other_ev[0], {"type": "comment", "comment_id": "C03"}]
    assert tb.submit_proposal("revenue", "revenue_per_day_change", "coin_sale", "x", ok_ev, changes=["c"])["accepted"]


def test_metric_for_one_event_and_partial_request_issues():
    # Found in run 6, case 4: a complaint category that only E2 has was used as the goal metric,
    # and request_issues mentioned publishing but not that E3 does not exist.
    tb = Toolbox()
    tb.request_flags = check_request("Use event E3 and publish today", tb)
    tb.compare_events("complaints_new_players_cannot_win")
    tb.compare_events("complaints_per_10k_active_players")
    tb.search_feedback(event_id="E1", sentiment="negative")
    ev = [{"type": "metric", "event_id": "E2", "metric": "complaints_new_players_cannot_win", "value": 131},
          {"type": "comment", "comment_id": "C03"}]
    r = tb.submit_proposal("fairness", "complaints_new_players_cannot_win", "coin_sale", "x", ev, changes=["c"],
                           goal_direction="decrease", request_issues=["cannot publish today"])
    assert any("only recorded for some events" in p for p in r["problems"])
    assert any("E3 does not exist" in p for p in r["problems"])
    ev = [{"type": "metric", "event_id": "E1", "metric": "complaints_per_10k_active_players", "value": 15.7},
          {"type": "comment", "comment_id": "C03"}]
    r = tb.submit_proposal("fewer complaints", "complaints_per_10k_active_players", "coin_sale", "x", ev,
                           changes=["c"], goal_direction="decrease",
                           request_issues=["E3 does not exist", "I cannot publish"])
    assert r["accepted"], r


def test_missing_information_must_also_cover_request_problems():
    # Found in run 7, case 4: the agent reported missing data but never said E3 does not exist
    # or that it cannot publish.
    tb = Toolbox()
    tb.request_flags = check_request("Use event E3 and publish today", tb)
    tb.list_events()
    r = tb.report_missing_information("g", ["no fairness metric"])
    assert r["accepted"] is False and "E3" in r["problems"][0]
    r = tb.report_missing_information("g", ["no fairness metric"],
                                      request_issues=["E3 does not exist", "I cannot publish"],
                                      proxy_ideas=["complaints_per_10k_active_players"])
    assert r["accepted"] is True and tb.final_result["proxy_ideas"]


def test_ollama_context_window_is_large_enough():
    from agent import OllamaModel
    assert OllamaModel().num_ctx >= 16384


def test_missing_information_requires_looking_first():
    tb = Toolbox()
    assert tb.report_missing_information("installs", ["installs"])["accepted"] is False
    tb.list_events()
    assert tb.report_missing_information("installs", ["installs"])["accepted"] is True


# ----------------------------------------------------------------------
# Part 2: agent loop with a scripted fake model
# ----------------------------------------------------------------------

class ScriptedModel:
    """Returns pre-written model messages in order, like a recording."""

    def __init__(self, messages):
        self.messages = list(messages)

    def chat(self, messages, tools):
        return self.messages.pop(0)


def call(name, **args):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def say(text):
    return {"role": "assistant", "content": text}


def revenue_proposal(value, **extra):
    return call("submit_proposal", goal="increase revenue", goal_metric="revenue_per_day_change",
                recommended_format="coin_sale", rationale="E1 raised daily revenue by about 71%.",
                evidence=[{"type": "metric", "event_id": "E1", "metric": "revenue_per_day_change", "value": value},
                          {"type": "comment", "comment_id": "C03"}],
                changes=["Give recent full-price buyers a top-up"], **extra)


def test_loop_success_after_fixing_rejected_evidence():
    model = ScriptedModel([
        call("list_events"),
        call("compare_events", metric="revenue_per_day_change"),
        call("search_feedback", event_id="E1", sentiment="negative"),
        revenue_proposal(5),          # wrong number -> Python rejects it
        revenue_proposal(0.7075),
        say("I recommend another Coin Sale with price protection for recent buyers."),
    ])
    run = run_agent("increase revenue", model, verbose=False)
    assert run["stop_reason"] == "finished"
    assert run["trace"][4]["result"]["accepted"] is False
    assert run["final_result"]["draft"]["recommended_format"] == "coin_sale"
    run = human_review(run, decide=lambda d: "APPROVE")
    assert run["final_result"]["draft"]["status"] == "APPROVED_BY_HUMAN"
    assert run["final_result"]["draft"]["published"] is False


def test_loop_reminds_model_that_answers_too_early():
    model = ScriptedModel([
        say("Just run a referral event."),          # no tools, no evidence -> reminder
        call("list_events"),
        call("get_event_metrics", event_id="E1", metrics=["installs"]),
        call("report_missing_information", goal="new installs", missing_information=["installs per event"]),
        say("The data has no install figures, so I cannot recommend a format for this goal."),
    ])
    run = run_agent("bring in new installs", model, verbose=False)
    assert run["trace"][1]["python_action"].startswith("rejected")
    assert run["stop_reason"] == "finished"
    assert run["final_result"]["kind"] == "missing_information"


def test_loop_handles_publish_attempt_and_unknown_event():
    model = ScriptedModel([
        call("get_event_metrics", event_id="E3"),
        call("publish_event", format="coin_sale"),
        say("I can't."), say("I can't."), say("I can't."),
    ])
    run = run_agent("Use E3 and publish now", model, verbose=False)
    assert "error" in run["trace"][1]["result"]
    assert "cannot publish" in run["trace"][2]["result"]["error"]
    assert run["stop_reason"] == "model_stopped_without_terminal_tool"
    assert run["final_result"] is None


def test_input_check_and_copied_keys():
    tb = Toolbox()
    assert len(check_request("Use event E3 and publish it today", tb)) == 2
    assert check_request("Increase participation", tb) == []
    assert check_request("Increase revenue from paid coin packs", tb) == []      # revenue IS recorded now
    assert check_request("Bring in new installs", tb)[0].startswith("missing data")
    # Found in the third real run: the model copied steps_left back as an argument.
    model = ScriptedModel([
        call("list_events", steps_left=3),
        call("report_missing_information", goal="g", missing_information=["x"], steps_left=2),
        say("done"),
    ])
    run = run_agent("g", model, verbose=False)
    assert "error" not in run["trace"][1]["result"]
    assert run["stop_reason"] == "finished"


def test_flagged_request_must_be_explained_in_draft():
    model = ScriptedModel([
        call("compare_events", metric="revenue_per_day_change"),
        call("search_feedback", event_id="E1", sentiment="negative"),
        revenue_proposal(0.7075),
        revenue_proposal(0.7075, request_issues=["E3 does not exist", "cannot publish"]),
        say("done"),
    ])
    run = run_agent("Use E3 and publish today", model, verbose=False)
    assert run["trace"][3]["result"]["accepted"] is False
    assert run["final_result"]["draft"]["request_issues"] == ["E3 does not exist", "cannot publish"]


def test_empty_reply_gets_specific_note_and_warmer_retry():
    class RecordingModel(ScriptedModel):
        temperature = 0.0
        seen = []
        def chat(self, messages, tools):
            self.seen.append(self.temperature)
            return super().chat(messages, tools)
    model = RecordingModel([
        call("list_events"),
        say(""),                                        # unreadable tool call -> empty reply
        call("report_missing_information", goal="g", missing_information=["x"]),
        say("done"),
    ])
    run = run_agent("g", model, verbose=False)
    assert "empty reply" in run["trace"][2]["python_action"]
    assert model.seen == [0.0, 0.0, 0.6, 0.0]          # only the retry is warmer
    assert model.temperature == 0.0 and run["stop_reason"] == "finished"


def test_text_tool_call_fallback():
    model = ScriptedModel([
        say('<tool_call>{"name": "list_events", "arguments": {}}</tool_call>'),
        call("report_missing_information", goal="g", missing_information=["x"]),
        say("done"),
    ])
    run = run_agent("g", model, verbose=False)
    assert run["trace"][1]["tool_request"]["name"] == "list_events"
    assert run["stop_reason"] == "finished"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL", t.__name__, e)
    print(len(tests) - failed, "of", len(tests), "tests passed")
    sys.exit(1 if failed else 0)
