"""
OIO Platform - Flask Backend
"""
import os
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# ===== App Setup =====
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

DB_PATH = 'oio.db'

# ===== Database Setup =====
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            avatar_color TEXT DEFAULT 'linear-gradient(135deg, #6c8aff, #a78bfa)',
            status TEXT DEFAULT 'offline',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS groups_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            avatar_color TEXT DEFAULT 'linear-gradient(135deg, #fb923c, #f97316)',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER,
            user_id INTEGER,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, user_id),
            FOREIGN KEY (group_id) REFERENCES groups_table(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER,
            group_id INTEGER,
            content TEXT NOT NULL,
            msg_type TEXT DEFAULT 'text',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id),
            FOREIGN KEY (group_id) REFERENCES groups_table(id)
        );

        CREATE TABLE IF NOT EXISTS ai_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_context TEXT,
            ai_response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')
    conn.commit()
    conn.close()

# ===== User Model =====
class User(UserMixin):
    def __init__(self, id, username, display_name, avatar_color, status):
        self.id = id
        self.username = username
        self.display_name = display_name
        self.avatar_color = avatar_color
        self.status = status

    def get_initials(self):
        parts = self.display_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.display_name[:2].upper()

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row['id'], row['username'], row['display_name'],
                     row['avatar_color'], row['status'])
    return None

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ===== Online Users Tracking =====
online_users = {}  # user_id -> sid

# ===== OIO Engine (imported from separate file for model replacement) =====
from oio_engine import ai_assistant_analyze

# Debug mode: toggle score visibility via /api/debug/toggle-scores
SHOW_SCORES = False

# ===== Routes =====
@app.route('/')
@login_required
def index():
    return render_template('index.html', user=current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db()
        row = conn.execute('SELECT * FROM users WHERE username = ? AND password_hash = ?',
                           (username, hash_password(password))).fetchone()
        conn.close()

        if row:
            user = User(row['id'], row['username'], row['display_name'],
                        row['avatar_color'], row['status'])
            login_user(user)
            return redirect(url_for('index'))
        else:
            error = 'Invalid username or password'

    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        display_name = request.form.get('display_name', '').strip()

        if not username or not password or not display_name:
            error = 'All fields are required'
        else:
            colors = [
                'linear-gradient(135deg, #f472b6, #e879f9)',
                'linear-gradient(135deg, #34d399, #10b981)',
                'linear-gradient(135deg, #60a5fa, #3b82f6)',
                'linear-gradient(135deg, #a78bfa, #7c3aed)',
                'linear-gradient(135deg, #fbbf24, #f59e0b)',
                'linear-gradient(135deg, #f87171, #ef4444)',
            ]
            import random
            color = random.choice(colors)

            conn = get_db()
            try:
                conn.execute('INSERT INTO users (username, password_hash, display_name, avatar_color) VALUES (?, ?, ?, ?)',
                             (username, hash_password(password), display_name, color))
                conn.commit()
                conn.close()
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                conn.close()
                error = 'Username already exists'

    return render_template('register.html', error=error)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ===== API Routes =====
@app.route('/api/contacts')
@login_required
def api_contacts():
    conn = get_db()
    # Get all users except current user
    users = conn.execute('SELECT * FROM users WHERE id != ?', (current_user.id,)).fetchall()

    # Get groups the user is in
    groups = conn.execute('''
        SELECT g.* FROM groups_table g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = ?
    ''', (current_user.id,)).fetchall()

    contacts = []

    for u in users:
        # Get last message between current user and this user
        last_msg = conn.execute('''
            SELECT content, created_at FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY created_at DESC LIMIT 1
        ''', (current_user.id, u['id'], u['id'], current_user.id)).fetchone()

        # Count unread (simple: messages from them that are newer)
        unread = conn.execute('''
            SELECT COUNT(*) as cnt FROM messages
            WHERE sender_id = ? AND receiver_id = ? AND msg_type = 'text'
        ''', (u['id'], current_user.id)).fetchone()

        initials = ''
        parts = u['display_name'].split()
        if len(parts) >= 2:
            initials = (parts[0][0] + parts[1][0]).upper()
        else:
            initials = u['display_name'][:2].upper()

        contacts.append({
            'id': u['id'],
            'name': u['display_name'],
            'initials': initials,
            'color': u['avatar_color'],
            'status': u['status'] if u['id'] in [int(k) for k in online_users.keys()] else 'offline',
            'preview': last_msg['content'][:40] if last_msg else '',
            'time': last_msg['created_at'][-8:-3] if last_msg else '',
            'unread': 0,
            'type': 'chat',
            'target_id': u['id']
        })

    for g in groups:
        last_msg = conn.execute('''
            SELECT u.display_name, m.content, m.created_at FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.group_id = ? ORDER BY m.created_at DESC LIMIT 1
        ''', (g['id'],)).fetchone()

        initials = ''.join([w[0] for w in g['name'].split()[:2]]).upper()
        contacts.append({
            'id': g['id'],
            'name': g['name'],
            'initials': initials,
            'color': g['avatar_color'],
            'status': None,
            'preview': f"{last_msg['display_name']}: {last_msg['content'][:30]}" if last_msg else '',
            'time': last_msg['created_at'][-8:-3] if last_msg else '',
            'unread': 0,
            'type': 'group',
            'target_id': g['id']
        })

    conn.close()
    return jsonify(contacts)

@app.route('/api/messages/<chat_type>/<int:target_id>')
@login_required
def api_messages(chat_type, target_id):
    conn = get_db()
    if chat_type == 'chat':
        rows = conn.execute('''
            SELECT m.*, u.display_name, u.avatar_color FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?)
            ORDER BY m.created_at ASC LIMIT 100
        ''', (current_user.id, target_id, target_id, current_user.id)).fetchall()
    else:
        rows = conn.execute('''
            SELECT m.*, u.display_name, u.avatar_color FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.group_id = ?
            ORDER BY m.created_at ASC LIMIT 100
        ''', (target_id,)).fetchall()

    messages = []
    for r in rows:
        initials = ''
        parts = r['display_name'].split()
        if len(parts) >= 2:
            initials = (parts[0][0] + parts[1][0]).upper()
        else:
            initials = r['display_name'][:2].upper()

        messages.append({
            'id': r['id'],
            'sender_id': r['sender_id'],
            'content': r['content'],
            'display_name': r['display_name'],
            'avatar_color': r['avatar_color'],
            'initials': initials,
            'time': r['created_at'][-8:-3] if r['created_at'] else '',
            'is_me': r['sender_id'] == current_user.id
        })

    conn.close()
    return jsonify(messages)

@app.route('/api/ai/suggestions', methods=['POST'])
@login_required
def api_ai_suggestions():
    data = request.get_json()
    messages_context = data.get('messages', [])
    suggestions = ai_assistant_analyze(
        messages_context,
        current_user_id=current_user.id,
        show_scores=SHOW_SCORES
    )
    return jsonify(suggestions)

@app.route('/api/email/generate', methods=['POST'])
@login_required
def api_email_generate():
    data = request.get_json()
    email_content = data.get('email_content', '').strip()
    selected_advice = data.get('selected_advice', None)  # list of advice IDs
    custom_context = data.get('custom_context', None)     # user-provided details
    if not email_content:
        return jsonify({'error': 'No email content provided'}), 400

    from models.email_reply import generate_email_replies
    result = generate_email_replies(email_content, selected_advice_ids=selected_advice,
                                    user_name=current_user.display_name,
                                    custom_context=custom_context)
    return jsonify(result)

@app.route('/api/email/guardian', methods=['POST'])
@login_required
def api_guardian():
    """Guardian: Analyze user's own draft for risky phrasing."""
    data = request.get_json()
    draft_content = data.get('draft_content', '').strip()
    selected_advice = data.get('selected_advice', None)
    if not draft_content:
        return jsonify({'error': 'No draft content provided'}), 400

    from models.email_reply import improve_draft
    result = improve_draft(draft_content, selected_advice_ids=selected_advice)
    return jsonify(result)

@app.route('/api/debug/toggle-scores', methods=['POST'])
@login_required
def toggle_scores():
    """Toggle OIO score visibility. For development/debug only."""
    global SHOW_SCORES
    SHOW_SCORES = not SHOW_SCORES
    return jsonify({'show_scores': SHOW_SCORES})

@app.route('/api/debug/scores-status')
@login_required
def scores_status():
    return jsonify({'show_scores': SHOW_SCORES})

@app.route('/api/groups', methods=['POST'])
@login_required
def api_create_group():
    data = request.get_json()
    name = data.get('name', '').strip()
    member_ids = data.get('members', [])

    if not name:
        return jsonify({'error': 'Group name required'}), 400

    conn = get_db()
    cursor = conn.execute('INSERT INTO groups_table (name, created_by) VALUES (?, ?)',
                          (name, current_user.id))
    group_id = cursor.lastrowid

    # Add creator as member
    conn.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)',
                 (group_id, current_user.id))
    # Add other members
    for mid in member_ids:
        conn.execute('INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)',
                     (group_id, mid))
    conn.commit()
    conn.close()
    return jsonify({'id': group_id, 'name': name})

# ===== SocketIO Events =====
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        online_users[current_user.id] = request.sid
        # Update user status
        conn = get_db()
        conn.execute('UPDATE users SET status = ? WHERE id = ?', ('online', current_user.id))
        conn.commit()
        conn.close()
        emit('user_online', {'user_id': current_user.id}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        online_users.pop(current_user.id, None)
        conn = get_db()
        conn.execute('UPDATE users SET status = ? WHERE id = ?', ('offline', current_user.id))
        conn.commit()
        conn.close()
        emit('user_offline', {'user_id': current_user.id}, broadcast=True)

@socketio.on('join_room')
def handle_join_room(data):
    room = data.get('room')
    if room:
        join_room(room)

@socketio.on('leave_room')
def handle_leave_room(data):
    room = data.get('room')
    if room:
        leave_room(room)


# Video/Voice call signaling
@socketio.on('call_user')
def handle_call(data):
    target_id = data.get('target_id')
    call_type = data.get('call_type', 'video')  # 'video' or 'voice'
    if target_id in online_users:
        emit('incoming_call', {
            'caller_id': current_user.id,
            'caller_name': current_user.display_name,
            'call_type': call_type
        }, room=online_users[target_id])

@socketio.on('accept_call')
def handle_accept(data):
    caller_id = data.get('caller_id')
    if caller_id in online_users:
        emit('call_accepted', {
            'accepter_id': current_user.id,
            'accepter_name': current_user.display_name
        }, room=online_users[caller_id])

@socketio.on('reject_call')
def handle_reject(data):
    caller_id = data.get('caller_id')
    if caller_id in online_users:
        emit('call_rejected', {
            'rejecter_name': current_user.display_name
        }, room=online_users[caller_id])

@socketio.on('end_call')
def handle_end_call(data):
    target_id = data.get('target_id')
    if target_id in online_users:
        emit('call_ended', {}, room=online_users[target_id])

# ===== Run =====
def seed_test_account():
    """Create a test account so new users always have someone to chat with."""
    conn = get_db()
    existing = conn.execute('SELECT id FROM users WHERE username = ?', ('testbot',)).fetchone()
    if not existing:
        conn.execute(
            'INSERT INTO users (username, password_hash, display_name, avatar_color, status) VALUES (?, ?, ?, ?, ?)',
            ('testbot', hash_password('test123'),
             'OIO Assistant Bot',
             'linear-gradient(135deg, #34d399, #10b981)',
             'online')
        )
        conn.commit()
        print("  [Seed] Test account created: testbot / test123")
    else:
        # Keep bot online
        conn.execute('UPDATE users SET status = ? WHERE username = ?', ('online', 'testbot'))
        conn.commit()
    conn.close()

# Bot auto-reply logic — see models/bot_replies.py (NEED REPLACE)
from models.bot_replies import get_bot_reply

def get_bot_user_id():
    conn = get_db()
    row = conn.execute('SELECT id FROM users WHERE username = ?', ('testbot',)).fetchone()
    conn.close()
    return row['id'] if row else None

# Notification data (in-memory for now)
def get_notifications(user_id):
    return [
        {'id': 1, 'type': 'system', 'title': 'Welcome to OIO', 'text': 'Your account is set up. Start chatting to see OIO analysis in action.', 'time': 'Just now', 'read': False},
        {'id': 2, 'type': 'tip', 'title': 'Try the OIO Bot', 'text': 'Click on "OIO Assistant Bot" in your contacts to test the platform features.', 'time': '1m ago', 'read': False},
        {'id': 3, 'type': 'update', 'title': 'OIO Score Tracking', 'text': 'Your Openness, Initiative, and Objectivity scores are now visible in the right panel during conversations.', 'time': '5m ago', 'read': True},
    ]

# Settings data
SETTINGS_SECTIONS = [
    {
        'title': 'Profile',
        'items': [
            {'key': 'display_name', 'label': 'Display Name', 'type': 'text'},
            {'key': 'status_msg', 'label': 'Status Message', 'type': 'text'},
        ]
    },
    {
        'title': 'OIO Preferences',
        'items': [
            {'key': 'oio_nudges', 'label': 'Enable OIO Nudges', 'type': 'toggle', 'default': True},
            {'key': 'conflict_alerts', 'label': 'Conflict Alerts', 'type': 'toggle', 'default': True},
            {'key': 'pressure_alerts', 'label': 'Pressure Signal Alerts', 'type': 'toggle', 'default': True},
            {'key': 'score_display', 'label': 'Show OIO Scores', 'type': 'toggle', 'default': True},
        ]
    },
    {
        'title': 'Notifications',
        'items': [
            {'key': 'desktop_notif', 'label': 'Desktop Notifications', 'type': 'toggle', 'default': False},
            {'key': 'sound_notif', 'label': 'Message Sounds', 'type': 'toggle', 'default': True},
        ]
    },
    {
        'title': 'Appearance',
        'items': [
            {'key': 'theme', 'label': 'Theme', 'type': 'select', 'options': ['Dark', 'Light'], 'default': 'Dark'},
            {'key': 'font_size', 'label': 'Font Size', 'type': 'select', 'options': ['Small', 'Medium', 'Large'], 'default': 'Medium'},
        ]
    },
]

@app.route('/api/notifications')
@login_required
def api_notifications():
    return jsonify(get_notifications(current_user.id))

@app.route('/api/settings')
@login_required
def api_settings():
    return jsonify(SETTINGS_SECTIONS)

# Override the send_message handler to include bot reply
original_handle = None

@socketio.on('send_message')
def handle_send_message(data):
    if not current_user.is_authenticated:
        return

    content = data.get('content', '').strip()
    chat_type = data.get('chat_type', 'chat')
    target_id = data.get('target_id')

    if not content or not target_id:
        return

    conn = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if chat_type == 'chat':
        conn.execute('INSERT INTO messages (sender_id, receiver_id, content, created_at) VALUES (?, ?, ?, ?)',
                     (current_user.id, target_id, content, now))
    else:
        conn.execute('INSERT INTO messages (sender_id, group_id, content, created_at) VALUES (?, ?, ?, ?)',
                     (current_user.id, target_id, content, now))
    conn.commit()
    conn.close()

    initials = current_user.get_initials()

    msg_data = {
        'sender_id': current_user.id,
        'content': content,
        'display_name': current_user.display_name,
        'avatar_color': current_user.avatar_color,
        'initials': initials,
        'time': now[-8:-3],
        'is_me': False
    }

    if chat_type == 'chat':
        room = f"chat_{min(current_user.id, target_id)}_{max(current_user.id, target_id)}"
        emit('new_message', msg_data, room=room)

        # Bot auto-reply
        bot_id = get_bot_user_id()
        if bot_id and target_id == bot_id:
            import time as _time
            reply_text = get_bot_reply(content)
            reply_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            conn2 = get_db()
            conn2.execute('INSERT INTO messages (sender_id, receiver_id, content, created_at) VALUES (?, ?, ?, ?)',
                         (bot_id, current_user.id, reply_text, reply_now))
            conn2.commit()
            conn2.close()

            bot_msg = {
                'sender_id': bot_id,
                'content': reply_text,
                'display_name': 'OIO Assistant Bot',
                'avatar_color': 'linear-gradient(135deg, #34d399, #10b981)',
                'initials': 'OB',
                'time': reply_now[-8:-3],
                'is_me': False
            }
            socketio.sleep(0.8)  # Small delay to feel natural
            emit('new_message', bot_msg, room=room)
    else:
        room = f"group_{target_id}"
        emit('new_message', msg_data, room=room)

if __name__ == '__main__':
    init_db()
    seed_test_account()
    print("=" * 50)
    print("  OIO Platform Running!")
    print("  Open http://localhost:8080 in your browser")
    print("  Test account: testbot / test123")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=8080, debug=True, allow_unsafe_werkzeug=True)
