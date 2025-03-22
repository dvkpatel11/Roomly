from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime

from ..utils.auth_utils import check_household_permission
from ..models.models import Event, User, Household
from ..extensions import db

calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.route("/households/<household_id>/events", methods=["POST"])
@jwt_required()
def create_event(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    household = Household.query.get(household_id)

    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    data = request.get_json()

    # Handle recurring events
    if data.get("recurrence_rule"):
        try:
            base_event = create_recurring_events(data, household, user)
            return (
                jsonify(
                    {
                        "message": "Recurring events created",
                        "base_event_id": base_event.id,
                    }
                ),
                201,
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # Single event creation
    new_event = Event(
        title=data["title"],
        start_time=datetime.fromisoformat(data["start_time"]),
        end_time=(
            datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
        ),
        recurrence_rule=data.get("recurrence_rule"),
        privacy=data.get("privacy", "public"),
        household_id=household.id,
        user_id=user.id,
    )

    db.session.add(new_event)
    db.session.commit()

    notify_members(household, user, new_event)

    return jsonify({"message": "Event created", "event_id": new_event.id}), 201


@calendar_bp.route("/households/<household_id>/events", methods=["GET"])
@jwt_required()
def get_household_events(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    household = Household.query.get(household_id)

    # Get date range parameters
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = Event.query.filter_by(household_id=household_id)

    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    if not check_household_permission(user, household_id, "admin"):
        query = query.filter((Event.privacy == "public") | (Event.user_id == user.id))

    # Apply date range filter if provided
    if start_date:
        try:
            start_date = datetime.fromisoformat(start_date)
            query = query.filter(Event.end_time >= start_date)
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Invalid start_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"
                    }
                ),
                400,
            )

    if end_date:
        try:
            end_date = datetime.fromisoformat(end_date)
            query = query.filter(Event.start_time <= end_date)
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Invalid end_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"
                    }
                ),
                400,
            )

    events = query.order_by(Event.start_time.asc()).all()

    return (
        jsonify(
            [
                {
                    "id": e.id,
                    "title": e.title,
                    "start_time": e.start_time.isoformat(),
                    "end_time": e.end_time.isoformat() if e.end_time else None,
                    "recurrence_rule": e.recurrence_rule,
                    "privacy": e.privacy,
                    "created_by": e.user.email,
                    "is_recurring": bool(e.recurrence_rule),
                }
                for e in events
            ]
        ),
        200,
    )


@calendar_bp.route("/events/<event_id>", methods=["PATCH"])
@jwt_required()
def update_event(event_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    event = Event.query.get_or_404(event_id)

    # Check permissions (creator or admin)
    if event.user_id != user.id and not check_household_permission(
        user, event.household_id, "admin"
    ):
        return jsonify({"error": "Not authorized"}), 403

    data = request.get_json()

    # Update fields
    if "title" in data:
        event.title = data["title"]
    if "start_time" in data:
        event.start_time = datetime.fromisoformat(data["start_time"])
    if "end_time" in data:
        event.end_time = (
            datetime.fromisoformat(data["end_time"]) if data["end_time"] else None
        )
    if "privacy" in data:
        event.privacy = data["privacy"]

    db.session.commit()
    return jsonify({"message": "Event updated"}), 200


@calendar_bp.route("/events/<event_id>", methods=["DELETE"])
@jwt_required()
def delete_event(event_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    event = Event.query.get_or_404(event_id)

    # Check permissions (creator or admin)
    if event.user_id != user.id and not check_household_permission(
        user, event.household_id, "admin"
    ):
        return jsonify({"error": "Not authorized"}), 403

    db.session.delete(event)
    db.session.commit()
    return jsonify({"message": "Event deleted"}), 200


@calendar_bp.route("/users/me/events", methods=["GET"])
@jwt_required()
def get_user_events():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Get user's events across all households
    events = Event.query.filter_by(user_id=user.id).all()

    return (
        jsonify(
            [
                {
                    "id": e.id,
                    "title": e.title,
                    "start_time": e.start_time.isoformat(),
                    "end_time": e.end_time.isoformat() if e.end_time else None,
                    "household_id": e.household_id,
                    "privacy": e.privacy,
                }
                for e in events
            ]
        ),
        200,
    )


def create_recurring_events(data, household, user):
    """Create a series of recurring events based on RRULE"""
    from dateutil.rrule import rrulestr
    from dateutil.relativedelta import relativedelta

    base_event = Event(
        title=data["title"],
        start_time=datetime.fromisoformat(data["start_time"]),
        end_time=(
            datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
        ),
        recurrence_rule=data["recurrence_rule"],
        privacy=data.get("privacy", "public"),
        household_id=household.id,
        user_id=user.id,
    )

    db.session.add(base_event)
    db.session.flush()  # Get ID without committing

    # Generate occurrences (limit to reasonable number)
    try:
        rrule = rrulestr(data["recurrence_rule"], dtstart=base_event.start_time)
        occurrences = list(rrule.replace(count=10))  # Limit to 10 occurrences initially

        # Skip the first occurrence as it's covered by the base event
        for occurrence_date in occurrences[1:]:
            duration = relativedelta()
            if base_event.end_time:
                duration = relativedelta(base_event.end_time, base_event.start_time)

            occurrence_event = Event(
                title=data["title"],
                start_time=occurrence_date,
                end_time=occurrence_date + duration if base_event.end_time else None,
                privacy=data.get("privacy", "public"),
                household_id=household.id,
                user_id=user.id,
                parent_event_id=base_event.id,  # Link to parent
            )
            db.session.add(occurrence_event)

    except Exception as e:
        db.session.rollback()
        raise Exception(f"Invalid recurrence rule: {str(e)}")

    db.session.commit()
    return base_event


def notify_members(household, creator, event):
    """Notify household members about a new event"""
    from ..models.models import Notification

    for member in household.members:
        if member.id != creator.id:  # Don't notify creator
            notification = Notification(
                type="new_event",
                content=f"New event: {event.title} on {event.start_time.strftime('%Y-%m-%d %H:%M')}",
                user_id=member.id,
                household_id=household.id,
                reference_type="event",
                reference_id=event.id,
            )
            db.session.add(notification)

    db.session.commit()
