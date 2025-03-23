from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.models import User, Household, user_households
from ..extensions import db

users_bp = Blueprint("users", __name__, url_prefix="/users")

@users_bp.route("/me/preferences", methods=["PATCH"])
@jwt_required()
def update_user_preferences():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    data = request.get_json()
    
    # Make sure we have preferences dictionary
    if not hasattr(user, 'preferences') or user.preferences is None:
        user.preferences = {}
    
    # Update preferences
    if isinstance(data, dict):
        for key, value in data.items():
            user.preferences[key] = value
    
        # If active_household is being set, verify it exists and user is a member
        if 'active_household' in data and data['active_household']:
            household_id = data['active_household']
            is_member = db.session.query(user_households).filter_by(
                user_id=user.id, household_id=household_id
            ).first()
            
            if not is_member:
                return jsonify({
                    "error": "Cannot set active household. User is not a member of this household."
                }), 403
    
    try:
        db.session.commit()
        return jsonify({
            "message": "Preferences updated successfully",
            "preferences": user.preferences
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500 