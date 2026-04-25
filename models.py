from database import db
from datetime import datetime


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vk_id = db.Column(db.Integer, unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    photo_url = db.Column(db.String(300), default='')
    role = db.Column(db.String(20), default='player')
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), default='')
    coach_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    join_code = db.Column(db.String(10), unique=True, nullable=False)
    stats_level = db.Column(db.String(20), default='minimal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
    passes_total = db.Column(db.Integer, default=0)
    passes_accurate = db.Column(db.Integer, default=0)
    shots_total = db.Column(db.Integer, default=0)
    tackles = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)