from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.models import Badge, User, user_badges, Notification
from ..utils.auth_utils import check_household_permission
from ..utils.badge_utils import check_badge_eligibility
from ..extensions import db

badge_bp = Blueprint("badges", __name__)


@badge_bp.route("/badges", methods=["GET"])
@jwt_required()
def get_all_badges():
    """Get all available badge types"""
    badges = Badge.query.all()

    return (
        jsonify(
            {
                "badges": [
                    {
                        "id": badge.id,
                        "type": badge.type,
                        "name": badge.name,
                        "description": badge.description,
                    }
                    for badge in badges
                ]
            }
        ),
        200,
    )


@badge_bp.route("/users/me/badges", methods=["GET"])
@jwt_required()
def get_user_badges():
    """Get current user's earned badges"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Query association table to get award dates
    badge_awards = (
        db.session.query(Badge, user_badges.c.awarded_at)
        .join(user_badges, Badge.id == user_badges.c.badge_id)
        .filter(user_badges.c.user_id == user.id)
        .all()
    )

    return (
        jsonify(
            {
                "badges": [
                    {
                        "id": award.Badge.id,
                        "type": award.Badge.type,
                        "name": award.Badge.name,
                        "description": award.Badge.description,
                        "awarded_at": (
                            award.awarded_at.isoformat() if award.awarded_at else None
                        ),
                    }
                    for award in badge_awards
                ]
            }
        ),
        200,
    )


@badge_bp.route("/households/<household_id>/badges", methods=["GET"])
@jwt_required()
def get_household_badges(household_id):
    """Get all badges earned by household members"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not check_household_permission(user, household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    # Get all household members
    from ..models.models import Household, user_households

    household = Household.query.get_or_404(household_id)
    members_query = (
        db.session.query(User)
        .join(user_households, User.id == user_households.c.user_id)
        .filter(user_households.c.household_id == household_id)
        .all()
    )

    # Build member badge data
    member_badges = {}
    for member in members_query:
        badge_awards = (
            db.session.query(Badge, user_badges.c.awarded_at)
            .join(user_badges, Badge.id == user_badges.c.badge_id)
            .filter(user_badges.c.user_id == member.id)
            .all()
        )

        member_badges[member.id] = {
            "email": member.email,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "full_name": member.full_name,
            "badges": [
                {
                    "id": award.Badge.id,
                    "type": award.Badge.type,
                    "name": award.Badge.name,
                    "awarded_at": (
                        award.awarded_at.isoformat() if award.awarded_at else None
                    ),
                }
                for award in badge_awards
            ],
        }

    return jsonify({"members": member_badges}), 200


@badge_bp.route("/admin/badges", methods=["POST"])
@jwt_required()
def create_badge():
    """Create a new badge type (admin only)"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if user.role != "admin":
        return jsonify({"error": "Admin privileges required"}), 403

    data = request.get_json()

    try:
        new_badge = Badge(
            type=data["type"],
            name=data["name"],
            description=data.get("description", ""),
        )
        db.session.add(new_badge)
        db.session.commit()

        return jsonify({"message": "Badge created", "badge_id": new_badge.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@badge_bp.route("/admin/award-badge", methods=["POST"])
@jwt_required()
def award_badge():
    """Manually award a badge to a user (admin only)"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if user.role != "admin":
        return jsonify({"error": "Admin privileges required"}), 403

    data = request.get_json()
    badge_id = data.get("badge_id")
    user_id = data.get("user_id")

    badge = Badge.query.get_or_404(badge_id)
    target_user = User.query.get_or_404(user_id)

    # Check if already awarded
    existing_award = (
        db.session.query(user_badges)
        .filter_by(user_id=user_id, badge_id=badge_id)
        .first()
    )

    if existing_award:
        return jsonify({"error": "Badge already awarded to this user"}), 409

    try:
        # Award badge
        db.session.execute(
            user_badges.insert().values(user_id=user_id, badge_id=badge_id)
        )

        # Create notification
        notification = Notification(
            type="badge_awarded",
            content=f"You've earned the {badge.name} badge!",
            user_id=user_id,
            reference_type="badge",
            reference_id=badge_id,
        )
        db.session.add(notification)

        db.session.commit()

        return (
            jsonify(
                {
                    "message": "Badge awarded",
                    "badge_name": badge.name,
                    "user_email": target_user.email,
                }
            ),
            200,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@badge_bp.route("/users/check-badges", methods=["POST"])
@jwt_required()
def check_badges():
    """Check and award badges based on user activity"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    try:
        # This would call helper functions to check various achievements
        awarded_badges = check_badge_eligibility(user)

        return (
            jsonify(
                {
                    "message": f"Awarded {len(awarded_badges)} new badges",
                    "badges": [
                        {
                            "id": badge.id,
                            "name": badge.name,
                            "description": badge.description,
                        }
                        for badge in awarded_badges
                    ],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@badge_bp.route("/users/me/badge-progress", methods=["GET"])
@jwt_required()
def get_badge_progress():
    """Get progress toward badges that haven't been earned yet"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Get badges the user doesn't have yet
    user_badge_ids = (
        db.session.query(user_badges.c.badge_id).filter_by(user_id=user.id).all()
    )
    user_badge_ids = [b[0] for b in user_badge_ids]

    unearned_badges = Badge.query.filter(Badge.id.notin_(user_badge_ids)).all()

    # Calculate progress for each badge
    progress_data = []
    for badge in unearned_badges:
        # The progress calculation would depend on badge type
        # Here's a placeholder implementation
        progress = calculate_badge_progress(user, badge)

        if progress:
            progress_data.append(
                {
                    "badge_id": badge.id,
                    "badge_name": badge.name,
                    "badge_type": badge.type,
                    "description": badge.description,
                    "progress": progress["current"],
                    "target": progress["target"],
                    "percentage": (
                        round((progress["current"] / progress["target"]) * 100, 2)
                        if progress["target"] > 0
                        else 0
                    ),
                }
            )

    return jsonify({"badge_progress": progress_data}), 200


def calculate_badge_progress(user, badge):
    """Calculate progress toward earning a specific badge"""
    # Different badge types require different progress calculations
    from ..models.models import Task

    if badge.type == "5_day_streak":
        # Get current streak
        from ..utils.task_utils import calculate_streak

        current_streak = calculate_streak(user.id)
        return {"current": current_streak, "target": 5}

    elif badge.type == "10_day_streak":
        from ..utils.task_utils import calculate_streak

        current_streak = calculate_streak(user.id)
        return {"current": current_streak, "target": 10}

    elif badge.type == "task_master":
        # Count completed tasks
        completed_tasks = Task.query.filter_by(
            assigned_to=user.id, completed=True
        ).count()
        return {
            "current": completed_tasks,
            "target": 50,
        }  # Example: 50 tasks to earn badge

    elif badge.type == "top_contributor":
        # This might need household context to determine if user has most tasks
        # For now, just return null progress
        return None

    # Default case
    return None


@badge_bp.route("/households/<household_id>/leaderboard", methods=["GET"])
@jwt_required()
def get_household_leaderboard(household_id):
    """Get leaderboard data for household members"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not check_household_permission(user, household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    # Get leaderboard data
    from ..models.models import Task, Household

    # Get all household members
    members_query = (
        db.session.query(User)
        .join(user_households, User.id == user_households.c.user_id)
        .filter(user_households.c.household_id == household_id)
        .all()
    )

    leaderboard_data = []
    for member in members_query:
        # Count tasks completed in the last 30 days
        from datetime import datetime, timedelta

        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        completed_tasks = Task.query.filter(
            Task.assigned_to == member.id,
            Task.household_id == household_id,
            Task.completed == True,
            Task.completed_at >= thirty_days_ago,
        ).count()

        # Count badges earned
        badge_count = db.session.query(user_badges).filter_by(user_id=member.id).count()

        # Calculate streak
        from ..utils.task_utils import calculate_streak

        current_streak = calculate_streak(member.id)

        leaderboard_data.append(
            {
                "user_id": member.id,
                "email": member.email,
                "name": getattr(member, "name", member.email.split("@")[0]),
                "tasks_completed": completed_tasks,
                "badge_count": badge_count,
                "current_streak": current_streak,
                "rank": 0,  # Will be calculated after sorting
            }
        )

    # Sort by tasks completed and assign ranks
    leaderboard_data.sort(key=lambda x: x["tasks_completed"], reverse=True)
    for i, entry in enumerate(leaderboard_data):
        entry["rank"] = i + 1

    return (
        jsonify(
            {
                "leaderboard": leaderboard_data,
                "update_time": datetime.utcnow().isoformat(),
            }
        ),
        200,
    )
