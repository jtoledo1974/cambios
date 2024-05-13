"""Flask App for managing shifts."""

import collections

from flask import Response, redirect, render_template, request, session, url_for

from .config import app, db
from .models import Shift, User


@app.route("/")
def index() -> Response:
    """Render the index page."""
    if "user_id" in session:
        user = User.query.get(session["user_id"])
        shifts = Shift.query.order_by(Shift.date).all()
        shift_data = collections.defaultdict(
            lambda: {"M": "Open", "T": "Open", "N": "Open"},
        )
        for shift in shifts:
            date_str = shift.date.strftime("%Y-%m-%d")
            shift_data[date_str][shift.shift_type] = shift.user.username
        return render_template("index.html", user=user, shift_data=shift_data)
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login() -> str:
    """Render the login page."""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            session["user_id"] = user.id
            return redirect(url_for("index"))
        return "Login Failed"
    return render_template("login.html")


@app.route("/logout")
def logout() -> Response:
    """Logout the user."""
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register() -> Response:
    """Render the register page."""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)