# Background ML Pipeline

The application now uses a background lifecycle before any prediction is published.

## Flow

Football provider data -> persistent match store -> leakage-safe rolling features -> trained Poisson regression -> chronological validation -> log loss + calibration ECE -> feature/performance drift monitoring -> future-match prediction -> Gemini/Groq AI review -> approved/publishable predictions -> Streamlit slips/API.

The currently implemented trained model is scikit-learn Poisson regression. It predicts home and away goal means from rolling team/venue/league features and converts those means into coherent football-market probabilities using the existing score-distribution engine.

## Scheduled jobs

Daily workflow: `.github/workflows/ml_daily.yml`
Runs at 02:15 UTC every day and:
1. collects recent results plus upcoming fixtures;
2. settles previously stored predictions;
3. checks performance and feature drift;
4. trains a model when none exists or the model is due;
5. predicts the next 31 days;
6. sends the processed model candidates and quality/drift context through the AI review agent;
7. marks only AI-approved predictions as `approved`.

Weekly workflow: `.github/workflows/ml_weekly.yml`
Runs at 03:15 UTC every Monday and performs the same lifecycle with a longer history window and forced retraining.

GitHub scheduled workflows run from the default branch and use UTC unless a timezone is configured.

## Required GitHub Actions secrets

Create these repository secrets under GitHub -> Settings -> Secrets and variables -> Actions:

`DB_PATH`
`API_FOOTBALL_KEY`
`API_FOOTBALL_KEYS` (optional)
`FOOTBALL_PROVIDER`
`FOOTBALL_PROVIDER_CHAIN`
`FOOTBALL_PROVIDER_MODE`
`FOOTBALL_DATA_API_KEY` (optional)
`BSD_API_KEY` (optional)
`BIGBALLSDATA_API_KEY` (optional)
`ALLSPORTSAPI_API_KEY` (optional)
`ISPORTS_API_KEY` (optional)
`THESPORTSDB_API_KEY` (optional)
`GROQ_API_KEY`
`GROQ_MODEL` (optional)
`GEMINI_API_KEY`
`GEMINI_MODEL` (optional)

`DB_PATH` must point to the same persistent database used by the deployed API/Streamlit application. For the Render deployment, use the persistent PostgreSQL connection string rather than a local SQLite path.

## What is withheld

There is deliberately no statistical-only fallback in the Streamlit package generator. If the background model has not produced enough AI-approved predictions, the app shows that the package is not ready instead of publishing unreviewed picks.

The API endpoints:
`GET /ml/status`
`GET /ml/predictions?days=1`
`GET /ml/predict/{fixture_id}`

serve the stored AI-approved background predictions.

## Model monitoring

Each training run records:
- training and validation row counts;
- 1X2 multiclass log loss;
- calibration ECE;
- home/away goal MAE;
- feature reference distributions.

Each background run records:
- recent settled-prediction log loss versus validation log loss;
- feature drift score;
- a drift alert when performance or feature distributions move materially.

A retrained model that is materially worse than the active model (more than 5% higher validation log loss) is recorded but not activated.

## Operational note

The AI agent is the publication/review layer. The model fitting, metrics, drift checks and database writes remain deterministic application code so they are repeatable and auditable. The AI agent receives those computed results plus provider evidence and may approve/reject an existing model candidate, but it cannot invent a fixture, market, probability or data point.
