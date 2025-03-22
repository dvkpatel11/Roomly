from ..extensions import db
from ..models.models import user_households


def check_household_permission(user, household_id, required_role):
    """
    Verify if a user has the required role in a specific household.

    Args:
        user (User): The user object to check
        household_id (str): UUID of the household
        required_role (str): Minimum required role ('admin' or 'member')

    Returns:
        bool: True if user has permission, False otherwise
    """
    # Get the user's role in this household
    result = (
        db.session.query(user_households.c.role)
        .filter(
            user_households.c.user_id == user.id,
            user_households.c.household_id == household_id,
        )
        .first()
    )

    if not result:
        return False  # User not in household

    user_role = result.role

    # Define role hierarchy
    ROLE_HIERARCHY = {"member": 0, "admin": 1}

    # Check if user's role meets or exceeds required role
    return ROLE_HIERARCHY.get(user_role, -1) >= ROLE_HIERARCHY.get(required_role, 0)
