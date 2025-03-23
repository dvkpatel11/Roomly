from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.models import Notification, Task, RecurringTaskRule, User
from ..utils.auth_utils import check_household_permission
from ..utils.task_utils import (
    auto_assign_task,
    generate_recurring_tasks,
    calculate_streak,
)
from ..extensions import db

task_bp = Blueprint("tasks", __name__)


@task_bp.route("/households/<household_id>/tasks", methods=["POST"])
@jwt_required()
def create_task(household_id):
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    data = request.get_json()

    # Authorization check
    if not check_household_permission(current_user, household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    try:
        # Auto-assign task
        assigned_to = auto_assign_task(household_id, data.get("preferred_assignee"))

        new_task = Task(
            title=data["title"],
            frequency=data.get("frequency", "one_time"),
            household_id=household_id,
            created_by=current_user.id,
            assigned_to=assigned_to,
            due_date=(
                datetime.fromisoformat(data["due_date"])
                if data.get("due_date")
                else None
            ),
        )

        db.session.add(new_task)
        db.session.flush()  # Get task ID before commit

        # Handle recurring tasks
        if data.get("is_recurring"):
            recurrence_rule = RecurringTaskRule(
                task_id=new_task.id,
                interval_days=data["interval_days"],
                anchor_date=new_task.due_date,
                end_date=(
                    datetime.fromisoformat(data["end_date"])
                    if data.get("end_date")
                    else None
                ),
            )
            db.session.add(recurrence_rule)

            # Generate future instances
            generate_recurring_tasks(new_task.id, recurrence_rule)

        db.session.commit()

        return (
            jsonify(
                {
                    "message": "Task created",
                    "task_id": new_task.id,
                    "assigned_to": assigned_to,
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@task_bp.route("/households/<household_id>/tasks", methods=["GET"])
@jwt_required()
def get_household_tasks(household_id):
    current_user = User.query.get(get_jwt_identity())
    if not check_household_permission(current_user, household_id, "member"):
        return jsonify({"error": "Not a household member"}), 403

    # Filter parameters
    status = request.args.get("status", "all")
    assigned_to = request.args.get("assignedTo")
    frequency = request.args.get("frequency", "all")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    include_completed = request.args.get("include_completed", "true").lower() == "true"

    query = Task.query.filter_by(household_id=household_id)

    # Apply filters
    if status != "all":
        if status == "completed":
            query = query.filter(Task.completed == True)
        elif status == "pending":
            query = query.filter(Task.completed == False)
            # No overdue check as that's determined at runtime
    elif not include_completed:
        query = query.filter(Task.completed == False)

    if assigned_to:
        query = query.filter(Task.assigned_to == assigned_to)

    if frequency != "all":
        # Map frontend frequency to backend
        frequency_mapping = {
            "once": "one_time",
            "daily": "daily",
            "weekly": "weekly",
            "monthly": "monthly",
        }
        backend_frequency = frequency_mapping.get(frequency)
        if backend_frequency:
            query = query.filter(Task.frequency == backend_frequency)

    tasks = query.paginate(page=page, per_page=per_page)

    return (
        jsonify(
            {
                "tasks": [task_to_dict(t) for t in tasks.items],
                "total": tasks.total,
                "page": tasks.page,
                "per_page": tasks.per_page,
            }
        ),
        200,
    )


@task_bp.route("/tasks/<task_id>/complete", methods=["PATCH"])
@jwt_required()
def complete_task(task_id):
    current_user = User.query.get(get_jwt_identity())
    task = Task.query.get_or_404(task_id)

    if task.completed:
        return jsonify({"error": "Task already completed"}), 400

    if not check_household_permission(current_user, task.household_id, "member"):
        return jsonify({"error": "Not authorized"}), 403

    if task.assigned_to != current_user.id:
        return jsonify({"error": "Task not assigned to you"}), 403

    try:
        task.completed = True
        task.completed_at = datetime.utcnow()

        # Check for recurring task regeneration
        if task.recurring_rule:
            generate_recurring_tasks(task.id, task.recurring_rule)

        db.session.commit()

        return (
            jsonify(
                {
                    "message": "Task marked complete",
                    "streak": calculate_streak(current_user.id),
                }
            ),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@task_bp.route("/tasks/<task_id>/swap", methods=["POST"])
@jwt_required()
def request_swap(task_id):
    current_user = User.query.get(get_jwt_identity())
    task = Task.query.get_or_404(task_id)
    data = request.get_json()

    if not check_household_permission(current_user, task.household_id, "member"):
        return jsonify({"error": "Not authorized"}), 403

    new_assignee = User.query.get(data["new_assignee_id"])

    # Validate new assignee is household member
    if not check_household_permission(new_assignee, task.household_id, "member"):
        return jsonify({"error": "New assignee not in household"}), 400

    try:
        # Verify swap request (could add approval workflow here)
        task.assigned_to = new_assignee.id
        notification = Notification(
            type="task_assignment",
            content=f"Task '{task.title}' has been assigned to you",
            user_id=new_assignee.id,
            household_id=task.household_id,
            reference_type="task",
            reference_id=task.id,
        )
        db.session.add(notification)
        db.session.commit()

        return (
            jsonify({"message": "Task swapped", "new_assignee": new_assignee.email}),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@task_bp.route("/users/<user_id>/tasks", methods=["GET"])
@jwt_required()
def get_user_tasks(user_id):
    current_user = User.query.get(get_jwt_identity())

    if current_user.id != user_id and not check_household_permission(
        current_user, None, "admin"
    ):
        return jsonify({"error": "Unauthorized access"}), 403

    tasks = Task.query.filter_by(assigned_to=user_id).all()
    return jsonify([task_to_dict(t) for t in tasks]), 200


@task_bp.route("/tasks/<task_id>", methods=["DELETE"])
@jwt_required()
def delete_task(task_id):
    current_user = User.query.get(get_jwt_identity())
    task = Task.query.get_or_404(task_id)

    # Authorization: Task creator or household admin
    if task.created_by != current_user.id and not check_household_permission(
        current_user, task.household_id, "admin"
    ):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Delete recurring rules first
        if task.recurring_rule:
            db.session.delete(task.recurring_rule)

        db.session.delete(task)
        db.session.commit()
        return jsonify({"message": "Task deleted"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def task_to_dict(task):
    # Map backend frequency to frontend frequency
    frequency_mapping = {
        "one_time": "once",
        "daily": "daily",
        "weekly": "weekly",
        "monthly": "monthly",
    }

    # Determine status based on completed and due date
    status = "completed" if task.completed else "pending"
    if not task.completed and task.due_date and task.due_date < datetime.utcnow():
        status = "overdue"

    # Find the assigned user's name if available
    assigned_to_name = None
    if task.assigned_to:
        assigned_user = User.query.get(task.assigned_to)
        if assigned_user:
            assigned_to_name = (
                assigned_user.name
                if hasattr(assigned_user, "name")
                else assigned_user.email
            )

    return {
        "id": task.id,
        "title": task.title,
        "description": getattr(task, "description", ""),
        "status": status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": (
            task.created_at.isoformat()
            if hasattr(task, "created_at")
            else datetime.utcnow().isoformat()
        ),
        "created_by": task.created_by,
        "assigned_to": task.assigned_to,
        "assigned_to_name": assigned_to_name,
        "household_id": task.household_id,
        "frequency": frequency_mapping.get(task.frequency, "once"),
    }


@task_bp.route("/tasks/<task_id>", methods=["PATCH"])
@jwt_required()
def update_task(task_id):
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    task = Task.query.get_or_404(task_id)
    data = request.get_json()

    # Authorization: Task creator or household admin
    if task.created_by != current_user.id and not check_household_permission(
        current_user, task.household_id, "admin"
    ):
        return jsonify({"error": "Not authorized to update this task"}), 403

    try:
        # Update basic task properties
        if "title" in data:
            task.title = data["title"]

        if "description" in data:
            task.description = data.get("description", "")

        if "due_date" in data:
            task.due_date = (
                datetime.fromisoformat(data["due_date"]) if data["due_date"] else None
            )

        if "frequency" in data:
            # Map frontend frequency to backend
            frequency_mapping = {
                "once": "one_time",
                "daily": "daily",
                "weekly": "weekly",
                "monthly": "monthly",
            }
            task.frequency = frequency_mapping.get(data["frequency"], "one_time")

        # Handle recurring task rules if needed
        if "is_recurring" in data:
            if data["is_recurring"]:
                # Create or update recurring rule
                if task.recurring_rule:
                    # Update existing rule
                    if "interval_days" in data:
                        task.recurring_rule.interval_days = data["interval_days"]
                    if "end_date" in data:
                        task.recurring_rule.end_date = (
                            datetime.fromisoformat(data["end_date"])
                            if data["end_date"]
                            else None
                        )
                else:
                    # Create new rule
                    recurrence_rule = RecurringTaskRule(
                        task_id=task.id,
                        interval_days=data.get("interval_days", 7),  # Default weekly
                        anchor_date=task.due_date,
                        end_date=(
                            datetime.fromisoformat(data["end_date"])
                            if data.get("end_date")
                            else None
                        ),
                    )
                    db.session.add(recurrence_rule)
            elif task.recurring_rule:
                # Remove recurring rule if task is no longer recurring
                db.session.delete(task.recurring_rule)

        # Handle assignee changes
        if "assigned_to" in data and data["assigned_to"] != task.assigned_to:
            new_assignee_id = data["assigned_to"]

            # Verify new assignee is in household
            if new_assignee_id:
                new_assignee = User.query.get(new_assignee_id)
                if not new_assignee or not check_household_permission(
                    new_assignee, task.household_id, "member"
                ):
                    return jsonify({"error": "Invalid assignee"}), 400

                # Create notification for new assignee
                notification = Notification(
                    type="task_assignment",
                    content=f"Task '{task.title}' has been assigned to you",
                    user_id=new_assignee_id,
                    household_id=task.household_id,
                    reference_type="task",
                    reference_id=task.id,
                )
                db.session.add(notification)

            task.assigned_to = new_assignee_id

        db.session.commit()
        return (
            jsonify(
                {"message": "Task updated successfully", "task": task_to_dict(task)}
            ),
            200,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
