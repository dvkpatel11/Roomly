from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_socketio import emit, join_room, leave_room
from datetime import datetime
from ..models.models import Message, Poll, Vote, User, Household, user_households
from ..extensions import db, socketio
from ..utils.auth_utils import check_household_permission
from flask_jwt_extended import decode_token

chat_bp = Blueprint("chat", __name__)

online_users = {}


# WebSocket Event Handlers
@socketio.on("connect")
def handle_connect():
    pass


@socketio.on("join")
def handle_join(data):
    # Authenticate using token passed in data
    try:
        token = data.get("token")
        # Verify token and get user_id
        user_id = verify_jwt_token(token)  # Implement this function
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        room = f"household_{data['household_id']}"
        join_room(room)
        emit("joined", {"message": f"Joined {room}"})
    except Exception as e:
        emit("error", {"message": str(e)})


@socketio.on("disconnect")
def handle_disconnect():
    # Find user in online_users and mark as disconnected
    for user_id, data in online_users.items():
        if data.get("sid") == request.sid:
            online_users[user_id]["connected"] = False

            # Notify household members
            for household_id in data.get("households", []):
                emit(
                    "user_offline",
                    {"user_id": user_id},
                    room=f"household_{household_id}",
                    broadcast=True,
                )
            break


@socketio.on("message")
def handle_message(data):
    try:
        token = data.get("token")
        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        household_id = data.get("household_id")
        household = Household.query.get(household_id)

        if not household:
            emit("error", {"message": "Household not found"})
            return

        # Check membership
        is_member = (
            db.session.query(user_households)
            .filter_by(user_id=user_id, household_id=household_id)
            .first()
        )

        if not is_member:
            emit("error", {"message": "Not a household member"})
            return

        new_message = Message(
            content=data["content"],
            household_id=household_id,
            user_id=user_id,
            is_announcement=data.get("is_announcement", False),
        )
        db.session.add(new_message)
        db.session.commit()

        # Log the message creation for debugging
        print(f"New message created: ID={new_message.id}, Content={new_message.content[:30]}..., Sender={user.email}")

        # Broadcast to all in the room
        room = f"household_{household_id}"
        emit(
            "new_message",
            {
                "id": new_message.id,
                "content": new_message.content,
                "sender_id": user_id,
                "sender_email": user.email,
                "is_announcement": new_message.is_announcement,
                "created_at": new_message.created_at.isoformat(),
            },
            room=room,
        )

        # Return success to the sender with the message ID
        return {
            "status": "success",
            "message_id": new_message.id,
            "sender_id": user_id,
            "sender_email": user.email,
        }

        # Create notifications for offline users
        notify_offline_users(
            household_id,
            user_id,
            "new_message",
            f"New message from {user.email}: {data['content'][:30]}...",
            new_message.id,
        )

    except Exception as e:
        print(f"Error in handle_message: {str(e)}")
        emit("error", {"message": str(e)})
        return {"status": "error", "message": str(e)}


@socketio.on("authenticate")
def handle_authenticate(data):
    try:
        token = data.get("token")
        if not token:
            emit("error", {"message": "Token required"})
            return

        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        # Track online status
        online_users[user_id] = {
            "sid": request.sid,
            "connected": True,
            "households": [],
        }

        emit("authenticated", {"user_id": user_id})
    except Exception as e:
        emit("error", {"message": str(e)})


@socketio.on("join_household")
def join_household(data):
    try:
        token = data.get("token")
        household_id = data.get("household_id")

        if not token or not household_id:
            emit("error", {"message": "Token and household_id required"})
            return

        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        # Check household membership
        household = Household.query.get(household_id)
        if not household:
            emit("error", {"message": "Household not found"})
            return

        # This should use the association table to check membership
        is_member = (
            db.session.query(user_households)
            .filter_by(user_id=user_id, household_id=household_id)
            .first()
        )

        if not is_member:
            emit("error", {"message": "Not a household member"})
            return

        # Join the room
        room = f"household_{household_id}"
        join_room(room)

        # Update online status
        if user_id in online_users:
            if household_id not in online_users[user_id].get("households", []):
                online_users[user_id]["households"].append(household_id)

        # Notify other members
        emit(
            "user_joined",
            {"user_id": user_id, "email": user.email},
            room=room,
            broadcast=True,
            include_self=False,
        )

        # Send recent messages (last 100)
        recent_messages = (
            Message.query.filter_by(household_id=household_id)
            .order_by(Message.created_at.desc())
            .limit(100)
            .all()
        )
        
        message_list = [
            {
                "id": m.id,
                "content": m.content,
                "sender_id": m.user_id,
                "sender_email": m.sender.email,
                "is_announcement": m.is_announcement,
                "created_at": m.created_at.isoformat(),
                "edited_at": m.edited_at.isoformat() if m.edited_at else None
            }
            for m in recent_messages
        ]
        
        # Send recent active polls
        active_polls = (
            Poll.query.filter_by(household_id=household_id)
            .filter(Poll.expires_at > datetime.utcnow())
            .all()
        )
        
        poll_list = []
        for poll in active_polls:
            creator = User.query.get(poll.created_by) if hasattr(poll, 'created_by') else None
            creator_email = creator.email if creator else "Unknown"
            
            poll_list.append({
                "id": poll.id,
                "question": poll.question,
                "options": poll.options,
                "expires_at": poll.expires_at.isoformat(),
                "created_by": creator_email,
                "created_at": poll.created_at.isoformat() if hasattr(poll, 'created_at') else None
            })

        emit(
            "joined_household",
            {
                "household_id": household_id,
                "message": f"Joined household chat",
                "recent_messages": message_list,
                "active_polls": poll_list
            },
        )

    except Exception as e:
        emit("error", {"message": str(e)})


@socketio.on("leave_household")
def leave_household(data):
    try:
        household_id = data.get("household_id")

        if not household_id:
            emit("error", {"message": "Household ID required"})
            return

        room = f"household_{household_id}"
        leave_room(room)

        # Update online status
        for user_id, data in online_users.items():
            if data.get("sid") == request.sid:
                if household_id in data.get("households", []):
                    data["households"].remove(household_id)
                break

        emit("left_household", {"household_id": household_id})
    except Exception as e:
        emit("error", {"message": str(e)})


def verify_jwt_token(token):
    """Verify JWT token and return user_id"""
    try:
        print(f"Verifying token: {token}")  # Log the token
        decoded = decode_token(token.encode('utf-8'))  # Convert to bytes
        return decoded["sub"]  # This should be the user_id
    except Exception as e:
        raise Exception(f"Invalid token: {str(e)}")


def is_user_online(user_id):
    """Check if a user is currently online"""
    return user_id in online_users and online_users[user_id].get("connected", False)


def notify_offline_users(
    household_id, sender_id, message_type, content, reference_id=None
):
    """Create notifications for users who are offline"""
    from ..models.models import Notification, user_households

    try:
        # Query all household members
        members_query = (
            db.session.query(user_households).filter_by(household_id=household_id).all()
        )

        for membership in members_query:
            member_id = membership.user_id

            # Skip the sender
            if member_id == sender_id:
                continue

            # Skip online users in this household
            if (
                member_id in online_users
                and online_users[member_id].get("connected")
                and household_id in online_users[member_id].get("households", [])
            ):
                continue

            # Create notification for offline user
            notification = Notification(
                type=message_type,
                content=content,
                user_id=member_id,
                household_id=household_id,
                reference_type="message" if message_type == "new_message" else "poll",
                reference_id=reference_id,
            )
            db.session.add(notification)

        db.session.commit()
    except Exception as e:
        db.session.rollback()


# REST Endpoints
@chat_bp.route("/households/<household_id>/messages", methods=["GET"])
@jwt_required()
def get_messages(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    household = Household.query.get(household_id)

    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    # Support cursor-based pagination for efficiency
    before_id = request.args.get("before_id", type=int)
    after_id = request.args.get("after_id", type=int)
    limit = request.args.get("limit", 500, type=int)  # Default to 500 messages
    
    # Build query
    query = Message.query.filter_by(household_id=household_id)
    
    # Apply cursor-based pagination if specified
    if before_id:
        message = Message.query.get(before_id)
        if message:
            query = query.filter(Message.created_at < message.created_at)
    elif after_id:
        message = Message.query.get(after_id)
        if message:
            query = query.filter(Message.created_at > message.created_at)
    
    # Get the messages, ordered by creation time
    messages = query.order_by(Message.created_at.desc()).limit(limit).all()
    
    # Convert to JSON-serializable format
    message_list = [
        {
            "id": m.id,
            "content": m.content,
            "sender_id": m.user_id,
            "sender_email": m.sender.email,
            "is_announcement": m.is_announcement,
            "created_at": m.created_at.isoformat(),
            "edited_at": m.edited_at.isoformat() if m.edited_at else None
        }
        for m in messages
    ]

    return jsonify({"messages": message_list}), 200


@chat_bp.route("/households/<household_id>/messages", methods=["POST"])
@jwt_required()
def send_message(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Check if the user is a member of the household
    household = Household.query.get(household_id)
    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message content is required"}), 400

    try:
        new_message = Message(
            content=data["message"],
            household_id=household_id,
            user_id=current_user_id,
            is_announcement=data.get("isAnnouncement", False),
        )
        db.session.add(new_message)
        db.session.commit()

        return jsonify({"message": "Message sent successfully", "message_id": new_message.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/households/<household_id>/polls", methods=["POST"])
@jwt_required()
def create_poll(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    household = Household.query.get(household_id)

    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    data = request.get_json()
    new_poll = Poll(
        question=data["question"],
        options={
            option: 0 for option in data["options"]
        },  # Initialize vote counts to 0
        expires_at=datetime.fromisoformat(data["expires_at"]),
        household_id=household.id,
    )
    db.session.add(new_poll)
    db.session.commit()

    # Broadcast new poll to all household members
    socketio.emit(
        "new_poll",
        {
            "id": new_poll.id,
            "question": new_poll.question,
            "options": new_poll.options,
            "expires_at": new_poll.expires_at.isoformat(),
            "created_by": user.email,
        },
        room=f"household_{household_id}",
    )

    return jsonify({"message": "Poll created", "poll_id": new_poll.id}), 201


@chat_bp.route("/polls/<poll_id>/vote", methods=["POST"])
@jwt_required()
def vote_poll(poll_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    poll = Poll.query.get(poll_id)

    if not poll or user not in poll.household.members:
        return jsonify({"error": "Not authorized"}), 403

    if poll.expires_at < datetime.utcnow():
        return jsonify({"error": "Poll has expired"}), 400

    data = request.get_json()
    selected_option = data["selected_option"]

    if selected_option not in poll.options:
        return jsonify({"error": "Invalid option"}), 400

    # Check for existing vote
    existing_vote = Vote.query.filter_by(poll_id=poll_id, user_id=user.id).first()
    if existing_vote:
        return jsonify({"error": "Already voted"}), 409

    # Record vote
    new_vote = Vote(poll_id=poll_id, user_id=user.id, selected_option=selected_option)
    db.session.add(new_vote)

    # Update poll options
    poll.options[selected_option] += 1
    db.session.commit()

    # Broadcast updated poll results using socketio.emit instead of emit
    socketio.emit(
        "poll_updated",
        {"poll_id": poll.id, "options": poll.options},
        room=f"household_{poll.household_id}",
    )

    return jsonify({"message": "Vote recorded"}), 200


@chat_bp.route("/polls/<poll_id>", methods=["GET"])
@jwt_required()
def get_poll_results(poll_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    poll = Poll.query.get(poll_id)

    if not poll or user not in poll.household.members:
        return jsonify({"error": "Not authorized"}), 403

    return (
        jsonify(
            {
                "id": poll.id,
                "question": poll.question,
                "options": poll.options,
                "expires_at": poll.expires_at.isoformat(),
                "created_by": poll.created_by,
            }
        ),
        200,
    )


@socketio.on("edit_message")
def handle_edit_message(data):
    try:
        token = data.get("token")
        if not token:
            emit("error", {"message": "Token required"})
            return

        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        message_id = data.get("message_id")
        new_content = data.get("content")

        if not message_id or not new_content:
            emit("error", {"message": "Message ID and content required"})
            return

        message = Message.query.get(message_id)

        if not message:
            emit("error", {"message": "Message not found"})
            return

        # Only the sender can edit their message
        if message.user_id != user_id:
            emit("error", {"message": "Not authorized to edit this message"})
            return

        # Don't allow editing messages older than 24 hours
        if datetime.utcnow() - message.created_at > timedelta(hours=24):
            emit("error", {"message": "Cannot edit messages older than 24 hours"})
            return

        # Update message
        message.content = new_content
        message.edited_at = datetime.utcnow()
        db.session.commit()

        # Broadcast edit to all in the room
        room = f"household_{message.household_id}"
        emit(
            "message_edited",
            {
                "id": message.id,
                "content": message.content,
                "edited_at": message.edited_at.isoformat(),
            },
            room=room,
        )

    except Exception as e:
        emit("error", {"message": str(e)})


@socketio.on("delete_message")
def handle_delete_message(data):
    try:
        token = data.get("token")
        if not token:
            emit("error", {"message": "Token required"})
            return

        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        message_id = data.get("message_id")

        if not message_id:
            emit("error", {"message": "Message ID required"})
            return

        message = Message.query.get(message_id)

        if not message:
            emit("error", {"message": "Message not found"})
            return

        # Only the sender or admin can delete a message
        is_admin = check_household_permission(user, message.household_id, "admin")
        if message.user_id != user_id and not is_admin:
            emit("error", {"message": "Not authorized to delete this message"})
            return

        # Delete the message
        household_id = message.household_id
        db.session.delete(message)
        db.session.commit()

        # Broadcast deletion to all in the room
        room = f"household_{household_id}"
        emit(
            "message_deleted",
            {"id": message_id, "deleted_by": user_id},
            room=room,
        )

    except Exception as e:
        emit("error", {"message": str(e)})


@socketio.on("typing_start")
def handle_typing_start(data):
    try:
        token = data.get("token")
        if not token:
            emit("error", {"message": "Token required"})
            return

        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        household_id = data.get("household_id")
        if not household_id:
            emit("error", {"message": "Household ID required"})
            return

        # Verify user is a member of this household
        is_member = (
            db.session.query(user_households)
            .filter_by(user_id=user_id, household_id=household_id)
            .first()
        )

        if not is_member:
            emit("error", {"message": "Not a household member"})
            return

        # Broadcast typing status to all users in the household (except sender)
        room = f"household_{household_id}"
        emit(
            "user_typing",
            {
                "user_id": user_id,
                "user_email": user.email,
                "user_name": getattr(user, "name", user.email.split("@")[0]),
            },
            room=room,
            include_self=False,
        )

    except Exception as e:
        emit("error", {"message": str(e)})


@socketio.on("typing_stop")
def handle_typing_stop(data):
    try:
        token = data.get("token")
        if not token:
            emit("error", {"message": "Token required"})
            return

        user_id = verify_jwt_token(token)
        user = User.query.get(user_id)

        if not user:
            emit("error", {"message": "User not found"})
            return

        household_id = data.get("household_id")
        if not household_id:
            emit("error", {"message": "Household ID required"})
            return

        # Broadcast typing stopped to all users in the household
        room = f"household_{household_id}"
        emit("user_typing_stopped", {"user_id": user_id}, room=room, include_self=False)

    except Exception as e:
        emit("error", {"message": str(e)})


def check_household_permission(user, household_id, role):
    """Check if the user has a specific role in the household."""
    # Assuming you have a UserHousehold model that links users to households with roles
    membership = (
        db.session.query(user_households)
        .filter_by(user_id=user.id, household_id=household_id)
        .first()
    )
    return membership.role == role if membership else False


@chat_bp.route("/households/<household_id>/polls", methods=["GET"])
@jwt_required()
def get_polls(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    household = Household.query.get(household_id)

    if not household or user not in household.members:
        return jsonify({"error": "Not a household member"}), 403

    # Support cursor-based pagination for efficiency
    before_id = request.args.get("before_id", type=int)
    after_id = request.args.get("after_id", type=int)
    limit = request.args.get("limit", 50, type=int)  # Default to 50 polls (usually fewer than messages)
    include_expired = request.args.get("include_expired", "false").lower() == "true"
    
    # Build query
    query = Poll.query.filter_by(household_id=household_id)
    
    # Only include active polls by default
    if not include_expired:
        query = query.filter(Poll.expires_at > datetime.utcnow())
    
    # Apply cursor-based pagination if specified
    if before_id:
        poll = Poll.query.get(before_id)
        if poll:
            query = query.filter(Poll.created_at < poll.created_at)
    elif after_id:
        poll = Poll.query.get(after_id)
        if poll:
            query = query.filter(Poll.created_at > poll.created_at)
    
    # Get the polls, ordered by creation time
    polls = query.order_by(Poll.created_at.desc()).limit(limit).all()
    
    # Get the creator's email for each poll
    poll_list = []
    for poll in polls:
        creator = User.query.get(poll.created_by) if hasattr(poll, 'created_by') else None
        creator_email = creator.email if creator else "Unknown"
        
        poll_list.append({
            "id": poll.id,
            "question": poll.question,
            "options": poll.options,
            "expires_at": poll.expires_at.isoformat(),
            "created_by": creator_email,
            "created_at": poll.created_at.isoformat() if hasattr(poll, 'created_at') else None
        })

    return jsonify({"polls": poll_list}), 200
