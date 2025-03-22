from flask import Flask
from .config import Config
from .extensions import jwt, cors, db, migrate, socketio


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={
            r"/*": {
                "origins": app.config["CORS_ORIGINS"],
                "methods": app.config["CORS_METHODS"],
                "allow_headers": app.config["CORS_ALLOW_HEADERS"],
                "expose_headers": app.config["CORS_EXPOSE_HEADERS"],
                "supports_credentials": app.config["CORS_SUPPORTS_CREDENTIALS"],
            }
        },
    )
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(
        app,
        cors_allowed_origins=app.config["CORS_ORIGINS"],
        ping_timeout=app.config["SOCKETIO_PING_TIMEOUT"],
        ping_interval=app.config["SOCKETIO_PING_INTERVAL"],
        logger=app.config["SOCKETIO_LOGGER"],
        engineio_logger=app.config["SOCKETIO_ENGINEIO_LOGGER"],
    )

    # Register blueprints
    from .routes.auth_routes import auth_bp
    from .routes.chat_routes import chat_bp
    from .routes.calendar_routes import calendar_bp
    from .routes.badge_routes import badge_bp
    from .routes.analytics_routes import analytics_bp
    from .routes.task_routes import task_bp
    from .routes.household_routes import household_bp
    from .routes.notification_routes import notification_bp
    from .routes.poll_routes import poll_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(badge_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(poll_bp)

    # Setup JWT error handlers and loaders
    @jwt.user_identity_loader
    def user_identity_lookup(user_id):
        return user_id

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        from .models.models import User

        identity = jwt_data["sub"]
        return User.query.filter_by(id=identity).one_or_none()

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return {"error": "Token has expired"}, 401

    # Setup database migration support
    with app.app_context():
        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            # Enable foreign keys for SQLite
            def _fk_pragma_on_connect(dbapi_con, con_record):
                dbapi_con.execute("pragma foreign_keys=ON")

            from sqlalchemy import event

            event.listen(db.engine, "connect", _fk_pragma_on_connect)

            # Create tables for in-memory database
            db.create_all()

    return app
