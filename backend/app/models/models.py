from datetime import datetime
import uuid
import bcrypt
from ..extensions import db

# Association Tables
user_households = db.Table(
    "user_households",
    db.Column(
        "user_id", db.String(36), db.ForeignKey("users.id"), primary_key=True
    ),  # UUID stored as string
    db.Column(
        "household_id", db.String(36), db.ForeignKey("households.id"), primary_key=True
    ),
    db.Column("role", db.String(50)),  # 'admin' or 'member'
    db.Column("joined_at", db.DateTime, default=datetime.utcnow),
)

user_badges = db.Table(
    "user_badges",
    db.Column(
        "user_id", db.String(36), db.ForeignKey("users.id"), primary_key=True
    ),  # UUID stored as string
    db.Column("badge_id", db.String(36), db.ForeignKey("badges.id"), primary_key=True),
    db.Column("awarded_at", db.DateTime, default=datetime.utcnow),
)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(50), default="member")
    preferences = db.Column(db.JSON)  # {"likes": ["cooking"], "notifications": True}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    households = db.relationship(
        "Household",
        secondary=user_households,
        backref=db.backref("members", lazy="dynamic"),
    )
    tasks_created = db.relationship(
        "Task", backref="creator", foreign_keys="Task.created_by"
    )
    tasks_assigned = db.relationship(
        "Task", backref="assignee", foreign_keys="Task.assigned_to"
    )
    messages = db.relationship("Message", backref="sender")
    votes = db.relationship("Vote", backref="voter")
    badges = db.relationship(
        "Badge", secondary=user_badges, backref=db.backref("users", lazy="dynamic")
    )

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password):
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Household(db.Model):
    __tablename__ = "households"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    tasks = db.relationship("Task", backref="household")
    messages = db.relationship("Message", backref="household")
    polls = db.relationship("Poll", backref="household")
    events = db.relationship("Event", backref="household")
    files = db.relationship("File", backref="household")
    admin_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    admin = db.relationship(
        "User", backref=db.backref("administered_households", lazy="dynamic")
    )


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.String(20))  # 'daily', 'weekly', 'monthly', 'one_time'
    due_date = db.Column(db.DateTime)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    household_id = db.Column(
        db.String(36), db.ForeignKey("households.id"), nullable=False
    )
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    assigned_to = db.Column(db.String(36), db.ForeignKey("users.id"))

    # Relationships
    recurring_rule = db.relationship("RecurringTaskRule", uselist=False, backref="task")


class RecurringTaskRule(db.Model):
    __tablename__ = "recurring_task_rules"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    interval_days = db.Column(db.Integer)  # 7 for weekly
    anchor_date = db.Column(db.DateTime)  # First occurrence
    end_date = db.Column(db.DateTime)

    task_id = db.Column(db.String(36), db.ForeignKey("tasks.id"), unique=True)


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    content = db.Column(db.Text, nullable=False)
    is_announcement = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    household_id = db.Column(
        db.String(36), db.ForeignKey("households.id"), nullable=False
    )
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)


class Poll(db.Model):
    __tablename__ = "polls"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    question = db.Column(db.String(255), nullable=False)
    options = db.Column(db.JSON)  # {"option1": 0, "option2": 0}
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    household_id = db.Column(
        db.String(36), db.ForeignKey("households.id"), nullable=False
    )

    # Relationships
    votes = db.relationship("Vote", backref="poll")


class Vote(db.Model):
    __tablename__ = "votes"

    poll_id = db.Column(db.String(36), db.ForeignKey("polls.id"), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), primary_key=True)
    selected_option = db.Column(db.String(100), nullable=False)


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    recurrence_rule = db.Column(db.String(255))  # iCal RRULE format
    privacy = db.Column(db.String(50), default="public")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    household_id = db.Column(
        db.String(36), db.ForeignKey("households.id"), nullable=False
    )
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)


class File(db.Model):
    __tablename__ = "files"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = db.Column(db.String(255), nullable=False)
    s3_key = db.Column(db.String(255), unique=True)
    is_encrypted = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    household_id = db.Column(
        db.String(36), db.ForeignKey("households.id"), nullable=False
    )
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)


class Badge(db.Model):
    __tablename__ = "badges"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    type = db.Column(
        db.String(50), unique=True, nullable=False
    )  # '5_day_streak', 'top_contributor'
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    type = db.Column(
        db.String(50), nullable=False
    )  # 'task_reminder', 'poll_update', 'announcement'
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    household_id = db.Column(
        db.String(36), db.ForeignKey("households.id"), nullable=False
    )

    # Optional reference fields
    reference_type = db.Column(db.String(50))  # 'task', 'poll', 'message'
    reference_id = db.Column(db.String(36))  # ID of the referenced object

    # Relationships
    user = db.relationship("User", backref=db.backref("notifications", lazy="dynamic"))
    household = db.relationship(
        "Household", backref=db.backref("notifications", lazy="dynamic")
    )


class NotificationSettings(db.Model):
    __tablename__ = "notification_settings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), unique=True, nullable=False
    )
    email_notifications = db.Column(db.Boolean, default=True)
    push_notifications = db.Column(db.Boolean, default=True)
    in_app_notifications = db.Column(db.Boolean, default=True)
    notification_types = db.Column(
        db.JSON,
        default=lambda: {
            "task_assigned": True,
            "task_completed": True,
            "task_overdue": True,
            "household_invitation": True,
            "household_joined": True,
            "event_reminder": True,
            "event_invitation": True,
            "poll_created": True,
            "badge_earned": True,
            "announcement": True,
        },
    )
    quiet_hours = db.Column(
        db.JSON,
        default=lambda: {"enabled": False, "start_time": None, "end_time": None},
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    user = db.relationship(
        "User", backref=db.backref("notification_settings", uselist=False)
    )
