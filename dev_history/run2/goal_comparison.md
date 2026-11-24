# Same data, two goals

| Goal | Recommended format | Changes | Verified evidence | Tools used (in order) |
|---|---|---|---|---|
| Our goal for the next event is to INCREASE PA... | Daily Login Reward |  | participation_rate, participation_rate, C21, C28, C19, C26, C33, C04, C11 | list_events() -> compare_events(participation_rate) -> search_feedback(E2, negative, matchmaking_wait) -> search_feedback(E2, negative, disconnect_broke_streak) -> search_feedback(negative, rewards_too_small, E1) -> submit_proposal |
| Our goal for the next event is to REDUCE PLAY... | Daily Login Reward |  | complaints_total, complaints_total, C17, C29, C23, C33, C21 | list_events() -> compare_events(complaints_total) -> search_feedback(E2, unfair_tile_deal, 5, veteran) -> search_feedback(suspected_collusion, E2, 5, veteran) -> search_feedback(E2, 5, veteran, disconnect_broke_streak) -> search_feedback(E2, 5, veteran, reward_too_hard) -> search_feedback(E2, 5, veteran, matchmaking_wait) -> search_feedback(E2, 5, veteran, reward_not_received_bug) -> search_feedback(E2, 5, veteran, reward_too_hard) -> search_feedback(E2, 5, veteran, other) -> submit_proposal |
