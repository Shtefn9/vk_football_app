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


# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────────────────────

def get_user():
    """Получаем пользователя из сессии или из uid в теле запроса"""
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
    """Получаем выбранную команду из сессии или из тела запроса"""
    team_id = session.get('current_team_id')
    if not team_id:
        body = request.get_json(silent=True) or {}
        team_id = body.get('team_id')
    return int(team_id) if team_id else None


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
            user = User(vk_id=vk_id, first_name=first_name,
                        last_name=last_name, photo_url=photo)
            db.session.add(user)
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.photo_url = photo
        db.session.commit()

        session['user_id'] = user.id
        session.pop('current_team_id', None)  # сбрасываем выбранную команду
        session.modified = True

        # Получаем все команды пользователя
        user_teams = UserTeam.query.filter_by(user_id=user.id).all()
        teams = []
        for ut in user_teams:
            team = db.session.get(Team, ut.team_id)
            if team:
                teams.append({
                    'id': team.id,
                    'name': team.name,
                    'city': team.city,
                    'role': ut.role
                })

        app.logger.debug(f"VK auth OK: user_id={user.id}, teams={len(teams)}")

        return jsonify({
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'teams': teams
        })
    except Exception as e:
        app.logger.error(f"vk_auth error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/select-team', methods=['POST'])
def api_select_team():
    """Выбор активной команды"""
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json()
    team_id = data.get('team_id')

    # Проверяем что пользователь состоит в этой команде
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
    """Покинуть текущую команду (вернуться к выбору)"""
    session.pop('current_team_id', None)
    session.modified = True
    return jsonify({'success': True})


# ─── API: КОМАНДЫ ─────────────────────────────────────────────────────────────

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
            stats_level='minimal'
        )
        db.session.add(team)
        db.session.flush()

        # Добавляем пользователя как тренера
        ut = UserTeam(user_id=user.id, team_id=team.id, role='coach')
        db.session.add(ut)
        db.session.commit()

        session['current_team_id'] = team.id
        session.modified = True

        return jsonify({'success': True, 'team_id': team.id})
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

        # Проверяем не состоит ли уже
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


# ─── API: ФРАГМЕНТЫ ───────────────────────────────────────────────────────────

@app.route('/api/fragment', methods=['POST'])
def api_fragment():
    body = request.get_json() or {}
    route = body.get('route', '/')
    user = get_user()

    app.logger.debug(f"Fragment: route={route}, user={user.id if user else None}")

    # Авторизация
    if route == '/':
        return jsonify({
            'html': render_template('fragments/auth.html'),
            'data': {}
        })

    if not user:
        return jsonify({'redirect': '/'})

    # Выбор команды
    if route == '/select-team':
        user_teams = UserTeam.query.filter_by(user_id=user.id).all()
        teams = []
        for ut in user_teams:
            team = db.session.get(Team, ut.team_id)
            if team:
                teams.append({
                    'id': team.id,
                    'name': team.name,
                    'city': team.city,
                    'role': ut.role
                })
        return jsonify({
            'html': render_template('fragments/select_team.html'),
            'data': {
                'first_name': user.first_name,
                'teams': teams
            }
        })

    # Создание команды
    if route == '/create-team':
        return jsonify({
            'html': render_template('fragments/create_team.html'),
            'data': {}
        })

    # Вступление в команду
    if route == '/join-team':
        return jsonify({
            'html': render_template('fragments/join_team.html'),
            'data': {}
        })

    # Дашборд — требует выбранной команды
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
                    'id': team.id,
                    'name': team.name,
                    'join_code': team.join_code,
                    'city': team.city
                } if team else None,
                'events': [{
                    'id': e.id, 'title': e.title,
                    'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                    'event_type': e.event_type, 'location': e.location
                } for e in events],
                'players': players
            }
            return jsonify({
                'html': render_template('fragments/coach_dashboard.html'),
                'data': data
            })
        else:
            my_stats = MatchStat.query.filter_by(player_id=user.id).all()
            total_stats = {
                'games': len(set(s.event_id for s in my_stats)),
                'goals': sum(s.goals for s in my_stats),
                'assists': sum(s.assists for s in my_stats),
                'pass_accuracy': 0
            }
            total_passes = sum(s.passes_total for s in my_stats)
            accurate_passes = sum(s.passes_accurate for s in my_stats)
            if total_passes > 0:
                total_stats['pass_accuracy'] = round(accurate_passes / total_passes * 100)

            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {'name': team.name} if team else None,
                'events': [{
                    'id': e.id, 'title': e.title,
                    'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                    'event_type': e.event_type, 'location': e.location
                } for e in events],
                'stats': total_stats
            }
            return jsonify({
                'html': render_template('fragments/player_dashboard.html'),
                'data': data
            })

    return jsonify({'error': 'Not found'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)