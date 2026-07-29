from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash

from ...models import DashboardUser
from datetime import datetime
from ...extensions import db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = DashboardUser.query.filter_by(username=username).first()
        if user is None or not check_password_hash(user.password_hash, password):
            flash("Usuario o contraseña incorrectos.", "error")
            return render_template("auth/login.html")

        if not user.is_active:
            flash("Esta cuenta está desactivada.", "error")
            return render_template("auth/login.html")

        login_user(user)
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("main.index"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
