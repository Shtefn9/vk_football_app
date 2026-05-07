from database import db
from datetime import datetime


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('UserTeam', backref='team', lazy=True)


class UserTeam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='player')  # 'coach', 'player'
    # Игровая позиция — назначается тренером
    position = db.Column(db.String(20), default='forward')  # 'goalkeeper', 'defender', 'forward'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

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

    # Общие поля (все роли, оба тарифа)
    goals = db.Column(db.Integer, default=0)
    assists = db.Column(db.Integer, default=0)
    yellow_cards = db.Column(db.Integer, default=0)
    red_cards = db.Column(db.Integer, default=0)
    minutes_played = db.Column(db.Integer, default=0)

    # Полевые игроки — базовый
    shots_total = db.Column(db.Integer, default=0)
    shots_on_target = db.Column(db.Integer, default=0)

    # Полевые игроки — детальный
    passes_total = db.Column(db.Integer, default=0)
    passes_accurate = db.Column(db.Integer, default=0)
    tackles = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)

    # Вратарь — базовый
    saves = db.Column(db.Integer, default=0)
    goals_conceded = db.Column(db.Integer, default=0)

    # Вратарь — детальный
    gk_passes_total = db.Column(db.Integer, default=0)
    gk_passes_accurate = db.Column(db.Integer, default=0)
    gk_losses = db.Column(db.Integer, default=0)
    goal_kicks_total = db.Column(db.Integer, default=0)
    goal_kicks_accurate = db.Column(db.Integer, default=0)

    # Рейтинг (только детальный)
    rating = db.Column(db.Float, default=0.0)