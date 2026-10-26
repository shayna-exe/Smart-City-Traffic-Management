# Smart City Traffic Management System

A Flask web application that simulates traffic on four roads, classifies congestion with a machine-learning model, estimates emissions, recommends an emergency corridor and shows everything on a live dashboard.

> **All traffic data is simulated.** No real sensors, maps or air-quality instruments are used, and nothing in the project claims otherwise.

## 1. Problem statement and objectives
City traffic operators need a quick view of which roads are congested and where emergency vehicles should go. This project demonstrates that pipeline end to end on simulated data: **simulate → classify (ML) → store (SQLite) → analyse → display**.

Objectives: consistent congestion classification; a reproducible, honestly evaluated ML model; transparent emission and air-quality estimates; a clear emergency-corridor rule; a responsive auto-updating dashboard; a simple local run and a documented Azure deployment.

## 2. Features (all implemented)
- Built-in simulator (4 roads, one reading per road every 5 s), started automatically with the app.
- Decision-tree congestion classifier (LOW / MEDIUM / HIGH), trained automatically on first run.
- Dashboard: total vehicles, average speed, congested roads, estimated CO₂, per-road status, emergency corridor, vehicle and speed trend charts (hover tooltips, legend toggles), congestion mix, recent records table, a "Classify" what-if form, and a live / stalled / offline indicator. It updates by polling JSON endpoints, with no page reloads.
- JSON API: `/api/summary`, `/api/records?limit=`, `/api/trends`, `/api/predict?cars=&speed=`, `/api/model`, `/api/health`.

## 3. Architecture
```
app.py                  entry point (python app.py / gunicorn app:app)
train_model.py          CLI: train + evaluate the model
simulate.py             CLI: standalone simulator (alternative to the built-in one)
smartcity/
  config.py             environment-driven settings
  traffic_rules.py      status names + congestion rules (single source of truth)
  simulator.py          traffic generator, background runner, single-writer lock
  ml.py                 training, evaluation, loading, prediction
  analysis.py           CO2 estimate, air-quality indicator, emergency corridor
  db.py                 SQLite access
  routes.py             pages and JSON API
templates/ static/      dashboard (HTML, CSS, JavaScript; charts are inline SVG, no CDN needed)
tests/                  unittest suite
azure/deploy.sh, startup.sh   Azure App Service deployment
```
Stack: Python 3.11+, Flask, SQLite, scikit-learn, NumPy, joblib; vanilla JavaScript; gunicorn in production.

**One pipeline only:** the web app owns the simulator thread. An OS file lock guarantees that only one simulator per machine writes, so several gunicorn workers, or `simulate.py` running next to the app, cannot create duplicate writers (the second one declines to start). The old `pipeline.py` and the conflicting old `simulator.py` were removed; `simulate.py` replaces them.

## 4. Congestion rules (the labels)
| Status | Rule |
|---|---|
| HIGH | speed < 20 km/h **and** ≥ 60 vehicles |
| MEDIUM | not HIGH, and (speed < 35 km/h **or** ≥ 60 vehicles) |
| LOW | otherwise |

Defined once in `smartcity/traffic_rules.py`; every module uses these exact strings.

## 5. Traffic simulation
Each road has a free-flow speed and a capacity. A demand level (0.05–1.0) follows a mean-reverting random walk with occasional surges; `cars = level × capacity (±5%)` and `speed = free-flow × (1 − 0.9 × level) + noise`, so speed falls as a road fills up. Set `SIM_SEED` for reproducible runs. Old rows are pruned beyond `RETENTION_MAX_ROWS`.

## 6. Machine-learning methodology
- **Model:** `DecisionTreeClassifier(max_depth=6)`, chosen because it is small and explainable.
- **Features:** vehicle count, average speed (km/h). **Classes:** LOW, MEDIUM, HIGH.
- **Training data:** 6000 reproducible synthetic samples (seed 42): half from the simulator's distribution, half uniform over the valid input range, labelled by the rules above. Synthetic training data is never stored as traffic records.
- **Evaluation:** stratified 75/25 train/test split, per-class precision/recall/F1, confusion matrix and 5-fold cross-validation. Results are saved to `data/traffic_model.metrics.json` and shown in the dashboard.
- **Honest interpretation:** the labels *are* deterministic threshold rules, so a tree learns them almost perfectly (about 100% on the held-out split when I ran it). This shows the model reproduces the rules. It does **not** show that the model predicts real traffic. Its value here is a demonstrable ML pipeline that could be retrained on real labelled data.
- **Lifecycle:** the model is loaded once at startup. It is trained if missing, corrupt, or built with a different scikit-learn version, and never retrained on page refresh. If it can be neither loaded nor trained, the app falls back to the rules, and the dashboard and `/api/health` say so (`predicted_by` is stored on every record).

## 7. Database
SQLite, table `traffic_records`: `id` (PK), `road`, `cars` (≥0), `speed` (≥0), `status` (LOW/MEDIUM/HIGH, CHECK constraint), `predicted_by` (`ml_model`/`rules`), `recorded_at` (UTC ISO). Index on `(road, id DESC)`. One short connection per operation, parameterised SQL, ordering by `id`, queries limited to recent rows. The file is created automatically in `data/`. The old `traffic.db` (random, unvalidated data in a different schema) is not carried over.

## 8. Estimates and assumptions
- **CO₂ (kg)** = vehicles × 1 km segment × EF(speed) ÷ 1000, with **EF = 90 + 2400 / speed g/km** (speed ≥ 5). The curve has the real-world shape (more per km in slow traffic, lowest near 60–80 km/h) but is an illustrative approximation, not COPERT/IPCC-calibrated. The 1 km segment length is an assumption.
- **Air-quality indicator:** Good < 6 kg, Moderate < 15 kg, otherwise Poor, based on the CO₂ estimate. It is **not an official AQI**; no pollutant concentrations are measured.

## 9. Emergency corridor logic
Averages the last 3 readings per road, estimates delay as `60 ÷ speed` minutes per 1 km, avoids roads currently HIGH (unless all are), breaks ties by fewer vehicles, and ranks all roads. **Limitation:** the data has no road-network connectivity, so this compares the four monitored roads. It is not a city-wide route and does not use Dijkstra.

## 10. Install and run (Windows)
```bat
cd SmartCityProject
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000. On first run the database and model are created automatically. (macOS/Linux: `source .venv/bin/activate`.)

Optional: `python train_model.py` retrains and prints the metrics. `python simulate.py` runs the standalone simulator; to use it, first disable the web app's simulator with `set SIMULATOR_ENABLED=0`.

## 11. Tests
```bat
python -m unittest discover -s tests -v
```
Covers: rules and status normalisation, CO₂ and air quality, emergency corridor, training and evaluation, model fallback and retraining, first start without a database or model, restart with existing files, empty-database dashboard, simulation and insertion, dashboard statistics, every API endpoint including invalid input, the single-simulator lock, and production-style startup through the real `app:app` WSGI object (plus gunicorn when it is installed).

## 12. Environment variables
See `.env.example`: `SMARTCITY_DATA_DIR`, `SMARTCITY_DB_PATH`, `SMARTCITY_MODEL_PATH`, `SIMULATOR_ENABLED`, `SIM_INTERVAL_SECONDS`, `SIM_SEED`, `RETENTION_MAX_ROWS`, `SQLITE_JOURNAL_MODE`, `LOG_LEVEL`, `HOST`, `PORT`, `FLASK_DEBUG` (off by default). No secrets are needed.

## 13. Deploy to Azure App Service
**Chosen approach:** one Linux App Service running the Flask app with gunicorn. Azure Machine Learning and Azure SQL are deliberately not used: the model is a tiny scikit-learn tree loaded in-process, and the data is simulated and pruned, so they would add cost without benefit.

Resources: resource group, App Service plan (B1 or higher recommended), Web App (Python 3.12).

```bash
az login
./azure/deploy.sh <unique-app-name>      # or run the commands inside it one by one
```
It sets `SMARTCITY_DATA_DIR=/home/data`, `SQLITE_JOURNAL_MODE=DELETE`, the startup command `startup.sh` (1 worker, 4 threads) and Always On.

Notes:
- **Storage:** `/home` persists across restarts but is a network share, so WAL is disabled (`DELETE` journal) and one worker is used. The database holds only simulated, disposable data. The model is retrained automatically at first start (about a second) whenever it is missing.
- **Free tier (F1):** has no Always On, so the app sleeps when idle and the simulator pauses.
- Scaling out to several instances would give each its own simulator and file. Moving to Azure SQL or Postgres plus a separate worker would be the next step.
- **Not verified:** no Azure subscription was available, so `azure/deploy.sh` and the Azure settings above were written from documentation but never executed.

## 14. Limitations
Simulated data only; model accuracy reflects rule learning; emission and air-quality values are illustrative; no road network, so no true routing; SQLite and an in-process simulator suit a demo, not a multi-instance production system; the dashboard has no authentication.

## 15. Future improvements (not implemented)
Real sensor or API ingestion; training on real labelled history or forecasting future congestion; a road graph with Dijkstra/A* routing; official AQI inputs; Azure SQL/Event Hubs for scale; authentication.
