from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.models import Notification, User, NotificationSettings
from ..extensions import db

notification_bp = Blueprint("notifications", __name__)


@notification_bp.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    """Get all notifications for the current user with pagination"""
    current_user_id = get_jwt_identity()

    # Pagination parameters
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    # Filter parameters
    is_read = request.args.get("is_read")
    household_id = request.args.get("household_id")

    query = Notification.query.filter_by(user_id=current_user_id)

    if is_read is not None:
        is_read_bool = is_read.lower() == "true"
        query = query.filter_by(is_read=is_read_bool)

    if household_id:
        query = query.filter_by(household_id=household_id)

    paginated_notifications = query.order_by(Notification.created_at.desc()).paginate(
        page=page, per_page=per_page
    )

    return jsonify(
        {
            "notifications": [
                {
                    "id": n.id,
                    "type": n.type,
                    "content": n.content,
                    "is_read": n.is_read,
                    "created_at": n.created_at.isoformat(),
                    "reference_type": n.reference_type,
                    "reference_id": n.reference_id,
                    "household_id": n.household_id,
                }
                for n in paginated_notifications.items
            ],
            "pagination": {
                "total": paginated_notifications.total,
                "pages": paginated_notifications.pages,
                "page": paginated_notifications.page,
                "per_page": paginated_notifications.per_page,
                "has_next": paginated_notifications.has_next,
                "has_prev": paginated_notifications.has_prev,
            },
        }
    )


@notification_bp.route("/notifications/<notification_id>/read", methods=["POST"])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    current_user_id = get_jwt_identity()

    notification = Notification.query.filter_by(
        id=notification_id, user_id=current_user_id
    ).first_or_404()

    notification.is_read = True
    db.session.commit()

    return jsonify({"success": True})


@notification_bp.route("/notifications/read-all", methods=["POST"])
@jwt_required()
def mark_all_notifications_read():
    """Mark all notifications as read for the current user"""
    current_user_id = get_jwt_identity()

    # Optional filter by household
    household_id = request.json.get("household_id")

    query = Notification.query.filter_by(user_id=current_user_id, is_read=False)

    if household_id:
        query = query.filter_by(household_id=household_id)

    notification_count = query.update({Notification.is_read: True})
    db.session.commit()
    socketio.emit("notification_count", {"count": notification_count})

    return jsonify({"success": True, "count": notification_count})


@notification_bp.route("/notifications/unread-count", methods=["GET"])
@jwt_required()
def get_unread_notification_count():
    """Get count of unread notifications for the current user"""
    current_user_id = get_jwt_identity()

    # Optional filter by household
    household_id = request.args.get("household_id")

    query = Notification.query.filter_by(user_id=current_user_id, is_read=False)

    if household_id:
        query = query.filter_by(household_id=household_id)

    count = query.count()

    return jsonify({"unread_count": count})


@notification_bp.route("/notifications/settings", methods=["GET"])
@jwt_required()
def get_notification_settings():
    """Get notification settings for the current user"""
    current_user_id = get_jwt_identity()

    settings = NotificationSettings.query.filter_by(user_id=current_user_id).first()
    if not settings:
        # Create default settings if they don't exist
        settings = NotificationSettings(user_id=current_user_id)
        db.session.add(settings)
        db.session.commit()

    return jsonify(
        {
            "email_notifications": settings.email_notifications,
            "push_notifications": settings.push_notifications,
            "in_app_notifications": settings.in_app_notifications,
            "notification_types": settings.notification_types,
            "quiet_hours": settings.quiet_hours,
        }
    )


@notification_bp.route("/notifications/settings", methods=["PATCH"])
@jwt_required()
def update_notification_settings():
    """Update notification settings for the current user"""
    current_user_id = get_jwt_identity()

    settings = NotificationSettings.query.filter_by(user_id=current_user_id).first()
    if not settings:
        settings = NotificationSettings(user_id=current_user_id)
        db.session.add(settings)

    data = request.json

    if "email_notifications" in data:
        settings.email_notifications = data["email_notifications"]
    if "push_notifications" in data:
        settings.push_notifications = data["push_notifications"]
    if "in_app_notifications" in data:
        settings.in_app_notifications = data["in_app_notifications"]
    if "notification_types" in data:
        # Update only provided notification types
        current_types = settings.notification_types
        current_types.update(data["notification_types"])
        settings.notification_types = current_types
    if "quiet_hours" in data:
        # Update only provided quiet hours settings
        current_quiet_hours = settings.quiet_hours
        current_quiet_hours.update(data["quiet_hours"])
        settings.quiet_hours = current_quiet_hours

    db.session.commit()

    return jsonify(
        {
            "email_notifications": settings.email_notifications,
            "push_notifications": settings.push_notifications,
            "in_app_notifications": settings.in_app_notifications,
            "notification_types": settings.notification_types,
            "quiet_hours": settings.quiet_hours,
        }
    )


@notification_bp.route("/notifications/<notification_id>", methods=["DELETE"])
@jwt_required()
def delete_notification(notification_id):
    """Delete a notification"""
    current_user_id = get_jwt_identity()
    notification = Notification.query.filter_by(
        id=notification_id, user_id=current_user_id
    ).first_or_404()

    db.session.delete(notification)
    db.session.commit()

    return jsonify({"success": True, "message": "Notification deleted successfully"})
