from flask import Flask, render_template, request, session, jsonify, redirect
from database import db, init_db
from models import User, Team, UserTeam, Event, MatchStat, EventAttendance
import random
import string
import logging
import os
import uuid
import re
import hmac
import hashlib
import base64
from urllib.parse import parse_qsl, urlencode
from datetime import datetime, timedelta, timezone
from yookassa import Configuration, Payment

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'football.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'vk_football_secret_2024'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ЮКасса
YOOKASSA_SHOP_ID = os.environ.get('YOOKASSA_SHOP_ID', '1365798')
YOOKASSA_SECRET_KEY = os.environ.get('YOOKASSA_SECRET_KEY', '')
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

# Секретный ключ VK Mini App
VK_SECURE_KEY = os.environ.get('VK_SECURE_KEY', '')

BASE_URL = os.environ.get('BASE_URL', 'https://vk-football-app-vyn4-production.up.railway.app')

# Регулярка для опасных символов
DANGEROUS_PATTERN = re.compile(r'[<>]')


def is_safe_text(text):
    """Проверяет что в тексте нет HTML-тегов или подозрительных символов"""
    if not text:
        return True
    return not DANGEROUS_PATTERN.search(text)


init_db(app)


@app.after_request
def add_headers(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Access-Control-Allow-Origin'] = '*'
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    else:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def verify_vk_launch_params(launch_params_str):
    """Проверяет HMAC-подпись параметров запуска VK Mini App."""
    if not VK_SECURE_KEY or not launch_params_str:
        return None
    try:
        params = dict(parse_qsl(launch_params_str, keep_blank_values=True))
        sign = params.pop('sign', None)
        if not sign:
            return None
        vk_params = {k: v for k, v in params.items() if k.startswith('vk_')}
        if not vk_params:
            return None
        sorted_params = sorted(vk_params.items())
        query_string = urlencode(sorted_params)
        digest = hmac.new(
            VK_SECURE_KEY.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).digest()
        expected_sign = base64.urlsafe_b64encode(digest).decode('utf-8').rstrip('=')
        if expected_sign != sign:
            app.logger.warning(f"VK sign mismatch")
            return None
        vk_user_id = vk_params.get('vk_user_id')
        return int(vk_user_id) if vk_user_id else None
    except Exception as e:
        app.logger.error(f"verify_vk_launch_params error: {e}")
        return None


def get_user():
    body = request.get_json(silent=True) or {}
    launch_params = body.get('vk_launch_params')

    if launch_params:
        vk_user_id = verify_vk_launch_params(launch_params)
        if vk_user_id:
            user = User.query.filter_by(vk_id=vk_user_id).first()
            if user:
                session['user_id'] = user.id
                session.modified = True
                return user
            return None

    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            return user
    return None


def get_current_team_id():
    team_id = session.get('current_team_id')
    if not team_id:
        body = request.get_json(silent=True) or {}
        team_id = body.get('team_id')
    return int(team_id) if team_id else None


def is_trial_active(team):
    if not team or not team.trial_until:
        return False
    return datetime.now() < team.trial_until


def calculate_rating(stat, position, stats_level):
    if stats_level != 'detailed':
        return 0.0
    if position == 'goalkeeper':
        total = stat.saves + stat.goals_conceded
        save_pct = stat.saves / total if total > 0 else 0.0
        rating = save_pct * 9.0
        if stat.goals_conceded == 0:
            rating += 1.0
        rating -= min(stat.gk_losses, 7) * 0.2
        if stat.gk_passes_total > 0:
            rating += (stat.gk_passes_accurate / stat.gk_passes_total) * 0.5
        if stat.goal_kicks_total > 0:
            rating += (stat.goal_kicks_accurate / stat.goal_kicks_total) * 0.3
    else:
        rating = 5.0
        rating += min(stat.goals, 3) * 1.0
        rating += min(stat.assists, 3) * 0.5
        rating += min(stat.shots_on_target, 5) * 0.2
        rating += min(stat.tackles, 5) * 0.15
        if stat.passes_total > 0:
            rating += (stat.passes_accurate / stat.passes_total) * 1.5
        rating -= min(stat.losses, 5) * 0.15
        rating -= stat.yellow_cards * 0.5
        rating -= stat.red_cards * 2.0
    return round(max(1.0, min(10.0, rating)), 1)


def generate_advice(stats_list, position):
    if not stats_list:
        return []
    games = len(stats_list)
    advice = []
    total_goals = sum(s.goals for s in stats_list)
    total_assists = sum(s.assists for s in stats_list)
    total_yellow = sum(s.yellow_cards for s in stats_list)
    total_red = sum(s.red_cards for s in stats_list)
    avg_goals = total_goals / games
    avg_assists = total_assists / games

    if position == 'forward':
        if total_goals == 0:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Ты ещё не открыл счёт в этом сезоне. Попробуй чаще смещаться в зону удара и не жди идеального момента — бей из любой удобной позиции.'})
        elif avg_goals < 0.2:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Голов пока мало. Анализируй где ты находишься в момент завершения атаки — скорее всего ты слишком далеко от ворот.'})
        elif avg_goals < 0.4:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Забиваешь стабильно но нечасто. Попробуй замыкать передачи с флангов — это увеличит количество ударов.'})
        elif avg_goals < 0.7:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Хорошая результативность. Старайся сохранять этот уровень и ищи моменты для удара с первого касания.'})
        else:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Ты один из лучших бомбардиров! Поддерживай форму и продолжай открываться за спину защитникам.'})

        total_shots = sum(s.shots_total for s in stats_list)
        total_on_target = sum(s.shots_on_target for s in stats_list)
        if total_shots > 0:
            shot_pct = total_on_target / total_shots * 100
            if shot_pct < 25:
                advice.append({'icon': '🎯', 'title': 'Удары', 'text': 'Большинство ударов проходит мимо. Не торопись — сделай шаг для баланса перед ударом и целься в нижние углы.'})
            elif shot_pct < 50:
                advice.append({'icon': '🎯', 'title': 'Удары', 'text': 'Точность ударов средняя. На тренировках отрабатывай удары с разных позиций штрафной зоны.'})
            else:
                advice.append({'icon': '🎯', 'title': 'Удары', 'text': 'Хорошая точность ударов! Теперь работай над силой удара чтобы вратарю было сложнее отбить.'})

        if total_assists == 0:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Ни одной голевой передачи. Чаще смотри по сторонам перед ударом — возможно партнёр стоит в лучшей позиции.'})
        elif avg_assists < 0.2:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Мало голевых передач. Развивай периферийное зрение — замечай открытых партнёров в штрафной.'})
        else:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Хорошее взаимодействие с партнёрами! Продолжай искать открытых игроков в опасных зонах.'})

        total_losses = sum(s.losses for s in stats_list)
        avg_losses = total_losses / games
        if avg_losses > 5:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Очень много потерь. В сложных ситуациях упрощай игру — лучше отдай назад чем потерять мяч в опасной зоне.'})
        elif avg_losses > 3:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Есть потери. Работай над укрыванием мяча корпусом под давлением защитника.'})
        else:
            advice.append({'icon': '✅', 'title': 'Потери', 'text': 'Хороший контроль мяча! Продолжай играть уверенно под давлением.'})

        total_passes = sum(s.passes_total for s in stats_list)
        accurate_passes = sum(s.passes_accurate for s in stats_list)
        if total_passes > 0:
            pass_pct = accurate_passes / total_passes * 100
            if pass_pct < 60:
                advice.append({'icon': '📊', 'title': 'Точность паса', 'text': 'Низкая точность паса. Начни с простых коротких передач — не рискуй длинными пасами в своей половине поля.'})
            elif pass_pct < 75:
                advice.append({'icon': '📊', 'title': 'Точность паса', 'text': 'Средняя точность паса. Перед передачей убедись что видишь партнёра — не отдавай вслепую.'})
            else:
                advice.append({'icon': '📊', 'title': 'Точность паса', 'text': 'Хорошая точность паса! Можешь пробовать более сложные передачи между линиями.'})

    elif position == 'defender':
        total_tackles = sum(s.tackles for s in stats_list)
        avg_tackles = total_tackles / games
        if avg_tackles == 0:
            advice.append({'icon': '🛡', 'title': 'Отборы', 'text': 'Ни одного отбора. Работай над выбором момента — не прыгай сразу, жди когда соперник примет мяч.'})
        elif avg_tackles < 1:
            advice.append({'icon': '🛡', 'title': 'Отборы', 'text': 'Мало отборов. Старайся занимать правильную позицию между мячом и воротами.'})
        elif avg_tackles <= 3:
            advice.append({'icon': '🛡', 'title': 'Отборы', 'text': 'Хорошее давление на соперника. Продолжай работать над позиционной защитой.'})
        else:
            advice.append({'icon': '🛡', 'title': 'Отборы', 'text': 'Отличная игра в отборе! Следи чтобы не получать карточки за грубые фолы.'})

        total_losses = sum(s.losses for s in stats_list)
        avg_losses = total_losses / games
        if avg_losses > 4:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Очень много потерь для защитника. В своей зоне играй проще — не рискуй с обводкой, отдавай мяч вратарю или назад.'})
        elif avg_losses > 2:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Есть потери в защите. Под давлением соперника не задерживай мяч — принимай решение быстрее.'})
        else:
            advice.append({'icon': '✅', 'title': 'Потери', 'text': 'Надёжный контроль мяча в защите! Продолжай играть уверенно.'})

        total_passes = sum(s.passes_total for s in stats_list)
        accurate_passes = sum(s.passes_accurate for s in stats_list)
        if total_passes > 0:
            pass_pct = accurate_passes / total_passes * 100
            if pass_pct < 65:
                advice.append({'icon': '📊', 'title': 'Точность паса', 'text': 'Низкая точность паса для защитника — это опасно. Играй проще, отдавай короткие передачи вратарю или партнёрам рядом.'})
            elif pass_pct < 80:
                advice.append({'icon': '📊', 'title': 'Точность паса', 'text': 'Средняя точность. Не торопись при розыгрыше от обороны — возьми время и найди свободного игрока.'})
            else:
                advice.append({'icon': '📊', 'title': 'Точность паса', 'text': 'Отличная точность паса! Ты надёжное звено в начале атак команды.'})

        if total_goals > 0:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Ты забил как защитник — отлично подключился в атаку! Главное не забывать возвращаться назад после атаки.'})
        if total_assists > 0:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Голевая передача от защитника — значит ты хорошо читаешь игру и вовремя подключаешься к атакам.'})
        if games > 0 and total_yellow / games > 0.3:
            advice.append({'icon': '🟨', 'title': 'Дисциплина', 'text': 'Слишком много жёлтых карточек. Учись встречать соперника корпусом а не ногой.'})
        if total_red > 0:
            advice.append({'icon': '🟥', 'title': 'Удаления', 'text': 'Удаление дорого обходится команде. Контролируй эмоции и никогда не иди в подкат сзади.'})

    elif position == 'goalkeeper':
        total_saves = sum(s.saves for s in stats_list)
        total_conceded = sum(s.goals_conceded for s in stats_list)
        if (total_saves + total_conceded) > 0:
            save_pct = total_saves / (total_saves + total_conceded) * 100
            if save_pct < 50:
                advice.append({'icon': '🧤', 'title': 'Сейвы', 'text': 'Меньше половины ударов отражено. Работай над стартовой позицией — стой ближе к центру ворот и не выходи слишком рано на удар.'})
            elif save_pct < 70:
                advice.append({'icon': '🧤', 'title': 'Сейвы', 'text': 'Средний процент сейвов. Тренируй реакцию на удары в углы — это самые сложные удары для вратаря.'})
            elif save_pct < 85:
                advice.append({'icon': '🧤', 'title': 'Сейвы', 'text': 'Хороший процент сейвов. Продолжай читать направление удара по замаху соперника.'})
            else:
                advice.append({'icon': '🧤', 'title': 'Сейвы', 'text': 'Отличная игра! Ты держишь команду в игре. Поддерживай концентрацию до финального свистка.'})

        avg_conceded = total_conceded / games
        if avg_conceded == 0:
            advice.append({'icon': '🏆', 'title': 'Сухие матчи', 'text': 'Не пропустил ни одного гола — лучший результат для вратаря! Продолжай держать концентрацию весь матч.'})
        elif avg_conceded <= 1:
            advice.append({'icon': '✅', 'title': 'Пропущенные голы', 'text': 'Один пропущенный гол за матч — нормальный результат. Анализируй где была ошибка в позиции.'})
        elif avg_conceded <= 3:
            advice.append({'icon': '⚠️', 'title': 'Пропущенные голы', 'text': 'Много пропускаешь. Разбери каждый гол — был ли ты на правильной позиции в момент удара.'})
        else:
            advice.append({'icon': '🔴', 'title': 'Пропущенные голы', 'text': 'Тяжёлые матчи. Поговори с тренером о позиционных ошибках и серьёзно работай над выбором позиции.'})

        total_passes = sum(s.gk_passes_total for s in stats_list)
        accurate_passes = sum(s.gk_passes_accurate for s in stats_list)
        if total_passes > 0:
            pass_pct = accurate_passes / total_passes * 100
            if pass_pct < 60:
                advice.append({'icon': '📊', 'title': 'Передачи', 'text': 'Низкая точность передач. Не рискуй длинными пасами — играй надёжно короткими передачами защитникам.'})
            elif pass_pct < 80:
                advice.append({'icon': '📊', 'title': 'Передачи', 'text': 'Средняя точность передач. Перед передачей убедись что партнёр открыт и готов принять мяч.'})
            else:
                advice.append({'icon': '📊', 'title': 'Передачи', 'text': 'Отличная точность передач! Ты хорошо начинаешь атаки команды.'})

        total_kicks = sum(s.goal_kicks_total for s in stats_list)
        accurate_kicks = sum(s.goal_kicks_accurate for s in stats_list)
        if total_kicks > 0:
            kick_pct = accurate_kicks / total_kicks * 100
            if kick_pct < 50:
                advice.append({'icon': '🦵', 'title': 'Вводы мяча', 'text': 'Большинство вводов теряется. Не бей наугад — ищи открытого игрока или выбивай мяч в угол поля.'})
            elif kick_pct < 75:
                advice.append({'icon': '🦵', 'title': 'Вводы мяча', 'text': 'Средняя точность вводов. Отрабатывай удар от ворот на тренировках — это важный элемент игры.'})
            else:
                advice.append({'icon': '🦵', 'title': 'Вводы мяча', 'text': 'Хорошая точность вводов! Ты эффективно начинаешь атаки от ворот.'})

        total_gk_losses = sum(s.gk_losses for s in stats_list)
        avg_gk_losses = total_gk_losses / games
        if avg_gk_losses > 3:
            advice.append({'icon': '🔴', 'title': 'Потери', 'text': 'Много потерь для вратаря — это очень опасно. В своей штрафной всегда играй надёжно и не рискуй с обводкой.'})
        elif avg_gk_losses > 1:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Есть потери. Вратарю нельзя рисковать с мячом в штрафной — играй проще.'})
        else:
            advice.append({'icon': '✅', 'title': 'Потери', 'text': 'Ни одной потери — отличная надёжность! Продолжай играть уверенно с мячом.'})

    return advice


# ─── SPA ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route('/api/vk-auth', methods=['POST'])
def api_vk_auth():
    try:
        body = request.get_json() or {}
        launch_params = body.get('vk_launch_params')
        vk_id = verify_vk_launch_params(launch_params)
        if not vk_id:
            return jsonify({'error': 'Invalid VK signature'}), 401

        first_name = (body.get('first_name') or '').strip()[:50]
        last_name = (body.get('last_name') or '').strip()[:50]
        photo = (body.get('photo') or '')[:500]
        if not first_name:
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


@app.route('/api/set-position', methods=['POST'])
def api_set_position():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    team_id = get_current_team_id()
    coach_ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
    if not coach_ut:
        return jsonify({'error': 'Только тренер может назначать позиции'}), 403
    try:
        data = request.get_json()
        player_id = data.get('player_id')
        position = data.get('position')
        if position not in ('goalkeeper', 'defender', 'forward'):
            return jsonify({'error': 'Неверная позиция'}), 400
        player_ut = UserTeam.query.filter_by(user_id=player_id, team_id=team_id).first()
        if not player_ut:
            return jsonify({'error': 'Игрок не найден'}), 404
        player_ut.position = position
        db.session.commit()
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
        team_name = (data.get('team_name') or '').strip()[:30]
        city = (data.get('city') or '').strip()[:30]
        if not team_name:
            return jsonify({'error': 'Название команды обязательно'}), 400
        if not is_safe_text(team_name) or not is_safe_text(city):
            return jsonify({'error': 'Недопустимые символы в названии или городе'}), 400
        join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        team = Team(name=team_name, city=city,
                    join_code=join_code, stats_level=data.get('stats_level', 'basic'))
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
        if stats_level not in ('basic', 'detailed'):
            return jsonify({'error': 'Неверный тариф'}), 400
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
        if not ut:
            return jsonify({'error': 'Только тренер может менять тариф'}), 403
        team = db.session.get(Team, team_id)
        if not team:
            return jsonify({'error': 'Команда не найдена'}), 404
        if stats_level == 'detailed':
            return jsonify({
                'error': 'Детальный тариф доступен только через пробный период или оплату подписки'
            }), 403
        team.stats_level = 'basic'
        db.session.commit()
        return jsonify({'success': True, 'stats_level': 'basic'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/start-trial', methods=['POST'])
def api_start_trial():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        team_id = get_current_team_id()
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
        if not ut:
            return jsonify({'error': 'Только тренер может активировать пробный период'}), 403
        team = db.session.get(Team, team_id)
        if not team:
            return jsonify({'error': 'Команда не найдена'}), 404
        if is_trial_active(team):
            return jsonify({'error': 'Пробный период уже активен'}), 400
        team.trial_until = datetime.now() + timedelta(days=7)
        db.session.commit()
        return jsonify({'success': True, 'trial_until': team.trial_until.strftime('%d.%m.%Y')})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/create-payment', methods=['POST'])
def api_create_payment():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        team_id = get_current_team_id()
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
        if not ut:
            return jsonify({'error': 'Только тренер может оплатить подписку'}), 403

        idempotence_key = str(uuid.uuid4())
        payment = Payment.create({
            'amount': {'value': '199.00', 'currency': 'RUB'},
            'confirmation': {
                'type': 'redirect',
                'return_url': f'{BASE_URL}/payment-success?team_id={team_id}&user_id={user.id}'
            },
            'capture': True,
            'description': f'Детальный тариф Well Played — 3 месяца (команда ID {team_id})',
            'metadata': {'team_id': str(team_id), 'user_id': str(user.id)}
        }, idempotence_key)

        return jsonify({
            'success': True,
            'payment_url': payment.confirmation.confirmation_url,
            'payment_id': payment.id
        })
    except Exception as e:
        app.logger.error(f"create_payment error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/payment-success')
def payment_success():
    team_id = request.args.get('team_id')
    user_id = request.args.get('user_id')
    if team_id and user_id:
        try:
            team = db.session.get(Team, int(team_id))
            if team:
                now = datetime.now()
                if team.subscription_until and team.subscription_until > now:
                    team.subscription_until = team.subscription_until + timedelta(days=90)
                else:
                    team.subscription_until = now + timedelta(days=90)
                team.stats_level = 'detailed'
                db.session.commit()
                app.logger.info(f"Subscription activated: team {team_id}, until {team.subscription_until}")
        except Exception as e:
            app.logger.error(f"payment_success error: {e}")
            db.session.rollback()
    return redirect(f'https://vk.com/app54481828')


@app.route('/api/subscribe', methods=['POST'])
def api_subscribe():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        team_id = get_current_team_id()
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
        if not ut:
            return jsonify({'error': 'Только тренер может активировать подписку'}), 403
        team = db.session.get(Team, team_id)
        if not team:
            return jsonify({'error': 'Команда не найдена'}), 404
        now = datetime.now()
        if team.subscription_until and team.subscription_until > now:
            team.subscription_until = team.subscription_until + timedelta(days=90)
        else:
            team.subscription_until = now + timedelta(days=90)
        team.stats_level = 'detailed'
        db.session.commit()
        return jsonify({'success': True, 'subscription_until': team.subscription_until.strftime('%d.%m.%Y')})
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
        join_code = (data.get('join_code') or '').upper().strip()[:10]
        if not join_code:
            return jsonify({'error': 'Введите код'}), 400
        team = Team.query.filter_by(join_code=join_code).first()
        if not team:
            return jsonify({'error': 'Команда с таким кодом не найдена'}), 404
        existing = UserTeam.query.filter_by(user_id=user.id, team_id=team.id).first()
        if existing:
            session['current_team_id'] = team.id
            session.modified = True
            return jsonify({'success': True, 'team_id': team.id})
        ut = UserTeam(user_id=user.id, team_id=team.id, role='player', position='forward')
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
        return jsonify({'error': 'unauthorized'}), 401
    team_id = get_current_team_id()
    ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first()
    if not ut:
        return jsonify({'error': 'Только тренер может добавлять события'}), 403
    try:
        data = request.get_json()
        title = (data.get('title') or '').strip()[:30]
        location = (data.get('location') or '').strip()[:30]
        event_type = data.get('event_type', 'training')
        if not title:
            return jsonify({'error': 'Название обязательно'}), 400
        if not is_safe_text(title) or not is_safe_text(location):
            return jsonify({'error': 'Недопустимые символы в названии или месте'}), 400
        if event_type not in ('match', 'training'):
            return jsonify({'error': 'Неверный тип события'}), 400

        # Валидация даты: формат, не в прошлом, не позже чем через неделю
        try:
            event_date = datetime.fromisoformat(data['event_date'])
        except (ValueError, TypeError, KeyError):
            return jsonify({'error': 'Неверный формат даты'}), 400

        now = datetime.now()
        max_allowed = now + timedelta(days=7)
        if event_date < now:
            return jsonify({'error': 'Дата события не может быть в прошлом'}), 400
        if event_date > max_allowed:
            return jsonify({'error': 'Дата события слишком далеко (максимум через неделю)'}), 400

        event = Event(team_id=team_id, title=title,
                      event_date=event_date,
                      event_type=event_type, location=location)
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

        event = db.session.get(Event, int(event_id)) if event_id else None
        if not event or event.team_id != team_id:
            return jsonify({'error': 'Событие не найдено в этой команде'}), 404

        player_ut = UserTeam.query.filter_by(user_id=player_id, team_id=team_id).first()
        if not player_ut:
            return jsonify({'error': 'Игрок не состоит в этой команде'}), 404

        team = db.session.get(Team, team_id)
        stats_level = team.effective_stats_level if team else 'basic'
        position = player_ut.position if player_ut else 'forward'
        stat = MatchStat.query.filter_by(player_id=player_id, event_id=event_id).first()
        if not stat:
            stat = MatchStat(player_id=player_id, event_id=event_id)
            db.session.add(stat)

        def safe_int(v, default=0):
            try:
                return max(0, int(v))
            except (ValueError, TypeError):
                return default

        stat.goals = safe_int(stats.get('goals'))
        stat.assists = safe_int(stats.get('assists'))
        stat.yellow_cards = safe_int(stats.get('yellow_cards'))
        stat.red_cards = safe_int(stats.get('red_cards'))
        stat.minutes_played = safe_int(stats.get('minutes_played'))
        if position == 'goalkeeper':
            stat.saves = safe_int(stats.get('saves'))
            stat.goals_conceded = safe_int(stats.get('goals_conceded'))
            stat.gk_passes_total = safe_int(stats.get('gk_passes_total'))
            stat.gk_passes_accurate = safe_int(stats.get('gk_passes_accurate'))
            stat.gk_losses = safe_int(stats.get('gk_losses'))
            stat.goal_kicks_total = safe_int(stats.get('goal_kicks_total'))
            stat.goal_kicks_accurate = safe_int(stats.get('goal_kicks_accurate'))
        else:
            stat.shots_total = safe_int(stats.get('shots_total'))
            stat.shots_on_target = safe_int(stats.get('shots_on_target'))
            stat.passes_total = safe_int(stats.get('passes_total'))
            stat.passes_accurate = safe_int(stats.get('passes_accurate'))
            stat.tackles = safe_int(stats.get('tackles'))
            stat.losses = safe_int(stats.get('losses'))
        stat.rating = calculate_rating(stat, position, stats_level)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/toggle-attendance', methods=['POST'])
def api_toggle_attendance():
    user = get_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        data = request.get_json()
        event_id = data.get('event_id')
        status = data.get('status')  # 'going' / 'not_going' / 'clear'
        reason = (data.get('reason') or '').strip()[:100]

        if not event_id:
            return jsonify({'error': 'event_id обязателен'}), 400
        if status not in ('going', 'not_going', 'clear'):
            return jsonify({'error': 'Неверный статус'}), 400

        event = db.session.get(Event, int(event_id))
        if not event:
            return jsonify({'error': 'Событие не найдено'}), 404

        ut = UserTeam.query.filter_by(user_id=user.id, team_id=event.team_id, role='player').first()
        if not ut:
            return jsonify({'error': 'Только игрок команды может отмечаться'}), 403

        if status == 'not_going' and not reason:
            return jsonify({'error': 'Укажите причину отказа'}), 400

        if not is_safe_text(reason):
            return jsonify({'error': 'Недопустимые символы в причине'}), 400

        attendance = EventAttendance.query.filter_by(event_id=event_id, user_id=user.id).first()

        if status == 'clear':
            if attendance:
                db.session.delete(attendance)
        else:
            if attendance:
                attendance.status = status
                attendance.reason = reason if status == 'not_going' else None
                attendance.updated_at = datetime.now()
            else:
                attendance = EventAttendance(
                    event_id=event_id,
                    user_id=user.id,
                    status=status,
                    reason=reason if status == 'not_going' else None
                )
                db.session.add(attendance)

        db.session.commit()
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/fragment', methods=['POST'])
def api_fragment():
    body = request.get_json() or {}
    route = body.get('route', '/')
    user = get_user()

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
        return jsonify({'html': render_template('fragments/select_team.html'),
                        'data': {'first_name': user.first_name, 'teams': teams}})

    if route == '/create-team':
        return jsonify({'html': render_template('fragments/create_team.html'), 'data': {}})

    if route == '/join-team':
        return jsonify({'html': render_template('fragments/join_team.html'), 'data': {}})

    if route == '/select-stats':
        team_id = get_current_team_id()
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id, role='coach').first() if team_id else None
        team = db.session.get(Team, team_id) if (team_id and ut) else None
        trial_active = is_trial_active(team)
        trial_until = team.trial_until.strftime('%d.%m.%Y') if (trial_active and team) else None
        sub_active = team and team.subscription_until and datetime.now() < team.subscription_until
        sub_until = team.subscription_until.strftime('%d.%m.%Y') if sub_active else None
        return jsonify({'html': render_template('fragments/select_stats.html'),
                        'data': {'is_upgrade': body.get('is_upgrade', False),
                                 'current_stats_level': team.effective_stats_level if team else 'basic',
                                 'trial_active': trial_active,
                                 'trial_until': trial_until,
                                 'sub_active': sub_active,
                                 'sub_until': sub_until}})

    if route == '/event-detail':
        event_id = body.get('event_id')
        if not event_id:
            return jsonify({'redirect': '/dashboard'})
        event = db.session.get(Event, int(event_id))
        if not event:
            return jsonify({'redirect': '/dashboard'})
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=event.team_id).first()
        if not ut:
            return jsonify({'error': 'Нет доступа к событию'}), 403
        team = db.session.get(Team, event.team_id)
        members = UserTeam.query.filter_by(team_id=event.team_id, role='player').all()
        pos_labels = {'goalkeeper': '🧤 Вратарь', 'defender': '🛡 Защитник', 'forward': '⚡ Нападающий'}

        attendances = EventAttendance.query.filter_by(event_id=event_id).all()
        att_map = {a.user_id: a for a in attendances}

        going = []
        not_going = []
        all_players = []

        for m in members:
            p = db.session.get(User, m.user_id)
            if not p:
                continue
            existing = MatchStat.query.filter_by(player_id=p.id, event_id=event_id).first()
            att = att_map.get(p.id)
            status = att.status if att else None
            reason = att.reason if att else None
            player_data = {
                'id': p.id, 'first_name': p.first_name, 'last_name': p.last_name,
                'position': m.position or 'forward',
                'position_label': pos_labels.get(m.position, '⚡ Нападающий'),
                'has_stats': existing is not None,
                'attendance_status': status,
                'attendance_reason': reason
            }
            all_players.append(player_data)
            if status == 'going':
                going.append(player_data)
            elif status == 'not_going':
                not_going.append(player_data)

        my_attendance = att_map.get(user.id)
        my_status = my_attendance.status if my_attendance else None
        my_reason = my_attendance.reason if my_attendance else None

        return jsonify({'html': render_template('fragments/event_detail.html'),
                        'data': {
                            'event': {'id': event.id, 'title': event.title,
                                      'event_date': event.event_date.strftime('%d.%m.%Y %H:%M'),
                                      'event_type': event.event_type, 'location': event.location},
                            'players': all_players,
                            'going': going,
                            'not_going': not_going,
                            'my_status': my_status,
                            'my_reason': my_reason,
                            'is_coach': ut.role == 'coach',
                            'stats_level': team.effective_stats_level if team else 'basic'
                        }})

    if route == '/edit-stats':
        event_id = body.get('event_id')
        player_id = body.get('player_id')
        position = body.get('position', 'forward')
        stats_level = body.get('stats_level', 'basic')
        event = db.session.get(Event, int(event_id)) if event_id else None
        if not event:
            return jsonify({'error': 'Событие не найдено'}), 404
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=event.team_id, role='coach').first()
        if not ut:
            return jsonify({'error': 'Только тренер может вносить статистику'}), 403
        existing_stats = {}
        if event_id and player_id:
            stat = MatchStat.query.filter_by(player_id=int(player_id), event_id=int(event_id)).first()
            if stat:
                existing_stats = {
                    'goals': stat.goals, 'assists': stat.assists,
                    'yellow_cards': stat.yellow_cards, 'red_cards': stat.red_cards,
                    'minutes_played': stat.minutes_played,
                    'saves': stat.saves, 'goals_conceded': stat.goals_conceded,
                    'gk_passes_total': stat.gk_passes_total, 'gk_passes_accurate': stat.gk_passes_accurate,
                    'gk_losses': stat.gk_losses, 'goal_kicks_total': stat.goal_kicks_total,
                    'goal_kicks_accurate': stat.goal_kicks_accurate,
                    'shots_total': stat.shots_total, 'shots_on_target': stat.shots_on_target,
                    'passes_total': stat.passes_total, 'passes_accurate': stat.passes_accurate,
                    'tackles': stat.tackles, 'losses': stat.losses
                }
        return jsonify({'html': render_template('fragments/edit_stats.html'),
                        'data': {'event_id': event_id, 'event_title': event.title,
                                 'player_id': player_id, 'player_name': body.get('player_name', ''),
                                 'position': position, 'stats_level': stats_level,
                                 'existing_stats': existing_stats}})

    if route == '/player-match-stats':
        event_id = body.get('event_id')
        stats_level = body.get('stats_level', 'basic')
        if not event_id:
            return jsonify({'redirect': '/dashboard'})
        event = db.session.get(Event, int(event_id))
        if not event:
            return jsonify({'redirect': '/dashboard'})
        player_ut = UserTeam.query.filter_by(user_id=user.id, team_id=event.team_id).first()
        if not player_ut:
            return jsonify({'error': 'Нет доступа к событию'}), 403
        position = player_ut.position if player_ut else 'forward'
        stat = MatchStat.query.filter_by(player_id=user.id, event_id=int(event_id)).first()
        stat_data = None
        if stat:
            stat_data = {
                'goals': stat.goals, 'assists': stat.assists,
                'yellow_cards': stat.yellow_cards, 'red_cards': stat.red_cards,
                'minutes_played': stat.minutes_played, 'rating': stat.rating,
                'saves': stat.saves, 'goals_conceded': stat.goals_conceded,
                'gk_passes_total': stat.gk_passes_total, 'gk_passes_accurate': stat.gk_passes_accurate,
                'gk_losses': stat.gk_losses, 'goal_kicks_total': stat.goal_kicks_total,
                'goal_kicks_accurate': stat.goal_kicks_accurate,
                'shots_total': stat.shots_total, 'shots_on_target': stat.shots_on_target,
                'passes_total': stat.passes_total, 'passes_accurate': stat.passes_accurate,
                'tackles': stat.tackles, 'losses': stat.losses
            }
        return jsonify({'html': render_template('fragments/player_match_stats.html'),
                        'data': {'event': {'id': event.id, 'title': event.title,
                                           'event_date': event.event_date.strftime('%d.%m.%Y %H:%M'),
                                           'event_type': event.event_type, 'location': event.location},
                                 'stat': stat_data, 'stats_level': stats_level, 'position': position}})

    if route == '/dashboard':
        team_id = get_current_team_id()
        if not team_id:
            return jsonify({'redirect': '/select-team'})
        ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
        if not ut:
            return jsonify({'redirect': '/select-team'})
        team = db.session.get(Team, team_id)
        events = Event.query.filter_by(team_id=team_id).order_by(Event.event_date).all()
        pos_labels = {'goalkeeper': '🧤 Вратарь', 'defender': '🛡 Защитник', 'forward': '⚡ Нападающий'}

        if ut.role == 'coach':
            members = UserTeam.query.filter_by(team_id=team_id, role='player').all()
            players = []
            for m in members:
                p = db.session.get(User, m.user_id)
                if p:
                    players.append({'id': p.id, 'first_name': p.first_name, 'last_name': p.last_name,
                                    'position': m.position or 'forward',
                                    'position_label': pos_labels.get(m.position, '⚡ Нападающий')})
            trial_active = is_trial_active(team)
            trial_until = team.trial_until.strftime('%d.%m.%Y') if trial_active else None
            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {
                    'id': team.id, 'name': team.name, 'join_code': team.join_code,
                    'city': team.city, 'stats_level': team.effective_stats_level,
                    'trial_active': trial_active, 'trial_until': trial_until
                } if team else None,
                'events': [{'id': e.id, 'title': e.title,
                            'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                            'event_type': e.event_type, 'location': e.location} for e in events],
                'players': players
            }
            return jsonify({'html': render_template('fragments/coach_dashboard.html'), 'data': data})
        else:
            position = ut.position or 'forward'
            # Статистика игрока только по матчам текущей команды
            my_stats = MatchStat.query.join(Event).filter(
                MatchStat.player_id == user.id,
                Event.team_id == team_id
            ).all()
            total_stats = {
                'games': len(set(s.event_id for s in my_stats)),
                'goals': sum(s.goals for s in my_stats),
                'assists': sum(s.assists for s in my_stats),
                'yellow_cards': sum(s.yellow_cards for s in my_stats),
                'red_cards': sum(s.red_cards for s in my_stats),
                'pass_accuracy': 0
            }
            if position == 'goalkeeper':
                total_saves = sum(s.saves for s in my_stats)
                total_conceded = sum(s.goals_conceded for s in my_stats)
                total_stats['saves'] = total_saves
                total_stats['goals_conceded'] = total_conceded
                total_stats['save_pct'] = round(total_saves / (total_saves + total_conceded) * 100) if (total_saves + total_conceded) > 0 else 0
            else:
                total_passes = sum(s.passes_total for s in my_stats)
                accurate_passes = sum(s.passes_accurate for s in my_stats)
                if total_passes > 0:
                    total_stats['pass_accuracy'] = round(accurate_passes / total_passes * 100)
            advice = []
            if team and team.effective_stats_level == 'detailed' and my_stats:
                advice = generate_advice(my_stats, position)
            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {'name': team.name, 'stats_level': team.effective_stats_level} if team else None,
                'position': position,
                'events': [{'id': e.id, 'title': e.title,
                            'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                            'event_type': e.event_type, 'location': e.location,
                            'has_stats': MatchStat.query.filter_by(player_id=user.id, event_id=e.id).first() is not None} for e in events],
                'stats': total_stats,
                'advice': advice
            }
            return jsonify({'html': render_template('fragments/player_dashboard.html'), 'data': data})

    if route == '/rules':
        return jsonify({
            'html': render_template('fragments/rules.html'),
            'data': {'back_route': body.get('back_route', '/dashboard')}
        })

    return jsonify({'error': 'Not found'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)