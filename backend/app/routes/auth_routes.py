from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    jwt_required,
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
)
from ..models.models import User, Household, user_households
from ..extensions import db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    if (
        not data
        or "email" not in data
        or "password" not in data
        or "first_name" not in data
        or "last_name" not in data
    ):
        return jsonify({"error": "Missing required fields"}), 400

    existing_user = User.query.filter_by(email=data["email"]).first()
    if existing_user:
        return jsonify({"error": "User already exists"}), 409

    try:
        new_user = User(
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            preferences=data.get("preferences", {}),
        )
        new_user.set_password(data["password"])
        db.session.add(new_user)
        db.session.commit()

        access_token = create_access_token(identity=new_user.id)
        refresh_token = create_refresh_token(identity=new_user.id)

        return (
            jsonify(
                {
                    "message": "User created",
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "user": {
                        "id": new_user.id,
                        "email": new_user.email,
                        "first_name": new_user.first_name,
                        "last_name": new_user.last_name,
                        "full_name": new_user.full_name,
                        "preferences": new_user.preferences,
                    },
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data.get("email")).first()
    if not user or not user.check_password(data.get("password", "")):
        return jsonify({"error": "Invalid credentials"}), 401

    access_token = create_access_token(identity=user.id)
    refresh_token = create_refresh_token(identity=user.id)

    return (
        jsonify(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "full_name": user.full_name,
                    "role": user.role,
                    "preferences": user.preferences,
                },
            }
        ),
        200,
    )


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def get_profile():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return (
        jsonify(
            {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "full_name": user.full_name,
                "role": user.role,
                "preferences": user.preferences,
                "households": [h.id for h in user.households],
            }
        ),
        200,
    )


@auth_bp.route("/me", methods=["PATCH"])
@jwt_required()
def update_profile():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    data = request.get_json()

    if "first_name" in data:
        user.first_name = data["first_name"]

    if "last_name" in data:
        user.last_name = data["last_name"]

    if "preferences" in data:
        user.preferences = {**user.preferences, **data["preferences"]}

    if "password" in data:
        user.set_password(data["password"])

    try:
        db.session.commit()
        return jsonify({"message": "Profile updated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/auth/households", methods=["POST"])
@jwt_required()
def create_household():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    data = request.get_json()

    try:
        new_household = Household(
            name=data.get("name", "Our Household"),
            admin_id=user.id,
        )
        db.session.add(new_household)

        # Add creator as admin
        db.session.execute(
            user_households.insert().values(
                user_id=user.id, household_id=new_household.id, role="admin"
            )
        )

        db.session.commit()
        return (
            jsonify({"message": "Household created", "household_id": new_household.id}),
            201,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    new_access_token = create_access_token(identity=current_user)
    return jsonify(access_token=new_access_token), 200
