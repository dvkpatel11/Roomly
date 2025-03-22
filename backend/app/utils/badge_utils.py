from ..models.models import Badge, user_badges, Task, Message, Vote
from ..extensions import db
from datetime import datetime, timedelta


def check_badge_eligibility(user):
    """
    Check if user is eligible for any badges and award them

    Args:
        user: User model instance

    Returns:
        List of newly awarded Badge instances
    """
    newly_awarded = []

    # Get existing badges
    existing_badges = set(
        badge_id
        for (badge_id,) in db.session.query(user_badges.c.badge_id)
        .filter_by(user_id=user.id)
        .all()
    )

    # Check task streak badges
    streak_badges = check_streak_badges(user, existing_badges)
    newly_awarded.extend(streak_badges)

    # Check contribution badges
    contribution_badges = check_contribution_badges(user, existing_badges)
    newly_awarded.extend(contribution_badges)

    # Check social badges
    social_badges = check_social_badges(user, existing_badges)
    newly_awarded.extend(social_badges)

    return newly_awarded


def check_streak_badges(user, existing_badges):
    """Check and award badges based on task completion streaks"""
    newly_awarded = []

    # Calculate current streak
    streak = calculate_streak(user.id)

    # Define streak badge thresholds
    streak_thresholds = {
        "3_day_streak": 3,
        "7_day_streak": 7,
        "14_day_streak": 14,
        "30_day_streak": 30,
    }

    # Check each threshold
    for badge_type, threshold in streak_thresholds.items():
        if streak >= threshold:
            badge = Badge.query.filter_by(type=badge_type).first()

            if badge and badge.id not in existing_badges:
                # Award badge
                award_badge(user.id, badge.id)
                newly_awarded.append(badge)

    return newly_awarded


def check_contribution_badges(user, existing_badges):
    """Check and award badges based on contributions to household"""
    newly_awarded = []

    # Count completed tasks
    completed_tasks = Task.query.filter_by(assigned_to=user.id, completed=True).count()

    # Define task completion thresholds
    task_thresholds = {
        "5_tasks_completed": 5,
        "25_tasks_completed": 25,
        "100_tasks_completed": 100,
    }

    # Check each threshold
    for badge_type, threshold in task_thresholds.items():
        if completed_tasks >= threshold:
            badge = Badge.query.filter_by(type=badge_type).first()

            if badge and badge.id not in existing_badges:
                award_badge(user.id, badge.id)
                newly_awarded.append(badge)

    return newly_awarded


def check_social_badges(user, existing_badges):
    """Check and award badges based on social activity"""
    newly_awarded = []

    # Count messages
    message_count = Message.query.filter_by(user_id=user.id).count()

    # Count poll votes
    vote_count = Vote.query.filter_by(user_id=user.id).count()

    # Social activity badges
    social_badges = {
        "active_communicator": 10,  # 10+ messages
        "poll_participant": 5,  # 5+ votes
    }

    # Check message threshold
    if message_count >= social_badges["active_communicator"]:
        badge = Badge.query.filter_by(type="active_communicator").first()
        if badge and badge.id not in existing_badges:
            award_badge(user.id, badge.id)
            newly_awarded.append(badge)

    # Check vote threshold
    if vote_count >= social_badges["poll_participant"]:
        badge = Badge.query.filter_by(type="poll_participant").first()
        if badge and badge.id not in existing_badges:
            award_badge(user.id, badge.id)
            newly_awarded.append(badge)

    return newly_awarded


def calculate_streak(user_id):
    """Calculate the current streak of consecutive days with completed tasks"""
    from sqlalchemy import func

    # Get completed tasks ordered by completion date
    completed_tasks = (
        Task.query.filter_by(assigned_to=user_id, completed=True)
        .order_by(Task.completed_at.desc())
        .all()
    )

    if not completed_tasks:
        return 0

    # Start with most recent task
    current_date = completed_tasks[0].completed_at.date()
    streak = 1

    # Check for tasks completed on previous days
    for i in range(1, 31):  # Limit to 30 days to avoid excessive checking
        previous_date = current_date - timedelta(days=1)

        # Check if any task was completed on the previous date
        task_on_date = False
        for task in completed_tasks:
            if task.completed_at.date() == previous_date:
                task_on_date = True
                break

        if task_on_date:
            streak += 1
            current_date = previous_date
        else:
            # Streak broken
            break

    return streak


def award_badge(user_id, badge_id):
    """Award a badge to a user"""
    from ..models.models import Notification

    # Add badge association
    db.session.execute(
        user_badges.insert().values(
            user_id=user_id, badge_id=badge_id, awarded_at=datetime.utcnow()
        )
    )

    # Get badge info for notification
    badge = Badge.query.get(badge_id)

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

    return badge
