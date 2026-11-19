# Data sources

Every dataset considered for this project: source, license, intended use, limitations, label mapping (PRD 10.2).
Searched 2026-11-20 on Hugging Face and Kaggle. **No public dataset is used for training or evaluation at this point.**

## Primary data: synthetic, generated here

| Item | Value |
|---|---|
| Source | `data_generator/` (this repository), seed 42, generator 1.1.0 |
| License | Same as the repository |
| Use | Training, validation, test, demo (ADR-0008, `docs/PRIVACY.md`) |
| Limitations | Reflects the generator's assumptions, not real Indonesian spending. See `docs/EDA.md` and `docs/DECISIONS.md` |

## Public candidates

Verified = the license, size and labels were read from the dataset card on 2026-11-20.

| Dataset | License | Size | Language / region | Labels | Real or synthetic | Verified | Decision |
|---|---|---|---|---|---|---|---|
| [DoDataThings/us-bank-transaction-categories-v2](https://huggingface.co/datasets/DoDataThings/us-bank-transaction-categories-v2) | MIT | 68,000 rows | English, US bank formats | 17 (Restaurants, Groceries, Shopping, Transportation, Entertainment, Utilities, Subscription, Healthcare, Insurance, Mortgage, Rent, Travel, Education, Personal Care, Transfer, Income, Fees), about 4,000 each | Synthetic, built from real US merchant names | Yes | **Not used** (see Q1 below). Possible later as a cross-domain sanity check |
| [Karthik-Eswar/indian-transaction-categorization-synthetic](https://huggingface.co/datasets/Karthik-Eswar/indian-transaction-categorization-synthetic) | MIT | 970 rows | English, Indian bank narrations (UPI/NEFT/IMPS) | 21 | Synthetic | Yes | Not used: too small, wrong region |
| [mitulshah/transaction-categorization](https://huggingface.co/datasets/mitulshah/transaction-categorization) | MIT | 4,501,043 rows | English; USA, UK, Canada, Australia, India | 10 broad categories | Mixed (synthetic + real data from other HF datasets, proportions not stated) | Yes | Not used: gated download, unclear provenance of real portion, coarse labels |
| [AgamiAI/Indian-Bank-Statements](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements) | Apache 2.0 (per search result) | not checked | Indian bank statements | not a categorization set | Stated to contain no real personal data | No | Not used |
| Kaggle: [entrepreneurlife/personal-finance](https://www.kaggle.com/datasets/entrepreneurlife/personal-finance), [apoorvwatsky/bank-transaction-data](https://www.kaggle.com/datasets/apoorvwatsky/bank-transaction-data), [ramyapintchy/personal-finance-data](https://www.kaggle.com/datasets/ramyapintchy/personal-finance-data), [ismetsemedov/personal-budget-transactions-dataset](https://www.kaggle.com/datasets/ismetsemedov/personal-budget-transactions-dataset) | MIT / CC0 / MIT / Apache 2.0 per search snippets | small (806 rows for the first; others not checked) | Indian or unspecified | mixed | Unknown or synthetic | **No** (search snippets only; Kaggle pages not opened) | Not used. Re-verify the license on the page before any use |
| ULB credit-card fraud (Kaggle) | not checked | not checked | European card transactions, anonymised features | fraud / not fraud | Real | No | Not used. PRD 10.2 allows it only to practice anomaly techniques; fraud is not personal unusual spending |

Searches found **no Indonesian-language, rupiah-denominated transaction dataset**. Licenses on Kaggle and Hugging Face can change; re-check before use.

## Q1 decision: public dataset for classifier generalization

**Decision: no public dataset is used for generalization testing.** The fallback in PRD §25 applies:
report results on the synthetic test split, the unseen-merchant test split, and the generator holdout variant, and state the limitation.

Reasons:
- Every candidate is English and synthetic or of unknown provenance, with US, UK or Indian merchants. None contains Indonesian merchants (Indomaret, GoFood, QRIS, DANA) or rupiah amounts, so a score on them would say little about the target domain.
- Label sets differ from `taxonomy-1` (for example Mortgage/Rent/Insurance/Travel have no equivalent). A mapping file would drop or merge many rows, and the result would mostly measure the mapping.
- The nearest fit (DoDataThings v2, MIT, 68k rows) is synthetic too, so it would not provide independent real-world evidence.

What this means for claims: the README and model card must say the classifier was only evaluated on synthetic data, and that real-world accuracy is unknown.

Optional later (not scheduled): map DoDataThings v2 to `taxonomy-1` in `config/label_maps/dodatathings_us_v2.yaml` (unmapped labels dropped and counted) and run it as a cross-domain sanity check, labelled as such. Revisit only if there is spare time after T-10.
