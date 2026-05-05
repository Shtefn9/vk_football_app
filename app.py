from flask import Flask, render_template, request, session, jsonify
from database import db, init_db
from models import User, Team, UserTeam, Event, MatchStat
from datetime import datetime
import random
import string
import logging
import os

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'football.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'vk_football_secret_2024'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

init_db(app)


@app.after_request
def add_headers(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def get_user():
    user_id = session.get('user_id')
    if not user_id:
        body = request.get_json(silent=True) or {}
        uid = body.get('uid')
        if uid:
            try:
                user_id = int(uid)
            except (ValueError, TypeError):
                return None
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if user:
        session['user_id'] = user.id
        session.modified = True
    return user


def get_current_team_id():
    team_id = session.get('current_team_id')
    if not team_id:
        body = request.get_json(silent=True) or {}
        team_id = body.get('team_id')
    return int(team_id) if team_id else None


def calculate_rating(stat, stats_level):
    """Автоматический расчёт рейтинга игрока за матч (только для detailed)"""
    if stats_level != 'detailed':
        return None

    rating = 5.0

    # Голы (максимум 3 учитывается)
    rating += min(stat.goals, 3) * 1.0
    # Передачи (максимум 3)
    rating += min(stat.assists, 3) * 0.5
    # Удары в створ (максимум 5)
    rating += min(stat.shots_on_target, 5) * 0.2
    # Отборы (максимум 5)
    rating += min(stat.tackles, 5) * 0.15
    # Точность паса (0.0–1.0)
    if stat.passes_total > 0:
        accuracy = stat.passes_accurate / stat.passes_total
        rating += accuracy * 1.5
    # Потери (максимум 5)
    rating -= min(stat.losses, 5) * 0.15
    # Карточки
    rating -= stat.yellow_cards * 0.5
    rating -= stat.red_cards * 2.0

    # Обрезаем до диапазона 1.0–10.0
    rating = max(1.0, min(10.0, rating))
    return round(rating, 1)


# ─── SPA SHELL ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ─── API: АВТОРИЗАЦИЯ ─────────────────────────────────────────────────────────

@app.route('/api/vk-auth', methods=['POST'])
def api_vk_auth():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data'}), 400
        vk_id = data.get('vk_id')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        photo = data.get('photo', '')
        if not vk_id or not first_name:
            return jsonify({'error': 'Missing fields'}), 400
        user = User.query.filter_by(vk_id=vk_id).first()
        if not user:
            user = User(vk_id=vk_id, first_name=first_name, last_name=last_name, photo_url=photo)
            db.session.add(user)
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.photo_url = photo
        db.session.commit()
        session['user_id'] = user.id
        session.pop('current_team_id', None)
        session.modified = True
        user_teams = UserTeam.query.filter_by(user_id=user.id).all()
        teams = []
        for ut in user_teams:
            team = db.session.get(Team, ut.team_id)
            if team:
                teams.append({'id': team.id, 'name': team.name, 'city': team.city, 'role': ut.role})
        return jsonify({'id': user.id, 'first_name': user.first_name, 'last_name': user.last_name, 'teams': teams})
    except Exception as e:
        app.logger.error(f"vk_auth error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/select-team', methods=['POST'])
def api_select_team():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json()
    team_id = data.get('team_id')
    ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
    if not ut:
        return jsonify({'error': 'Вы не состоите в этой команде'}), 403
    session['current_team_id'] = team_id
    session.modified = True
    return jsonify({'success': True, 'role': ut.role, 'team_id': team_id})


@app.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/leave-team', methods=['POST'])
def api_leave_team():
    session.pop('current_team_id', None)
    session.modified = True
    return jsonify({'success': True})


@app.route('/api/quit-team', methods=['POST'])
def api_quit_team():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        data = request.get_json()
        team_id = data.get('team_id') or get_current_team_id()
        if not team_id:
            return jsonify({'error': 'team_id не указан'}), 400
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
        if not ut:
            return jsonify({'error': 'Вы не состоите в этой команде'}), 404
        db.session.delete(ut)
        db.session.commit()
        session.pop('current_team_id', None)
        session.modified = True
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/create-team', methods=['POST'])
def api_create_team():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        data = request.get_json()
        join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        team = Team(
            name=data['team_name'],
            city=data.get('city', ''),
            join_code=join_code,
            stats_level=data.get('stats_level', 'basic')
        )
        db.session.add(team)
        db.session.flush()
        ut = UserTeam(user_id=user.id, team_id=team.id, role='coach')
        db.session.add(ut)
        db.session.commit()
        session['current_team_id'] = team.id
        session.modified = True
        return jsonify({'success': True, 'team_id': team.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/set-stats-level', methods=['POST'])
def api_set_stats_level():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        data = request.get_json()
        team_id = data.get('team_id') or get_current_team_id()
        stats_level = data.get('stats_level', 'basic')
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
        if not ut:
            return jsonify({'error': 'Только тренер может менять тариф'}), 403
        team = db.session.get(Team, team_id)
        if not team:
            return jsonify({'error': 'Команда не найдена'}), 404
        team.stats_level = stats_level
        db.session.commit()
        return jsonify({'success': True, 'stats_level': stats_level})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/join-team', methods=['POST'])
def api_join_team():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        data = request.get_json()
        join_code = data.get('join_code', '').upper().strip()
        team = Team.query.filter_by(join_code=join_code).first()
        if not team:
            return jsonify({'error': 'Команда с таким кодом не найдена'}), 404
        existing = UserTeam.query.filter_by(user_id=user.id, team_id=team.id).first()
        if existing:
            session['current_team_id'] = team.id
            session.modified = True
            return jsonify({'success': True, 'team_id': team.id, 'already_member': True})
        ut = UserTeam(user_id=user.id, team_id=team.id, role='player')
        db.session.add(ut)
        db.session.commit()
        session['current_team_id'] = team.id
        session.modified = True
        return jsonify({'success': True, 'team_id': team.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/add-event', methods=['POST'])
def api_add_event():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 403
    team_id = get_current_team_id()
    ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
    if not ut or ut.role != 'coach':
        return jsonify({'error': 'unauthorized'}), 403
    try:
        data = request.get_json()
        event = Event(
            team_id=team_id,
            title=data['title'],
            event_date=datetime.fromisoformat(data['event_date']),
            event_type=data['event_type'],
            location=data.get('location', '')
        )
        db.session.add(event)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-stats', methods=['POST'])
def api_save_stats():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    team_id = get_current_team_id()
    ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
    if not ut:
        return jsonify({'error': 'Только тренер может вносить статистику'}), 403
    try:
        data = request.get_json()
        event_id = data.get('event_id')
        player_id = data.get('player_id')
        stats = data.get('stats', {})

        team = db.session.get(Team, team_id)
        stats_level = team.stats_level if team else 'basic'

        stat = MatchStat.query.filter_by(player_id=player_id, event_id=event_id).first()
        if not stat:
            stat = MatchStat(player_id=player_id, event_id=event_id)
            db.session.add(stat)

        stat.goals = stats.get('goals', 0)
        stat.assists = stats.get('assists', 0)
        stat.yellow_cards = stats.get('yellow_cards', 0)
        stat.red_cards = stats.get('red_cards', 0)
        stat.minutes_played = stats.get('minutes_played', 0)
        stat.shots_total = stats.get('shots_total', 0)
        stat.shots_on_target = stats.get('shots_on_target', 0)
        stat.passes_total = stats.get('passes_total', 0)
        stat.passes_accurate = stats.get('passes_accurate', 0)
        stat.tackles = stats.get('tackles', 0)
        stat.losses = stats.get('losses', 0)

        # Рейтинг только для детального тарифа — считается автоматически
        stat.rating = calculate_rating(stat, stats_level) or 0

        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/fragment', methods=['POST'])
def api_fragment():
    body = request.get_json() or {}
    route = body.get('route', '/')
    user = get_user()

    app.logger.debug(f"Fragment: route={route}, user={user.id if user else None}")

    if route == '/':
        return jsonify({'html': render_template('fragments/auth.html'), 'data': {}})

    if not user:
        return jsonify({'redirect': '/'})

    if route == '/select-team':
        user_teams = UserTeam.query.filter_by(user_id=user.id).all()
        teams = []
        for ut in user_teams:
            team = db.session.get(Team, ut.team_id)
            if team:
                teams.append({'id': team.id, 'name': team.name, 'city': team.city, 'role': ut.role})
        return jsonify({
            'html': render_template('fragments/select_team.html'),
            'data': {'first_name': user.first_name, 'teams': teams}
        })

    if route == '/create-team':
        return jsonify({'html': render_template('fragments/create_team.html'), 'data': {}})

    if route == '/join-team':
        return jsonify({'html': render_template('fragments/join_team.html'), 'data': {}})

    if route == '/select-stats':
        return jsonify({'html': render_template('fragments/select_stats.html'), 'data': {}})

    if route == '/event-detail':
        event_id = body.get('event_id')
        if not event_id:
            return jsonify({'redirect': '/dashboard'})
        event = db.session.get(Event, int(event_id))
        if not event:
            return jsonify({'redirect': '/dashboard'})
        team_id = get_current_team_id()
        team = db.session.get(Team, team_id)
        members = UserTeam.query.filter_by(team_id=team_id, role='player').all()
        players = []
        for m in members:
            p = db.session.get(User, m.user_id)
            if p:
                existing = MatchStat.query.filter_by(player_id=p.id, event_id=event_id).first()
                players.append({
                    'id': p.id,
                    'first_name': p.first_name,
                    'last_name': p.last_name,
                    'has_stats': existing is not None
                })
        return jsonify({
            'html': render_template('fragments/event_detail.html'),
            'data': {
                'event': {
                    'id': event.id, 'title': event.title,
                    'event_date': event.event_date.strftime('%d.%m.%Y %H:%M'),
                    'event_type': event.event_type, 'location': event.location
                },
                'players': players,
                'stats_level': team.stats_level if team else 'basic'
            }
        })

    if route == '/edit-stats':
        event_id = body.get('event_id')
        player_id = body.get('player_id')
        player_name = body.get('player_name', '')
        stats_level = body.get('stats_level', 'basic')
        existing_stats = {}
        if event_id and player_id:
            stat = MatchStat.query.filter_by(player_id=int(player_id), event_id=int(event_id)).first()
            if stat:
                existing_stats = {
                    'goals': stat.goals, 'assists': stat.assists,
                    'yellow_cards': stat.yellow_cards, 'red_cards': stat.red_cards,
                    'minutes_played': stat.minutes_played,
                    'shots_total': stat.shots_total, 'shots_on_target': stat.shots_on_target,
                    'passes_total': stat.passes_total, 'passes_accurate': stat.passes_accurate,
                    'tackles': stat.tackles, 'losses': stat.losses
                }
        event = db.session.get(Event, int(event_id)) if event_id else None
        return jsonify({
            'html': render_template('fragments/edit_stats.html'),
            'data': {
                'event_id': event_id,
                'event_title': event.title if event else '',
                'player_id': player_id,
                'player_name': player_name,
                'stats_level': stats_level,
                'existing_stats': existing_stats
            }
        })

    if route == '/dashboard':
        team_id = get_current_team_id()
        if not team_id:
            return jsonify({'redirect': '/select-team'})
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
        if not ut:
            return jsonify({'redirect': '/select-team'})
        team = db.session.get(Team, team_id)
        events = Event.query.filter_by(team_id=team_id).order_by(Event.event_date).all()

        if ut.role == 'coach':
            members = UserTeam.query.filter_by(team_id=team_id, role='player').all()
            players = []
            for m in members:
                p = db.session.get(User, m.user_id)
                if p:
                    players.append({'id': p.id, 'first_name': p.first_name, 'last_name': p.last_name})
            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {
                    'id': team.id, 'name': team.name,
                    'join_code': team.join_code, 'city': team.city,
                    'stats_level': team.stats_level
                } if team else None,
                'events': [{'id': e.id, 'title': e.title, 'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'), 'event_type': e.event_type, 'location': e.location} for e in events],
                'players': players
            }
            return jsonify({'html': render_template('fragments/coach_dashboard.html'), 'data': data})
        else:
            my_stats = MatchStat.query.filter_by(player_id=user.id).all()
            total_stats = {
                'games': len(set(s.event_id for s in my_stats)),
                'goals': sum(s.goals for s in my_stats),
                'assists': sum(s.assists for s in my_stats),
                'yellow_cards': sum(s.yellow_cards for s in my_stats),
                'red_cards': sum(s.red_cards for s in my_stats),
                'pass_accuracy': 0
            }
            total_passes = sum(s.passes_total for s in my_stats)
            accurate_passes = sum(s.passes_accurate for s in my_stats)
            if total_passes > 0:
                total_stats['pass_accuracy'] = round(accurate_passes / total_passes * 100)

            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {'name': team.name, 'stats_level': team.stats_level} if team else None,
                'events': [{'id': e.id, 'title': e.title, 'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'), 'event_type': e.event_type, 'location': e.location} for e in events],
                'stats': total_stats
            }
            return jsonify({'html': render_template('fragments/player_dashboard.html'), 'data': data})

    return jsonify({'error': 'Not found'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)