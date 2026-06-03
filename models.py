from database import db
from datetime import datetime, timezone


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vk_id = db.Column(db.Integer, unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    photo_url = db.Column(db.String(300), default='')
    teams = db.relationship('UserTeam', backref='user', lazy=True)


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), default='')
    join_code = db.Column(db.String(10), unique=True, nullable=False)
    stats_level = db.Column(db.String(20), default='basic')
    trial_until = db.Column(db.DateTime, nullable=True)  # пробный период 7 дней
    subscription_until = db.Column(db.DateTime, nullable=True)  # платная подписка 90 дней
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    members = db.relationship('UserTeam', backref='team', lazy=True)

    @property
    def effective_stats_level(self):
        now = datetime.now()
        # Активна платная подписка
        if self.subscription_until and now < self.subscription_until:
            return 'detailed'
        # Активен пробный период
        if self.trial_until and now < self.trial_until:
            return 'detailed'
        return self.stats_level


class UserTeam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='player')
    position = db.Column(db.String(20), default='forward')
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'team_id', name='unique_user_team'),
    )


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    event_date = db.Column(db.DateTime, nullable=False)
    event_type = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(200), default='')
    description = db.Column(db.Text, default='')


class MatchStat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    goals = db.Column(db.Integer, default=0)
    assists = db.Column(db.Integer, default=0)
    yellow_cards = db.Column(db.Integer, default=0)
    red_cards = db.Column(db.Integer, default=0)
    minutes_played = db.Column(db.Integer, default=0)
    shots_total = db.Column(db.Integer, default=0)
    shots_on_target = db.Column(db.Integer, default=0)
    passes_total = db.Column(db.Integer, default=0)
    passes_accurate = db.Column(db.Integer, default=0)
    tackles = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    saves = db.Column(db.Integer, default=0)
    goals_conceded = db.Column(db.Integer, default=0)
    gk_passes_total = db.Column(db.Integer, default=0)
    gk_passes_accurate = db.Column(db.Integer, default=0)
    gk_losses = db.Column(db.Integer, default=0)
    goal_kicks_total = db.Column(db.Integer, default=0)
    goal_kicks_accurate = db.Column(db.Integer, default=0)
    rating = db.Column(db.Float, default=0.0)

class EventAttendance(db.Model):
    __tablename__ = 'event_attendance'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'going' / 'not_going'
    reason = db.Column(db.String(100))  # причина отказа, если status='not_going'
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('event_id', 'user_id', name='_event_user_uc'),)