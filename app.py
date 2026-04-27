from flask import Flask, render_template, request, session, redirect, url_for, jsonify
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
def add_header(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def get_user_id():
    """Получаем user_id из сессии, затем из ?uid= в URL, затем из формы"""
    if session.get('user_id'):
        return session['user_id']
    uid = request.args.get('uid') or request.form.get('uid')
    if uid:
        try:
            return int(uid)
        except (ValueError, TypeError):
            return None
    return None


def load_session(user_id):
    """Загружаем пользователя из БД и заполняем сессию"""
    user = db.session.get(User, user_id)
    if user:
        session['user_id'] = user.id
        session['vk_id'] = user.vk_id
        session['name'] = f'{user.first_name} {user.last_name}'
        session['role'] = user.role
        session['team_id'] = user.team_id
        session.modified = True
        app.logger.debug(f"Session loaded: user_id={user.id}, role={user.role}, team_id={user.team_id}")
    return user


# ─── МАРШРУТЫ ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    user_id = get_user_id()
    if user_id:
        user = load_session(user_id)
        if user:
            if user.team_id:
                return redirect(f'/dashboard?uid={user_id}')
            else:
                return redirect(f'/start?uid={user_id}')
    return render_template('vk_auth.html')


@app.route('/vk-auth', methods=['POST'])
def vk_auth():
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
            user = User(
                vk_id=vk_id,
                first_name=first_name,
                last_name=last_name,
                photo_url=photo,
                role='player',
                team_id=None
            )
            db.session.add(user)
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.photo_url = photo
        db.session.commit()

        load_session(user.id)
        app.logger.debug(f"VK auth OK: user_id={user.id}")

        return jsonify({
            'status': 'ok',
            'user_id': user.id,
            'first_name': first_name,
            'last_name': last_name,
            'role': user.role,
            'has_team': user.team_id is not None
        })
    except Exception as e:
        app.logger.error(f"vk_auth error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/test-login', methods=['POST'])
def test_login():
    try:
        vk_id = int(request.form['vk_id'])
        first_name = request.form['first_name']
        last_name = request.form['last_name']

        user = User.query.filter_by(vk_id=vk_id).first()
        if not user:
            user = User(vk_id=vk_id, first_name=first_name,
                        last_name=last_name, photo_url='', role='player', team_id=None)
            db.session.add(user)
            db.session.commit()

        load_session(user.id)
        return redirect(f'/start?uid={user.id}')
    except Exception as e:
        app.logger.error(f"test_login error: {e}")
        db.session.rollback()
        return f"Ошибка входа: {e}", 500


@app.route('/start')
def start():
    user_id = get_user_id()
    if not user_id:
        app.logger.debug("start(): нет user_id → index")
        return redirect(url_for('index'))
    user = load_session(user_id)
    if not user:
        return redirect(url_for('index'))
    # Если у пользователя уже есть команда — сразу в дашборд
    if user.team_id:
        app.logger.debug(f"start(): user уже в команде → dashboard")
        return redirect(f'/dashboard?uid={user_id}')
    app.logger.debug(f"start() OK: user_id={user_id}")
    return render_template('start.html', uid=user_id)


@app.route('/create-team', methods=['GET', 'POST'])
def create_team():
    user_id = get_user_id()
    if not user_id:
        return redirect(url_for('index'))
    load_session(user_id)

    if request.method == 'GET':
        return render_template('create_team.html', uid=user_id)

    try:
        team_name = request.form['team_name']
        city = request.form.get('city', '')
        join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

        team = Team(name=team_name, city=city, coach_id=user_id,
                    join_code=join_code, stats_level='minimal')
        db.session.add(team)
        db.session.flush()

        user = db.session.get(User, user_id)
        user.team_id = team.id
        user.role = 'coach'
        db.session.commit()

        app.logger.debug(f"Team created: id={team.id}, coach={user_id}")

        load_session(user_id)
        return redirect(f'/dashboard?uid={user_id}')
    except Exception as e:
        app.logger.error(f"create_team error: {e}")
        db.session.rollback()
        return render_template('create_team.html', uid=user_id, error=f'Ошибка: {str(e)}')


@app.route('/join-team', methods=['GET', 'POST'])
def join_team():
    user_id = get_user_id()
    if not user_id:
        return redirect(url_for('index'))
    load_session(user_id)

    if request.method == 'GET':
        return render_template('join_team.html', uid=user_id)

    try:
        join_code = request.form['join_code'].upper().strip()
        team = Team.query.filter_by(join_code=join_code).first()
        if not team:
            return render_template('join_team.html', uid=user_id,
                                   error='Команда с таким кодом не найдена')

        user = db.session.get(User, user_id)
        user.team_id = team.id
        user.role = 'player'
        db.session.commit()

        app.logger.debug(f"User {user_id} joined team {team.id}")

        load_session(user_id)
        return redirect(f'/dashboard?uid={user_id}')
    except Exception as e:
        app.logger.error(f"join_team error: {e}")
        db.session.rollback()
        return render_template('join_team.html', uid=user_id, error=f'Ошибка: {str(e)}')


@app.route('/dashboard')
def dashboard():
    user_id = get_user_id()
    if not user_id:
        app.logger.debug("dashboard(): нет user_id → index")
        return redirect(url_for('index'))

    user = load_session(user_id)
    if not user:
        return redirect(url_for('index'))

    # Берём актуальные данные из БД, не из сессии
    team_id = user.team_id
    role = user.role

    app.logger.debug(f"dashboard(): user_id={user_id}, role={role}, team_id={team_id}")

    team = db.session.get(Team, team_id) if team_id else None
    events = []
    if team:
        events = Event.query.filter_by(team_id=team_id).order_by(Event.event_date).all()

    if role == 'coach':
        players = User.query.filter_by(team_id=team_id, role='player').all() if team else []
        return render_template('coach_dashboard.html',
                               user=user, team=team, events=events,
                               players=players, uid=user_id)
    else:
        my_stats = MatchStat.query.filter_by(player_id=user_id).all()
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

        return render_template('player_dashboard.html',
                               user=user, team=team, events=events,
                               stats=total_stats, uid=user_id)


@app.route('/add-event', methods=['POST'])
def add_event():
    user_id = get_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    user = load_session(user_id)
    if not user or user.role != 'coach':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        team_id = user.team_id
        title = request.form['title']
        event_date = request.form['event_date']
        event_type = request.form['event_type']
        location = request.form.get('location', '')

        event = Event(
            team_id=team_id,
            title=title,
            event_date=datetime.strptime(event_date, '%Y-%m-%dT%H:%M'),
            event_type=event_type,
            location=location
        )
        db.session.add(event)
        db.session.commit()
        app.logger.debug(f"Event added: {title}")
    except Exception as e:
        app.logger.error(f"add_event error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return redirect(f'/dashboard?uid={user_id}')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)