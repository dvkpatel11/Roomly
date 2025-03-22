from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.models import User, Household, user_households
from ..utils.auth_utils import check_household_permission
from ..extensions import db
import secrets
import datetime
import base64
import hashlib
import hmac
import time

# Secret key for signing invitation codes (would be in environment variables in production)
INVITATION_SECRET = "Supersecretkey101"

household_bp = Blueprint("household", __name__)


# Create a new household
@household_bp.route("/households", methods=["POST"])
@jwt_required()
def create_household():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    data = request.get_json()

    if not data or not data.get("name"):
        return jsonify({"error": "Household name is required"}), 400

    try:
        new_household = Household(
            name=data.get("name"),
            admin_id=user.id,  # Set current user as admin
        )
        db.session.add(new_household)
        db.session.flush()  # Flush to get the ID without committing

        # Now that we have the ID, add creator as admin
        db.session.execute(
            user_households.insert().values(
                user_id=user.id,
                household_id=new_household.id,
                role="admin",
                joined_at=datetime.datetime.utcnow(),
            )
        )

        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Household created successfully",
                    "household": {
                        "id": new_household.id,
                        "name": new_household.name,
                        "role": "admin",
                        "admin_id": new_household.admin_id,
                        "createdAt": new_household.created_at.isoformat(),
                    },
                }
            ),
            201,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Get details of a specific household
@household_bp.route("/households/<household_id>", methods=["GET"])
@jwt_required()
def get_household(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Check if user is a member of this household
    is_member = (
        db.session.query(user_households)
        .filter_by(user_id=user.id, household_id=household_id)
        .first()
    )

    if not is_member:
        return jsonify({"error": "Not a member of this household"}), 403

    household = Household.query.get(household_id)
    if not household:
        return jsonify({"error": "Household not found"}), 404

    # Get members with their roles
    members_query = (
        db.session.query(User, user_households.c.role, user_households.c.joined_at)
        .join(user_households, User.id == user_households.c.user_id)
        .filter(user_households.c.household_id == household.id)
        .all()
    )

    members_list = [
        {
            "id": member.User.id,
            "name": (
                member.User.name
                if hasattr(member.User, "name")
                else member.User.email.split("@")[0]
            ),
            "email": member.User.email,
            "avatar": getattr(member.User, "avatar", None),
            "role": member.role,
            "joined_at": (
                member.joined_at.isoformat()
                if member.joined_at
                else datetime.datetime.utcnow().isoformat()
            ),
        }
        for member in members_query
    ]

    return (
        jsonify(
            {
                "id": household.id,
                "name": household.name,
                "members": members_list,
                "admin_id": household.admin_id,
                "createdAt": household.created_at.isoformat(),
            }
        ),
        200,
    )


# Get all households for current user
@household_bp.route("/households", methods=["GET"])
@jwt_required()
def get_user_households():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    households_with_roles = (
        db.session.query(Household, user_households.c.role)
        .join(user_households, Household.id == user_households.c.household_id)
        .filter(user_households.c.user_id == user.id)
        .all()
    )

    household_list = []
    for h in households_with_roles:
        # Get member count
        member_count = (
            db.session.query(user_households)
            .filter_by(household_id=h.Household.id)
            .count()
        )

        household_list.append(
            {
                "id": h.Household.id,
                "name": h.Household.name,
                "role": h.role,
                "memberCount": member_count,
                "admin_id": h.Household.admin_id,
                "createdAt": h.Household.created_at.isoformat(),
            }
        )

    return jsonify(household_list), 200


# Get active household (first household for the user or last accessed)
@household_bp.route("/households/active", methods=["GET"])
@jwt_required()
def get_active_household():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Try to get the user's last accessed household from preferences
    active_household_id = None
    if user.preferences and "active_household" in user.preferences:
        active_household_id = user.preferences["active_household"]

        # Verify user still has access to this household
        household_access = (
            db.session.query(user_households)
            .filter_by(user_id=user.id, household_id=active_household_id)
            .first()
        )

        if not household_access:
            active_household_id = None

    # If no active household set, get the first household
    if not active_household_id:
        household_membership = (
            db.session.query(user_households).filter_by(user_id=user.id).first()
        )

        if not household_membership:
            return jsonify({"error": "No households found"}), 404

        active_household_id = household_membership.household_id

        # Update user preferences to remember this household
        if not user.preferences:
            user.preferences = {}
        user.preferences["active_household"] = active_household_id
        db.session.commit()

    # Get the full household details
    household = Household.query.get(active_household_id)
    if not household:
        return jsonify({"error": "Household not found"}), 404

    # Get members with their roles
    members_query = (
        db.session.query(User, user_households.c.role, user_households.c.joined_at)
        .join(user_households, User.id == user_households.c.user_id)
        .filter(user_households.c.household_id == household.id)
        .all()
    )

    members_list = [
        {
            "id": member.User.id,
            "name": (
                member.User.name
                if hasattr(member.User, "name")
                else member.User.email.split("@")[0]
            ),
            "email": member.User.email,
            "avatar": getattr(member.User, "avatar", None),
            "role": member.role,
            "joined_at": (
                member.joined_at.isoformat()
                if member.joined_at
                else datetime.datetime.utcnow().isoformat()
            ),
        }
        for member in members_query
    ]

    return (
        jsonify(
            {
                "id": household.id,
                "name": household.name,
                "members": members_list,
                "admin_id": household.admin_id,
                "createdAt": household.created_at.isoformat(),
            }
        ),
        200,
    )


# Update household details
@household_bp.route("/households/<household_id>", methods=["PATCH"])
@jwt_required()
def update_household(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    data = request.get_json()

    # Check if user is admin
    if not check_household_permission(user, household_id, "admin"):
        return jsonify({"error": "Admin privileges required"}), 403

    household = Household.query.get(household_id)
    if not household:
        return jsonify({"error": "Household not found"}), 404

    if "name" in data:
        household.name = data["name"]

    try:
        db.session.commit()
        return jsonify({"message": "Household updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Get all members of a household
@household_bp.route("/households/<household_id>/members", methods=["GET"])
@jwt_required()
def get_household_members(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Check if user is a member of this household
    is_member = (
        db.session.query(user_households)
        .filter_by(user_id=user.id, household_id=household_id)
        .first()
    )

    if not is_member:
        return jsonify({"error": "Not a member of this household"}), 403

    # Get all members with their roles
    members_query = (
        db.session.query(User, user_households.c.role, user_households.c.joined_at)
        .join(user_households, User.id == user_households.c.user_id)
        .filter(user_households.c.household_id == household_id)
        .all()
    )

    members_list = [
        {
            "id": member.User.id,
            "email": member.User.email,
            "first_name": member.User.first_name,
            "last_name": member.User.last_name,
            "full_name": member.User.full_name,
            "role": member.role,
            "joined_at": (
                member.joined_at.isoformat()
                if member.joined_at
                else datetime.datetime.utcnow().isoformat()
            ),
        }
        for member in members_query
    ]

    return jsonify(members_list), 200


# Update member role
@household_bp.route(
    "/households/<household_id>/members/<member_id>/role", methods=["PATCH"]
)
@jwt_required()
def update_member_role(household_id, member_id):
    current_user_id = get_jwt_identity()
    requester = User.query.get(current_user_id)
    data = request.get_json()

    # Check if requester is admin
    if not check_household_permission(requester, household_id, "admin"):
        return jsonify({"error": "Admin privileges required"}), 403

    # Check if target user exists and is a member
    target_membership = (
        db.session.query(user_households)
        .filter_by(user_id=member_id, household_id=household_id)
        .first()
    )

    if not target_membership:
        return jsonify({"error": "Member not found in household"}), 404

    # Update the role
    new_role = data.get("role")
    if not new_role or new_role not in ["admin", "member"]:
        return jsonify({"error": "Valid role required (admin or member)"}), 400

    try:
        db.session.execute(
            user_households.update()
            .where(
                (user_households.c.user_id == member_id)
                & (user_households.c.household_id == household_id)
            )
            .values(role=new_role)
        )
        db.session.commit()
        return jsonify({"message": "Role updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Generate invitation code
@household_bp.route("/households/<household_id>/invitations", methods=["POST"])
@jwt_required()
def create_invitation(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Check if user is admin or member with invite permissions
    if not check_household_permission(user, household_id, "admin"):
        return jsonify({"error": "Admin privileges required"}), 403

    # Check if household exists
    household = Household.query.get(household_id)
    if not household:
        return jsonify({"error": "Household not found"}), 404

    # Generate code based on household ID
    invitation_info = generate_invitation_code(household_id)

    return jsonify(invitation_info), 201


# Join household with invitation code
@household_bp.route("/households/join-by-invitation", methods=["POST"])
@jwt_required()
def join_by_invitation():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    data = request.get_json()

    invitation_code = data.get("code")
    if not invitation_code:
        return jsonify({"error": "Invitation code required"}), 400

    # Validate and decode the invitation code
    household_id, error = validate_invitation_code(invitation_code)
    if error:
        return jsonify({"error": error}), 400

    household = Household.query.get(household_id)
    if not household:
        return jsonify({"error": "Household not found"}), 404

    # Check if already a member
    existing_membership = (
        db.session.query(user_households)
        .filter_by(user_id=user.id, household_id=household.id)
        .first()
    )

    if existing_membership:
        return jsonify({"error": "Already a member of this household"}), 409

    try:
        db.session.execute(
            user_households.insert().values(
                user_id=user.id,
                household_id=household.id,
                role="member",
                joined_at=datetime.datetime.utcnow(),
            )
        )
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Successfully joined household",
                    "household": {
                        "id": household.id,
                        "name": household.name,
                        "role": "member",
                        "admin_id": household.admin_id,
                        "createdAt": household.created_at.isoformat(),
                    },
                }
            ),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Remove member from household
@household_bp.route(
    "/households/<household_id>/members/<member_id>", methods=["DELETE"]
)
@jwt_required()
def remove_member(household_id, member_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Admin can remove anyone, members can only remove themselves
    is_admin = check_household_permission(user, household_id, "admin")
    is_self = user.id == member_id

    if not (is_admin or is_self):
        return jsonify({"error": "Not authorized to remove this member"}), 403

    try:
        deletion_query = user_households.delete().where(
            (user_households.c.user_id == member_id)
            & (user_households.c.household_id == household_id)
        )

        result = db.session.execute(deletion_query)

        if result.rowcount == 0:
            return jsonify({"error": "Member not found in household"}), 404

        db.session.commit()

        # If removing self, return appropriate message
        if is_self:
            return jsonify({"message": "Successfully left household"}), 200
        else:
            return jsonify({"message": "Member successfully removed"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Delete household (admin only)
@household_bp.route("/households/<household_id>", methods=["DELETE"])
@jwt_required()
def delete_household(household_id):
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # Check if user is admin
    if not check_household_permission(user, household_id, "admin"):
        return jsonify({"error": "Admin privileges required"}), 403

    household = Household.query.get(household_id)
    if not household:
        return jsonify({"error": "Household not found"}), 404

    try:
        # First delete all membership associations
        db.session.execute(
            user_households.delete().where(
                user_households.c.household_id == household_id
            )
        )

        # Then delete the household itself
        db.session.delete(household)
        db.session.commit()

        return jsonify({"message": "Household successfully deleted"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def generate_invitation_code(household_id, expires_in_days=7):
    """
    Generate an invitation code based on household_id with expiration

    Format: base64(household_id + expiry_timestamp + signature)
    """
    # Calculate expiration timestamp
    expiry = int(time.time() + (expires_in_days * 86400))  # seconds in a day

    # Create the message to sign (household_id + expiry time)
    message = f"{household_id}:{expiry}"

    # Create a signature using HMAC
    signature = hmac.new(
        INVITATION_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()[
        :8
    ]  # Use only first 8 chars of signature for brevity

    # Combine data with signature
    code_data = f"{message}:{signature}"

    # Encode to base64 and make URL-safe
    code = base64.urlsafe_b64encode(code_data.encode()).decode()

    return {
        "code": code,
        "expires_at": datetime.datetime.fromtimestamp(expiry).isoformat(),
    }


def validate_invitation_code(code):
    """
    Validate an invitation code, extracting the household_id if valid
    """
    try:
        # Decode the base64 code
        decoded = base64.urlsafe_b64decode(code.encode()).decode()

        # Split into parts
        parts = decoded.split(":")
        if len(parts) != 3:
            return None, "Invalid code format"

        household_id, expiry_str, signature = parts

        # Check if expired
        expiry = int(expiry_str)
        if time.time() > expiry:
            return None, "Invitation code has expired"

        # Verify signature
        message = f"{household_id}:{expiry_str}"
        expected_signature = hmac.new(
            INVITATION_SECRET.encode(), message.encode(), hashlib.sha256
        ).hexdigest()[:8]

        if signature != expected_signature:
            return None, "Invalid invitation code"

        return household_id, None

    except Exception as e:
        return None, f"Invalid code: {str(e)}"
