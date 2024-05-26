"""Routes for the Cambios app."""

from __future__ import annotations

import contextlib
from datetime import datetime
from functools import wraps
from typing import TYPE_CHECKING, Callable

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from pytz import timezone as tzinfo

from .cambios import MonthCalGen, is_admin
from .database import db
from .firebase import invalidate_token, verify_id_token
from .models import User
from .upload import process_file

if TYPE_CHECKING:  # pragma: no cover
    from flask import Flask
    from werkzeug import Response

main = Blueprint("main", __name__)


def privacy_policy_accepted(f: Callable) -> Callable:
    """Decorate a route to check if the user has accepted the privacy policy."""

    @wraps(f)
    def decorated_function(*args, **kwargs) -> Response | str:  # noqa: ANN002, ANN003
        """Check if the user has accepted the privacy policy."""
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("main.login"))

        user = db.session.get(User, user_id)
        if user and not user.has_accepted_terms:
            flash("Debes aceptar la política de privacidad para continuar.", "warning")
            return redirect(url_for("main.privacy_policy"))

        return f(*args, **kwargs)

    return decorated_function


@main.route("/")
@privacy_policy_accepted
def index() -> Response | str:
    """Render the index page."""
    if "user_id" not in session:
        return redirect(url_for("main.login"))

    user = db.session.get(User, session["user_id"])
    if not user:
        return redirect(url_for("main.logout"))

    # TODO #3 It would be better to use the user's timezone here
    # Currently forcing continental Spain using pytz
    today = datetime.now(tz=tzinfo("Europe/Madrid"))

    # Get month and year from query parameters or use current month and year
    month = request.args.get("month", type=int, default=today.month)
    year = request.args.get("year", type=int, default=today.year)

    calendar = MonthCalGen.generate(year, month, user, db.session)  # type: ignore[arg-type]

    # Check the session for the toggleDescriptions state
    if "toggleDescriptions" not in session:
        session["toggleDescriptions"] = request.user_agent.platform not in [
            "android",
            "iphone",
        ]

    return render_template(
        "index.html",
        user=user,
        calendar=calendar,
        toggle_descriptions=session["toggleDescriptions"],
    )


@main.route("/toggle_descriptions")
def toggle_descriptions() -> Response:
    """Toggle the descriptions on or off and save the state in the session."""
    session["toggleDescriptions"] = not session.get("toggleDescriptions", False)
    return redirect(url_for("main.index"))


@main.route("/login", methods=["GET", "POST"])
def login() -> Response | str:
    """Render the login page."""
    if request.method == "GET":
        if request.args.get("verify_email"):
            flash(
                "Se ha enviado un correo de verificación."
                " Por favor, verifica tu correo electrónico e inicia sesión de nuevo.",
                "info",
            )
        if request.args.get("logged_out"):
            flash("Has cerrado sesión.", "info")
        error = request.args.get("error")
        if error and isinstance(error, str):
            flash(error, "danger")
        return render_template("login.html")

    try:
        firebase_data = verify_id_token(request.form["idToken"])
        email = firebase_data["email"]
        session["firebase_uid"] = firebase_data["uid"]
    except ValueError:
        current_app.logger.exception(
            "Error verifying ID token %s",
            request.form["idToken"],
        )
        return redirect(url_for("main.logout", error="Autenticación fallida"))

    user = User.query.filter_by(email=email).first()
    if not user:
        # If the user database is empty we assume the first user is an admin.
        if not User.query.all():
            current_app.logger.info(
                "No users found in the database. Assuming first user is an admin.",
            )
            user = User(
                email=email,
                first_name="Admin",
                last_name="User",
                category="Admin",
                license_number=0,
                is_admin=True,
            )
            db.session.add(user)
            db.session.commit()
            session["is_admin"] = True
            flash("Usuario administrador creado.", "success")
            return redirect(url_for("admin.index"))

        current_app.logger.error("User not recognized. email=%s", email)
        return redirect(
            url_for(
                "main.logout",
                error="Usuario no reconocido. Hable con el administrador.",
            ),
        )

    session["user_id"] = user.id
    current_app.logger.info(
        "User %s logged in. email=%s",
        user.first_name + " " + user.last_name,
        email,
    )
    flash("Bienvenido, " + user.first_name + " " + user.last_name, "success")

    # Check for admin user.
    if is_admin(email):
        session["is_admin"] = True

    # Verificar si el usuario ha aceptado la política de privacidad
    if not user.has_accepted_terms:
        return redirect(url_for("main.privacy_policy"))

    return redirect(url_for("main.index"))


@main.route("/logout")
def logout() -> Response:
    """Logout the user."""
    firebase_id_token = session.get("firebase_uid")
    if firebase_id_token:
        with contextlib.suppress(Exception):
            invalidate_token(firebase_id_token)

    session.clear()
    error = request.args.get("error")
    if error:
        return redirect(url_for("main.login", logged_out=True, error=error))
    return redirect(url_for("main.login", logged_out=True))


@main.route("/privacy_policy", methods=["GET", "POST"])
def privacy_policy() -> Response | str:
    """Render the privacy policy page and handle acceptance."""
    if request.method == "POST":
        if "accept_policy" in request.form:
            user = db.session.get(User, session["user_id"])
            if user:
                user.has_accepted_terms = True
                db.session.commit()
                return redirect(url_for("main.index"))
        flash("Debe aceptar la política de privacidad para continuar.", "danger")

    return render_template("privacy_policy.html")


@main.route("/upload", methods=["GET", "POST"])
@privacy_policy_accepted
def upload() -> Response | str:
    """Upload shift data to the server.

    For GET requests, render the upload page.
    For POST requests, upload the shift data to the server.
    """
    if session.get("is_admin") is not True:
        return redirect(url_for("main.index"))
    if request.method != "POST":
        return render_template("upload.html")
    file = request.files["file"]
    add_new = bool(request.form.get("add_new"))
    if not file.filename:
        flash("No se ha seleccionado un archivo", "danger")
        return redirect(url_for("main.upload"))

    try:
        n_users, n_shifts = process_file(
            file,
            db.session,
            add_new=add_new,
            app_logger=current_app.logger,
        )
    except ValueError:
        flash("Formato de archivo no válido", "danger")
        return redirect(url_for("main.upload"))

    flash(
        "Archivo cargado con éxito. "
        f"Usuarios reconocidos: {n_users}, turnos agregados: {n_shifts}",
        "success",
    )
    return redirect(url_for("main.index"))


def register_routes(app: Flask) -> Blueprint:
    """Register the routes with the app."""
    app.register_blueprint(main)
    return main
