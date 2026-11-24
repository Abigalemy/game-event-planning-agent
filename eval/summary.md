# Stability evaluation

Each case run repeatedly with qwen3:8b. Correct = the expected ending was accepted by Python.

| Case | Temperature | Correct | Avg steps | Drafts rejected (avg) | Runs with empty replies | Avg seconds |
|---|---|---|---|---|---|---|
| 1_increase_revenue | 0.0 | 3/3 | 11.0 | 0.0 | 3 | 105 |
| 1_increase_revenue | 0.6 | 4/5 | 10.2 | 0.4 | 2 | 118 |
| 2_increase_participation | 0.0 | 3/3 | 8.0 | 0.0 | 0 | 65 |
| 2_increase_participation | 0.6 | 5/5 | 8.6 | 0.2 | 1 | 90 |
| 3_missing_install_data | 0.0 | 3/3 | 10.0 | 1.0 | 0 | 81 |
| 3_missing_install_data | 0.6 | 5/5 | 9.2 | 1.0 | 0 | 93 |
| 4_invalid_request | 0.0 | 3/3 | 12.0 | 4.0 | 0 | 233 |
| 4_invalid_request | 0.6 | 5/5 | 13.0 | 1.6 | 2 | 162 |

## Every run

| Case | T | # | Correct | Outcome | Steps | Rejected | Empty | Reminders |
|---|---|---|---|---|---|---|---|---|
| 1_increase_revenue | 0.0 | 1 | yes | coin_sale | 11 | 0 | 1 | 0 |
| 2_increase_participation | 0.0 | 1 | yes | daily_first_win | 8 | 0 | 0 | 0 |
| 3_missing_install_data | 0.0 | 1 | yes | missing_information | 10 | 1 | 0 | 0 |
| 4_invalid_request | 0.0 | 1 | yes | missing_information | 12 | 4 | 0 | 0 |
| 1_increase_revenue | 0.0 | 2 | yes | coin_sale | 11 | 0 | 1 | 0 |
| 2_increase_participation | 0.0 | 2 | yes | daily_first_win | 8 | 0 | 0 | 0 |
| 3_missing_install_data | 0.0 | 2 | yes | missing_information | 10 | 1 | 0 | 0 |
| 4_invalid_request | 0.0 | 2 | yes | missing_information | 12 | 4 | 0 | 0 |
| 1_increase_revenue | 0.0 | 3 | yes | coin_sale | 11 | 0 | 1 | 0 |
| 2_increase_participation | 0.0 | 3 | yes | daily_first_win | 8 | 0 | 0 | 0 |
| 3_missing_install_data | 0.0 | 3 | yes | missing_information | 10 | 1 | 0 | 0 |
| 4_invalid_request | 0.0 | 3 | yes | missing_information | 12 | 4 | 0 | 0 |
| 1_increase_revenue | 0.6 | 1 | yes | coin_sale | 10 | 0 | 1 | 0 |
| 2_increase_participation | 0.6 | 1 | yes | daily_first_win | 9 | 0 | 1 | 0 |
| 3_missing_install_data | 0.6 | 1 | yes | missing_information | 10 | 1 | 0 | 0 |
| 4_invalid_request | 0.6 | 1 | yes | missing_information | 14 | 1 | 1 | 0 |
| 1_increase_revenue | 0.6 | 2 | yes | coin_sale | 11 | 0 | 1 | 0 |
| 2_increase_participation | 0.6 | 2 | yes | daily_first_win | 8 | 0 | 0 | 0 |
| 3_missing_install_data | 0.6 | 2 | yes | missing_information | 10 | 1 | 0 | 0 |
| 4_invalid_request | 0.6 | 2 | yes | missing_information | 12 | 3 | 1 | 0 |
| 1_increase_revenue | 0.6 | 3 | yes | coin_sale | 9 | 0 | 0 | 0 |
| 2_increase_participation | 0.6 | 3 | yes | daily_first_win | 8 | 0 | 0 | 0 |
| 3_missing_install_data | 0.6 | 3 | yes | missing_information | 8 | 1 | 0 | 0 |
| 4_invalid_request | 0.6 | 3 | yes | missing_information | 13 | 2 | 0 | 0 |
| 1_increase_revenue | 0.6 | 4 | yes | coin_sale | 8 | 0 | 0 | 0 |
| 2_increase_participation | 0.6 | 4 | yes | daily_first_win | 8 | 0 | 0 | 0 |
| 3_missing_install_data | 0.6 | 4 | yes | missing_information | 8 | 1 | 0 | 0 |
| 4_invalid_request | 0.6 | 4 | yes | missing_information | 13 | 1 | 0 | 0 |
| 1_increase_revenue | 0.6 | 5 | **no** | ended with missing_information | 13 | 2 | 0 | 0 |
| 2_increase_participation | 0.6 | 5 | yes | daily_first_win | 10 | 1 | 0 | 0 |
| 3_missing_install_data | 0.6 | 5 | yes | missing_information | 10 | 1 | 0 | 0 |
| 4_invalid_request | 0.6 | 5 | yes | missing_information | 13 | 1 | 0 | 0 |
