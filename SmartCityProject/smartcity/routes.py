"""HTTP routes: the dashboard page plus a small JSON API polled by the browser."""
import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, render_template, request

from . import analysis
from .traffic_rules import HIGH, STATUSES, classify, validate_reading

bp = Blueprint("main", __name__)
log = logging.getLogger(__name__)


def _ext():
    return current_app.extensions["smartcity"]


def _enrich(row):
    carbon = analysis.get_carbon_kg(row["cars"], row["speed"])
    return {**row, "carbon_kg": carbon, "air_quality": analysis.get_air_quality(carbon)}


def _age_seconds(iso):
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - t).total_seconds()))
    except (TypeError, ValueError):
        return None


@bp.get("/")
def dashboard():
    return render_template("index.html", interval=current_app.config["SIM_INTERVAL_SECONDS"])


@bp.get("/api/summary")
def summary():
    db = _ext()["db"]
    latest = [_enrich(r) for r in db.latest_per_road(1)]
    if not latest:
        return jsonify(has_data=False, roads=[], emergency=None)
    smoothed = {}
    for r in db.latest_per_road(3):          # average of the latest 3 readings per road
        smoothed.setdefault(r["road"], []).append(r)
    corridor_input = []
    for road, rows in smoothed.items():
        corridor_input.append({"road": road, "cars": sum(x["cars"] for x in rows) / len(rows),
                               "speed": sum(x["speed"] for x in rows) / len(rows),
                               "status": rows[0]["status"]})
    return jsonify(
        has_data=True,
        roads=latest,
        total_vehicles=sum(r["cars"] for r in latest),
        average_speed=round(sum(r["speed"] for r in latest) / len(latest), 1),
        congested_roads=sum(1 for r in latest if r["status"] == HIGH),
        monitored_roads=len(latest),
        total_carbon_kg=round(sum(r["carbon_kg"] for r in latest), 1),
        emergency=analysis.emergency_corridor(corridor_input),
        updated_at=max(r["recorded_at"] for r in latest),
        data_age_seconds=_age_seconds(max(r["recorded_at"] for r in latest)),
    )


@bp.get("/api/records")
def records():
    try:
        limit = int(request.args.get("limit", 15))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    if not 1 <= limit <= 200:
        return jsonify(error="limit must be between 1 and 200"), 400
    return jsonify(records=[_enrich(r) for r in _ext()["db"].recent(limit)])


@bp.get("/api/trends")
def trends():
    db = _ext()["db"]
    rows = list(reversed(db.recent(160)))      # oldest -> newest
    return jsonify(points=[{"id": r["id"], "road": r["road"], "cars": r["cars"], "speed": r["speed"],
                            "t": r["recorded_at"]} for r in rows],
                   status_counts=db.status_counts(200), statuses=list(STATUSES))


@bp.get("/api/predict")
def predict():
    try:
        cars, speed = validate_reading(request.args.get("cars"), request.args.get("speed"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    status, source = _ext()["classifier"].predict(cars, speed)
    carbon = analysis.get_carbon_kg(cars, speed)
    return jsonify(cars=cars, speed=speed, status=status, predicted_by=source,
                   rule_status=classify(cars, speed), carbon_kg=carbon,
                   air_quality=analysis.get_air_quality(carbon))


@bp.get("/api/model")
def model_info():
    c = _ext()["classifier"]
    return jsonify(active=c.source, error=c.error, metrics=c.metrics)


@bp.get("/api/health")
def health():
    ext = _ext()
    try:
        count, last = ext["db"].count(), ext["db"].recent(1)
        db_ok = True
    except Exception:
        log.exception("Health check: database error")
        count, last, db_ok = 0, [], False
    return jsonify(status="ok" if db_ok else "degraded", database_ok=db_ok, records=count,
                   simulator_running_here=ext["runner"].running, simulator_error=ext["runner"].error,
                   classifier=ext["classifier"].source,
                   last_record_age_seconds=_age_seconds(last[0]["recorded_at"]) if last else None,
                   data_source="simulated"), (200 if db_ok else 503)


@bp.app_errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found"), 404
    return render_template("error.html", code=404, message="That page does not exist."), 404


@bp.app_errorhandler(500)
@bp.app_errorhandler(Exception)
def server_error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        code, msg = exc.code, exc.description
    else:
        log.exception("Unhandled error")
        code, msg = 500, "Something went wrong on the server. Please try again."
    if request.path.startswith("/api/"):
        return jsonify(error=msg), code
    return render_template("error.html", code=code, message=msg), code
