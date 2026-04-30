from flask import Flask, render_template, request, session, jsonify
from database import db, init_db
from models import User, Team, Event, MatchStat
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
        # Обновляем сессию
        session['user_id'] = user.id
        session.modified = True
    return user


# ─── ЕДИНСТВЕННАЯ СТРАНИЦА (SPA shell) ───────────────────────────────────────

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
                        last_name=last_name, photo_url=photo,
                        role='player', team_id=None)
            db.session.add(user)
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.photo_url = photo
        db.session.commit()

        session['user_id'] = user.id
        session.modified = True
        app.logger.debug(f"VK auth OK: user_id={user.id}")

        return jsonify({
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'team_id': user.team_id
        })
    except Exception as e:
        app.logger.error(f"vk_auth error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/logout')
def api_logout():
    session.clear()
    return jsonify({'success': True})


# ─── API: ДАННЫЕ ──────────────────────────────────────────────────────────────

@app.route('/api/user', methods=['GET', 'POST'])
def api_user():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify({
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'team_id': user.team_id
    })


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
            coach_id=user.id,
            join_code=join_code,
            stats_level='minimal'
        )
        db.session.add(team)
        db.session.flush()

        user.team_id = team.id
        user.role = 'coach'
        db.session.commit()

        session['team_id'] = team.id
        session['role'] = 'coach'
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

        user.team_id = team.id
        user.role = 'player'
        db.session.commit()

        session['team_id'] = team.id
        session['role'] = 'player'
        session.modified = True

        return jsonify({'success': True, 'team_id': team.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/add-event', methods=['POST'])
def api_add_event():
    user = get_user()
    if not user or user.role != 'coach':
        return jsonify({'error': 'unauthorized'}), 403

    try:
        data = request.get_json()
        event = Event(
            team_id=user.team_id,
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

    if route == '/':
        return jsonify({
            'html': render_template('fragments/auth.html'),
            'data': {}
        })

    if not user:
        return jsonify({'redirect': '/'})

    if route == '/start':
        if user.team_id:
            return jsonify({'redirect': '/dashboard'})
        return jsonify({
            'html': render_template('fragments/start.html'),
            'data': {'first_name': user.first_name}
        })

    if route == '/create-team':
        return jsonify({
            'html': render_template('fragments/create_team.html'),
            'data': {}
        })

    if route == '/join-team':
        return jsonify({
            'html': render_template('fragments/join_team.html'),
            'data': {}
        })

    if route == '/dashboard':
        team = db.session.get(Team, user.team_id) if user.team_id else None
        events = []
        if user.team_id:
            events = Event.query.filter_by(team_id=user.team_id).order_by(Event.event_date).all()

        if user.role == 'coach':
            players = User.query.filter_by(team_id=user.team_id, role='player').all() if user.team_id else []
            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {
                    'id': team.id,
                    'name': team.name,
                    'join_code': team.join_code,
                    'city': team.city
                } if team else None,
                'events': [{
                    'id': e.id,
                    'title': e.title,
                    'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                    'event_type': e.event_type,
                    'location': e.location
                } for e in events],
                'players': [{
                    'id': p.id,
                    'first_name': p.first_name,
                    'last_name': p.last_name
                } for p in players]
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
                    'id': e.id,
                    'title': e.title,
                    'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                    'event_type': e.event_type,
                    'location': e.location
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