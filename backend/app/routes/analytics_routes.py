from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta

from ..utils.auth_utils import check_household_permission
from ..models.models import Task, User, Household, Badge
from ..utils.badge_utils import calculate_streak, check_streak_badges, check_contribution_badges

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/households/<household_id>/analytics", methods=["GET"])
@jwt_required()
def get_analytics(household_id):
    user = User.query.filter_by(email=get_jwt_identity()).first()
    household = Household.query.get(household_id)

    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    # Calculate completion rates
    tasks = Task.query.filter_by(household_id=household_id).all()
    completed = sum(1 for t in tasks if t.completed)
    completion_rate = (completed / len(tasks)) * 100 if tasks else 0

    # Calculate overdue tasks
    now = datetime.utcnow()
    overdue = sum(
        1 for t in tasks if not t.completed and t.due_date and t.due_date < now
    )

    # Calculate average completion time
    completed_tasks = [t for t in tasks if t.completed and t.completed_at]
    avg_completion_time = 0
    if completed_tasks:
        completion_times = [
            (t.completed_at - t.created_at).total_seconds() / 3600
            for t in completed_tasks
        ]
        avg_completion_time = sum(completion_times) / len(completion_times)

    # User-specific analytics
    user_tasks = [t for t in tasks if t.assigned_to == user.id]
    user_completed = sum(1 for t in user_tasks if t.completed)

    # Calculate streak
    current_streak = calculate_streak(user.id)

    # Get badges earned (placeholder logic)
    badges = (
        Badge.query.join(user_badges).filter(user_badges.c.user_id == user.id).all()
    )

    # Household member analytics
    members = household.members
    active_members = len(set(t.assigned_to for t in tasks if t.assigned_to))

    # Find most active member
    member_completions = {}
    for t in tasks:
        if t.completed and t.assigned_to:
            member_completions[t.assigned_to] = (
                member_completions.get(t.assigned_to, 0) + 1
            )

    most_active_member = {"user_id": "", "email": "", "tasks_completed": 0}

    if member_completions:
        most_active_id = max(member_completions, key=member_completions.get)
        most_active_user = User.query.get(most_active_id)
        if most_active_user:
            most_active_member = {
                "user_id": most_active_user.id,
                "email": most_active_user.email,
                "tasks_completed": member_completions[most_active_id],
            }

    # Award badges (keep existing logic)
    check_contribution_badges(household_id)

    # Return comprehensive analytics data
    return (
        jsonify(
            {
                # Task analytics
                "task_analytics": {
                    "completion_rate": completion_rate,
                    "total_tasks": len(tasks),
                    "completed_tasks": completed,
                    "overdue_tasks": overdue,
                    "average_completion_time": avg_completion_time,  # in hours
                },
                # User analytics
                "user_analytics": {
                    "tasks_completed": user_completed,
                    "current_streak": current_streak,
                    "longest_streak": current_streak + 2,  # Placeholder
                    "badges_earned": len(badges),
                    "contribution_score": user_completed
                    * 10,  # Placeholder calculation
                    "rank_in_household": 1,  # Placeholder
                },
                # Household analytics
                "household_analytics": {
                    "total_members": len(members),
                    "active_members": active_members,
                    "total_tasks_created": len(tasks),
                    "total_tasks_completed": completed,
                    "average_completion_rate": completion_rate,
                    "most_active_member": most_active_member,
                },
                # Simple activity data - should be expanded in production
                "activity_over_time": [
                    {
                        "date": (datetime.utcnow() - timedelta(days=i)).isoformat(),
                        "value": int(i % 5),
                    }
                    for i in range(10)
                ],
                "activity_heatmap": [
                    {
                        "date": (datetime.utcnow() - timedelta(days=i)).isoformat(),
                        "count": int(i % 7),
                    }
                    for i in range(30)
                ],
            }
        ),
        200,
    )


@analytics_bp.route("/users/<user_id>/badges", methods=["GET"])
@jwt_required()
def get_user_badges(user_id):
    user = User.query.filter_by(email=get_jwt_identity()).first()
    target_user = User.query.get_or_404(user_id)

    if user.id != target_user.id and not check_household_permission(
        user, None, "admin"
    ):
        return jsonify({"error": "Unauthorized access"}), 403

    badges = target_user.badges
    return (
        jsonify(
            [
                {
                    "id": b.id,
                    "name": b.name,
                    "description": b.description,
                    "awarded_at": next(
                        (
                            ub.awarded_at
                            for ub in target_user.user_badges
                            if ub.badge_id == b.id
                        ),
                        None,
                    ),
                }
                for b in badges
            ]
        ),
        200,
    )
