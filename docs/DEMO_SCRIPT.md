# Demo video script (3 to 5 minutes)

The video itself has not been recorded. This is the script for it. Record against `make demo` (synthetic data only) and do not show real accounts.

| Time | Screen | Say |
|---|---|---|
| 0:00 | Landing / login | The problem: tracking spending by hand is tedious and nobody notices small or unusual costs. |
| 0:20 | Add a transaction | Type "Kopi Kenangan 25.000". The category preview appears with its confidence; save. |
| 0:50 | Transactions, needs review | A low-confidence one asks for a category. Correct it; the merchant rule is remembered and the next one is applied automatically. |
| 1:20 | CSV import | Upload the template, preview (valid / invalid / duplicate), commit atomically. |
| 1:50 | Dashboard | Period summary, category split, review queue, insights. |
| 2:20 | Budgets | Create a budget; a threshold notification. |
| 2:45 | Intelligence: Alerts, Forecast, Recurring, Spending style | An anomaly with its reason and the "it is normal" feedback; the forecast with P10/P50/P90; detected subscriptions; the user's segment and traits. |
| 3:45 | MLflow and Grafana | Registered model with metrics, alias `candidate`, shadow and rollback commands, the drift and latency dashboards. |
| 4:30 | Close | What is measured and what is not: synthetic data only, results in `docs/MODEL_EVALUATION.md`, limitations in the README. |

Do not quote a number in the video that is not in `docs/MODEL_EVALUATION.md`.
