from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from ..models.models import Poll, Vote, User, Household, Notification
from ..utils.auth_utils import check_household_permission
from ..extensions import db, socketio

poll_bp = Blueprint("polls", __name__)


@poll_bp.route("/households/<household_id>/polls", methods=["POST"])
@jwt_required()
def create_poll(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not check_household_permission(user, household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    data = request.get_json()
    if not data or not data.get("question") or not data.get("options"):
        return jsonify({"error": "Question and options are required"}), 400

    try:
        expires_at = (
            datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None
        )

        new_poll = Poll(
            question=data["question"],
            options={option: 0 for option in data["options"]},
            expires_at=expires_at,
            household_id=household_id,
        )
        db.session.add(new_poll)
        db.session.commit()

        # Notify household members
        for member in Household.query.get(household_id).members:
            if member.id != user.id:  # Don't notify creator
                notification = Notification(
                    type="new_poll",
                    content=f"New poll: {data['question']}",
                    user_id=member.id,
                    household_id=household_id,
                    reference_type="poll",
                    reference_id=new_poll.id,
                )
                db.session.add(notification)
        db.session.commit()

        # Emit WebSocket event
        socketio.emit(
            "new_poll",
            {
                "id": new_poll.id,
                "question": new_poll.question,
                "options": new_poll.options,
                "expires_at": (
                    new_poll.expires_at.isoformat() if new_poll.expires_at else None
                ),
                "creator": user.id,
            },
            room=f"household_{household_id}",
        )

        return jsonify({"message": "Poll created", "poll_id": new_poll.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@poll_bp.route("/households/<household_id>/polls", methods=["GET"])
@jwt_required()
def get_polls(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not check_household_permission(user, household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    # Filter parameters
    status = request.args.get("status", "active")  # active, expired, all
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    query = Poll.query.filter_by(household_id=household_id)

    if status == "active":
        query = query.filter(
            (Poll.expires_at > datetime.utcnow()) | (Poll.expires_at.is_(None))
        )
    elif status == "expired":
        query = query.filter(Poll.expires_at <= datetime.utcnow())

    polls = query.order_by(Poll.created_at.desc()).paginate(
        page=page, per_page=per_page
    )

    # Get user's votes
    user_votes = {
        vote.poll_id: vote.selected_option
        for vote in Vote.query.filter_by(user_id=user.id).all()
    }

    return (
        jsonify(
            {
                "polls": [
                    {
                        "id": poll.id,
                        "question": poll.question,
                        "options": poll.options,
                        "expires_at": (
                            poll.expires_at.isoformat() if poll.expires_at else None
                        ),
                        "created_at": poll.created_at.isoformat(),
                        "user_vote": user_votes.get(poll.id),
                    }
                    for poll in polls.items
                ],
                "total": polls.total,
                "page": polls.page,
                "per_page": polls.per_page,
            }
        ),
        200,
    )


@poll_bp.route("/polls/<poll_id>/vote", methods=["POST"])
@jwt_required()
def cast_vote(poll_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    poll = Poll.query.get_or_404(poll_id)

    # Check household membership
    if not check_household_permission(user, poll.household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    # Check if poll is expired
    if poll.expires_at and poll.expires_at < datetime.utcnow():
        return jsonify({"error": "Poll has expired"}), 400

    data = request.get_json()
    selected_option = data.get("option")

    if not selected_option or selected_option not in poll.options:
        return jsonify({"error": "Invalid option"}), 400

    # Check for existing vote
    existing_vote = Vote.query.filter_by(poll_id=poll_id, user_id=user.id).first()

    try:
        if existing_vote:
            # Remove count from previous option
            if poll.options.get(existing_vote.selected_option):
                poll.options[existing_vote.selected_option] -= 1

            # Update vote
            existing_vote.selected_option = selected_option
        else:
            # Create new vote
            new_vote = Vote(
                poll_id=poll_id, user_id=user.id, selected_option=selected_option
            )
            db.session.add(new_vote)

        # Increment count for selected option
        poll.options[selected_option] += 1

        db.session.commit()

        # Emit WebSocket event with updated results
        socketio.emit(
            "poll_update",
            {"id": poll.id, "options": poll.options, "voter": user.id},
            room=f"household_{poll.household_id}",
        )

        return (
            jsonify(
                {
                    "message": "Vote recorded",
                    "poll_id": poll.id,
                    "option": selected_option,
                }
            ),
            200,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@poll_bp.route("/polls/<poll_id>", methods=["GET"])
@jwt_required()
def get_poll(poll_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    poll = Poll.query.get_or_404(poll_id)

    # Check household membership
    if not check_household_permission(user, poll.household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    # Get user's vote if any
    user_vote = Vote.query.filter_by(poll_id=poll_id, user_id=user.id).first()

    # Get all votes for this poll
    all_votes = Vote.query.filter_by(poll_id=poll_id).all()
    voters = {vote.user_id: User.query.get(vote.user_id).email for vote in all_votes}

    return (
        jsonify(
            {
                "id": poll.id,
                "question": poll.question,
                "options": poll.options,
                "expires_at": poll.expires_at.isoformat() if poll.expires_at else None,
                "created_at": poll.created_at.isoformat(),
                "household_id": poll.household_id,
                "user_vote": user_vote.selected_option if user_vote else None,
                "total_votes": len(all_votes),
                "voters": voters,
                "is_expired": poll.expires_at and poll.expires_at < datetime.utcnow(),
            }
        ),
        200,
    )


@poll_bp.route("/polls/<poll_id>", methods=["DELETE"])
@jwt_required()
def delete_poll(poll_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    poll = Poll.query.get_or_404(poll_id)

    # Only admin or poll creator can delete
    if poll.created_by != user.id and not check_household_permission(
        user, poll.household_id, "admin"
    ):
        return jsonify({"error": "Not authorized"}), 403

    try:
        # Delete all votes first
        Vote.query.filter_by(poll_id=poll_id).delete()

        # Delete the poll
        db.session.delete(poll)
        db.session.commit()

        # Notify via WebSocket
        socketio.emit(
            "poll_deleted", {"poll_id": poll_id}, room=f"household_{poll.household_id}"
        )

        return jsonify({"message": "Poll deleted"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
