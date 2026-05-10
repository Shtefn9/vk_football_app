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
    """Генерирует советы игроку на основе его статистики за все матчи"""
    if not stats_list:
        return []

    games = len(stats_list)
    advice = []

    # Общие показатели
    total_goals = sum(s.goals for s in stats_list)
    total_assists = sum(s.assists for s in stats_list)
    total_yellow = sum(s.yellow_cards for s in stats_list)
    total_red = sum(s.red_cards for s in stats_list)
    avg_goals = total_goals / games
    avg_assists = total_assists / games

    if position == 'forward':
        # ── НАПАДАЮЩИЙ ──────────────────────────────

        # Голы
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

        # Удары в створ
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

        # Голевые передачи
        if total_assists == 0:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Ни одной голевой передачи. Чаще смотри по сторонам перед ударом — возможно партнёр стоит в лучшей позиции.'})
        elif avg_assists < 0.2:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Мало голевых передач. Развивай периферийное зрение — замечай открытых партнёров в штрафной.'})
        else:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Хорошее взаимодействие с партнёрами! Продолжай искать открытых игроков в опасных зонах.'})

        # Потери
        total_losses = sum(s.losses for s in stats_list)
        avg_losses = total_losses / games
        if avg_losses > 5:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Очень много потерь. В сложных ситуациях упрощай игру — лучше отдай назад чем потерять мяч в опасной зоне.'})
        elif avg_losses > 3:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Есть потери. Работай над укрыванием мяча корпусом под давлением защитника.'})
        else:
            advice.append({'icon': '✅', 'title': 'Потери', 'text': 'Хороший контроль мяча! Продолжай играть уверенно под давлением.'})

        # Точность паса
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
        # ── ЗАЩИТНИК ────────────────────────────────

        # Отборы
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

        # Потери
        total_losses = sum(s.losses for s in stats_list)
        avg_losses = total_losses / games
        if avg_losses > 4:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Очень много потерь для защитника. В своей зоне играй проще — не рискуй с обводкой, отдавай мяч вратарю или назад.'})
        elif avg_losses > 2:
            advice.append({'icon': '⚠️', 'title': 'Потери', 'text': 'Есть потери в защите. Под давлением соперника не задерживай мяч — принимай решение быстрее.'})
        else:
            advice.append({'icon': '✅', 'title': 'Потери', 'text': 'Надёжный контроль мяча в защите! Продолжай играть уверенно.'})

        # Точность паса
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

        # Голы и передачи защитника
        if total_goals > 0:
            advice.append({'icon': '⚽', 'title': 'Голы', 'text': 'Ты забил как защитник — отлично подключился в атаку! Главное не забывать возвращаться назад после атаки.'})
        if total_assists > 0:
            advice.append({'icon': '🤝', 'title': 'Передачи', 'text': 'Голевая передача от защитника — значит ты хорошо читаешь игру и вовремя подключаешься к атакам.'})

        # Карточки
        if total_yellow / games > 0.3:
            advice.append({'icon': '🟨', 'title': 'Дисциплина', 'text': 'Слишком много жёлтых карточек. Учись встречать соперника корпусом а не ногой.'})
        if total_red > 0:
            advice.append({'icon': '🟥', 'title': 'Удаления', 'text': 'Удаление дорого обходится команде. Контролируй эмоции и никогда не иди в подкат сзади.'})

    elif position == 'goalkeeper':
        # ── ВРАТАРЬ ─────────────────────────────────

        # Процент сейвов
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

        # Пропущенные голы
        avg_conceded = total_conceded / games
        if avg_conceded == 0:
            advice.append({'icon': '🏆', 'title': 'Сухие матчи', 'text': 'Не пропустил ни одного гола — лучший результат для вратаря! Продолжай держать концентрацию весь матч.'})
        elif avg_conceded <= 1:
            advice.append({'icon': '✅', 'title': 'Пропущенные голы', 'text': 'Один пропущенный гол за матч — нормальный результат. Анализируй где была ошибка в позиции.'})
        elif avg_conceded <= 3:
            advice.append({'icon': '⚠️', 'title': 'Пропущенные голы', 'text': 'Много пропускаешь. Разбери каждый гол — был ли ты на правильной позиции в момент удара.'})
        else:
            advice.append({'icon': '🔴', 'title': 'Пропущенные голы', 'text': 'Тяжёлые матчи. Поговори с тренером о позиционных ошибках и серьёзно работай над выбором позиции.'})

        # Точность передач вратаря
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

        # Точность вводов
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

        # Потери вратаря
        total_losses = sum(s.gk_losses for s in stats_list)
        avg_losses = total_losses / games
        if avg_losses > 3:
            advice.append({'icon': '🔴', 'title': 'Потери', 'text': 'Много потерь для вратаря — это очень опасно. В своей штрафной всегда играй надёжно и не рискуй с обводкой.'})
        elif avg_losses > 1:
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
        join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        team = Team(name=data['team_name'], city=data.get('city', ''),
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
        return jsonify({'error': 'unauthorized'}), 403
    team_id = get_current_team_id()
    ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
    if not ut or ut.role != 'coach':
        return jsonify({'error': 'unauthorized'}), 403
    try:
        data = request.get_json()
        event = Event(team_id=team_id, title=data['title'],
                      event_date=datetime.fromisoformat(data['event_date']),
                      event_type=data['event_type'], location=data.get('location', ''))
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
        player_ut = UserTeam.query.filter_by(user_id=player_id, team_id=team_id).first()
        position = player_ut.position if player_ut else 'forward'
        stat = MatchStat.query.filter_by(player_id=player_id, event_id=event_id).first()
        if not stat:
            stat = MatchStat(player_id=player_id, event_id=event_id)
            db.session.add(stat)
        stat.goals = stats.get('goals', 0)
        stat.assists = stats.get('assists', 0)
        stat.yellow_cards = stats.get('yellow_cards', 0)
        stat.red_cards = stats.get('red_cards', 0)
        stat.minutes_played = stats.get('minutes_played', 0)
        if position == 'goalkeeper':
            stat.saves = stats.get('saves', 0)
            stat.goals_conceded = stats.get('goals_conceded', 0)
            stat.gk_passes_total = stats.get('gk_passes_total', 0)
            stat.gk_passes_accurate = stats.get('gk_passes_accurate', 0)
            stat.gk_losses = stats.get('gk_losses', 0)
            stat.goal_kicks_total = stats.get('goal_kicks_total', 0)
            stat.goal_kicks_accurate = stats.get('goal_kicks_accurate', 0)
        else:
            stat.shots_total = stats.get('shots_total', 0)
            stat.shots_on_target = stats.get('shots_on_target', 0)
            stat.passes_total = stats.get('passes_total', 0)
            stat.passes_accurate = stats.get('passes_accurate', 0)
            stat.tackles = stats.get('tackles', 0)
            stat.losses = stats.get('losses', 0)
        stat.rating = calculate_rating(stat, position, stats_level)
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
        team = db.session.get(Team, team_id) if team_id else None
        return jsonify({'html': render_template('fragments/select_stats.html'),
                        'data': {'is_upgrade': body.get('is_upgrade', False),
                                 'current_stats_level': team.stats_level if team else 'basic'}})

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
        pos_labels = {'goalkeeper': '🧤 Вратарь', 'defender': '🛡 Защитник', 'forward': '⚡ Нападающий'}
        players = []
        for m in members:
            p = db.session.get(User, m.user_id)
            if p:
                existing = MatchStat.query.filter_by(player_id=p.id, event_id=event_id).first()
                players.append({'id': p.id, 'first_name': p.first_name, 'last_name': p.last_name,
                                'position': m.position or 'forward',
                                'position_label': pos_labels.get(m.position, '⚡ Нападающий'),
                                'has_stats': existing is not None})
        return jsonify({'html': render_template('fragments/event_detail.html'),
                        'data': {'event': {'id': event.id, 'title': event.title,
                                           'event_date': event.event_date.strftime('%d.%m.%Y %H:%M'),
                                           'event_type': event.event_type, 'location': event.location},
                                 'players': players, 'stats_level': team.stats_level if team else 'basic'}})

    if route == '/edit-stats':
        event_id = body.get('event_id')
        player_id = body.get('player_id')
        position = body.get('position', 'forward')
        stats_level = body.get('stats_level', 'basic')
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
        event = db.session.get(Event, int(event_id)) if event_id else None
        return jsonify({'html': render_template('fragments/edit_stats.html'),
                        'data': {'event_id': event_id, 'event_title': event.title if event else '',
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
        team_id = get_current_team_id()
        player_ut = UserTeam.query.filter_by(user_id=user.id, team_id=team_id).first()
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
            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {'id': team.id, 'name': team.name, 'join_code': team.join_code,
                         'city': team.city, 'stats_level': team.stats_level} if team else None,
                'events': [{'id': e.id, 'title': e.title,
                            'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                            'event_type': e.event_type, 'location': e.location} for e in events],
                'players': players
            }
            return jsonify({'html': render_template('fragments/coach_dashboard.html'), 'data': data})
        else:
            position = ut.position or 'forward'
            my_stats = MatchStat.query.filter_by(player_id=user.id).all()

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

            # Генерируем советы только для детального тарифа
            advice = []
            if team and team.stats_level == 'detailed' and my_stats:
                advice = generate_advice(my_stats, position)

            data = {
                'user': {'first_name': user.first_name, 'last_name': user.last_name},
                'team': {'name': team.name, 'stats_level': team.stats_level} if team else None,
                'position': position,
                'events': [{'id': e.id, 'title': e.title,
                            'event_date': e.event_date.strftime('%d.%m.%Y %H:%M'),
                            'event_type': e.event_type, 'location': e.location,
                            'has_stats': MatchStat.query.filter_by(player_id=user.id, event_id=e.id).first() is not None} for e in events],
                'stats': total_stats,
                'advice': advice
            }
            return jsonify({'html': render_template('fragments/player_dashboard.html'), 'data': data})

    return jsonify({'error': 'Not found'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)