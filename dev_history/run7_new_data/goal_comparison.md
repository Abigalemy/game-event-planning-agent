# Same data, two goals

| Goal | Recommended format | Changes | Verified evidence | Tools used (in order) |
|---|---|---|---|---|
| Our goal for the next event is to INCREASE RE... | none |  |  | list_events() -> compare_events(revenue_per_day_during_usd) -> search_feedback(E1, price_still_too_high, 2) -> search_feedback(2, coins_not_delivered, E1) -> search_feedback(E2, 2, reward_too_small) -> search_feedback(E2, 2, new_players_cannot_win) -> get_event_metrics(['revenue_per_day_during_usd'], E1) -> get_event_metrics(E2, ['revenue_per_day_during_usd']) |
| Our goal for the next event is to INCREASE PL... | Daily First Win Bonus | Increase the reward for the first win to make it more valuable for players; Implement a skill-based matchmaking system to help new players compete more effectively; Offer additional incentives for daily participation to encourage continued engagement | participation_rate, participation_rate, C18, C19, C20, C21 | list_events() -> compare_events(participation_rate) -> search_feedback(E2, new_players_cannot_win, 3) -> search_feedback(E2, 3, reward_too_small) -> submit_proposal |
