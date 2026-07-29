from functools import wraps

from flask import abort
from flask_login import current_user

# Jerarquía simple: admin puede todo lo que puede moderator, que puede
# todo lo que puede readonly. Se usa para decidir si un rol "alcanza".
ROLE_LEVELS = {"readonly": 0, "moderator": 1, "admin": 2}


def roles_required(*allowed_roles: str):
    """
    Restringe una vista a uno o más roles. Requiere que el usuario ya
    esté autenticado (usar junto a @login_required, o dejar que este
    decorador lo exija implícitamente vía current_user.is_authenticated).

    Uso:
        @players_bp.route("/<uuid>/notes", methods=["POST"])
        @login_required
        @roles_required("admin", "moderator")
        def add_note(uuid): ...
    """
    min_level = min(ROLE_LEVELS[r] for r in allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            user_level = ROLE_LEVELS.get(current_user.role, -1)
            if user_level < min_level:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
