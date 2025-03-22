import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-key-123")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret-456")
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 1800))
    DEBUG = os.getenv("DEBUG", "True") == "True"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # Disable overhead

    # SocketIO configuration
    SOCKETIO_PING_TIMEOUT = int(os.getenv("SOCKETIO_PING_TIMEOUT", 20))
    SOCKETIO_PING_INTERVAL = int(os.getenv("SOCKETIO_PING_INTERVAL", 25))
    SOCKETIO_ASYNC_MODE = "gevent"
    SOCKETIO_LOGGER = DEBUG
    SOCKETIO_ENGINEIO_LOGGER = DEBUG

    # Add JWT configuration for refresh tokens
    JWT_REFRESH_TOKEN_EXPIRES = int(
        os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 2592000)
    )  # 30 days

    # CORS configuration
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    CORS_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    CORS_ALLOW_HEADERS = [
        # Standard headers
        "Content-Type",
        "Authorization",
        "Accept",
        "Origin",
        # Custom headers
        "X-Household-ID",
        "X-Requested-With",
        # Cache control
        "Cache-Control",
        "If-Match",
        "If-None-Match",
        # Content negotiation
        "Accept-Language",
        "Accept-Encoding",
    ]
    CORS_EXPOSE_HEADERS = [
        "Content-Range",
        "X-Total-Count",
        "ETag",
        "Cache-Control",
    ]
    CORS_SUPPORTS_CREDENTIALS = True
    CORS_MAX_AGE = 600  # Maximum time to cache preflight requests (10 minutes)
