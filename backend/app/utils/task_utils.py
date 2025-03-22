from datetime import datetime, timedelta
from ..models.models import Task, User, user_households


def auto_assign_task(household_id, preferred_user_id=None):
    """Auto-assign task using preference-aware round-robin"""
    # Get eligible users
    users = (
        User.query.join(user_households)
        .filter(
            user_households.c.household_id == household_id,
            user_households.c.role.in_(["member", "admin"]),
        )
        .all()
    )

    if not users:
        return None

    # Try preferred user first
    if preferred_user_id:
        preferred = next((u for u in users if u.id == preferred_user_id), None)
        if preferred:
            return preferred.id

    # Get last assigned user
    last_task = (
        Task.query.filter_by(household_id=household_id)
        .order_by(Task.created_at.desc())
        .first()
    )

    # Round-robin assignment
    last_index = (
        users.index(next(u for u in users if u.id == last_task.assigned_to))
        if last_task
        else -1
    )
    next_index = (last_index + 1) % len(users)

    return users[next_index].id


def generate_recurring_tasks(parent_task_id, rule):
    """Generate future instances of recurring tasks"""
    parent = Task.query.get(parent_task_id)
    if not parent or not rule:
        return

    current_date = parent.due_date
    existing = (
        Task.query.filter_by(created_by=parent.created_by)
        .filter(Task.due_date > current_date)
        .count()
    )

    # Generate up to 6 months ahead
    while current_date < (datetime.utcnow() + timedelta(days=180)) and (
        rule.end_date is None or current_date < rule.end_date
    ):

        if existing == 0:
            from extensions import db

            new_task = Task(
                title=parent.title,
                frequency=parent.frequency,
                household_id=parent.household_id,
                created_by=parent.created_by,
                assigned_to=auto_assign_task(parent.household_id),
                due_date=current_date + timedelta(days=rule.interval_days),
            )
            db.session.add(new_task)

        current_date += timedelta(days=rule.interval_days)
        existing -= 1


def calculate_streak(user_id):
    """Calculate consecutive days of task completion"""
    completed_tasks = (
        Task.query.filter_by(assigned_to=user_id, completed=True)
        .order_by(Task.completed_at.desc())
        .all()
    )

    streak = 0
    current_date = datetime.utcnow().date()

    for task in completed_tasks:
        task_date = task.completed_at.date()
        if task_date == current_date - timedelta(days=streak):
            streak += 1
        else:
            break

    return streak
