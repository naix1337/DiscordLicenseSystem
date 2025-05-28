from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, timedelta
import secrets
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24) # Wichtig für Sessions und Flash-Nachrichten!

# --- Hilfsfunktion für Admin-Check (einfach gehalten) ---
def is_admin():
    # Eine einfach gehaltene Admin-Überprüfung. Für eine robustere App
    # sollte dies über eine Rollen-Spalte in der 'users'-Tabelle erfolgen.
    return session.get('username') == 'admin' # Ersetze 'admin' durch den tatsächlichen Admin-Benutzernamen

# --- Datenbank-Initialisierung ---
def init_db():
    conn = sqlite3.connect('key_system.db')
    c = conn.cursor()

    # Tabelle für Benutzerkonten
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP
        )
    ''')

    # NEU: Überprüfen und Hinzufügen der Spalte 'created_at' falls sie fehlt
    try:
        c.execute("SELECT created_at FROM users LIMIT 1")
    except sqlite3.OperationalError:
        # Spalte existiert nicht, füge sie hinzu
        c.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")
        # Aktualisiere vorhandene Zeilen mit dem aktuellen Zeitstempel
        c.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")


    # Tabelle für Keys
    c.execute('''
        CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY,
            duration_days INTEGER,
            created_at TIMESTAMP,
            created_by TEXT,
            uses_left INTEGER
        )
    ''')

    # Tabelle für Redemptions
    c.execute('''
        CREATE TABLE IF NOT EXISTS redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            user_id TEXT,
            discord_username TEXT,
            redeemed_at TIMESTAMP,
            expires_at TIMESTAMP,
            active BOOLEAN,
            FOREIGN KEY(key) REFERENCES keys(key)
        )
    ''')

    # NEU: Tabelle für Einladungscodes
    c.execute('''
        CREATE TABLE IF NOT EXISTS invite_codes (
            code TEXT PRIMARY KEY,
            used_by TEXT,
            used_at TIMESTAMP
        )
    ''')

    # Überprüfen und Hinzufügen der Spalte 'discord_username'
    try:
        c.execute("ALTER TABLE redemptions ADD COLUMN discord_username TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name: discord_username" not in str(e):
            raise e
        pass # Spalte existiert bereits

    conn.commit()
    conn.close()

    # Initialen Admin-Benutzer erstellen, falls keiner existiert
    conn = sqlite3.connect('key_system.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not c.fetchone():
        hashed_password = generate_password_hash('admin_password') # Setze hier ein sicheres Initialpasswort!
        # Füge created_at beim Initial-Admin hinzu
        c.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)', ('admin', hashed_password, datetime.now()))
        conn.commit()
        print("\n---------------------------------------------------------")
        print("Initialer Admin-Benutzer 'admin' mit Passwort 'admin_password' erstellt.")
        print("BITTE ÄNDERN SIE DAS PASSWORT SOFORT NACH DEM ERSTEN LOGIN!")
        print("---------------------------------------------------------\n")
    conn.close()

# Funktion zur Generierung eines Einladungscodes
def generate_invite_code():
    code = secrets.token_urlsafe(16) # Generiert einen sicheren, URL-freundlichen String
    conn = sqlite3.connect('key_system.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO invite_codes (code) VALUES (?)', (code,))
        conn.commit()
        print(f"\n---------------------------------------------------------")
        print(f"Neuer Einladungscode generiert: {code}")
        print(f"---------------------------------------------------------\n")
        return code
    except sqlite3.IntegrityError:
        # Falls der Code aus einem seltenen Zufall bereits existiert, versuche es erneut
        return generate_invite_code()
    finally:
        conn.close()


# --- Routen ---
@app.route('/')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect('key_system.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = user['username']
            flash('Erfolgreich eingeloggt!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Ungültige Anmeldeinformationen.', 'danger')
            return render_template('login.html')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        invite_code = request.form.get('invite_code')

        if not (username and password and confirm_password and invite_code):
            flash('Bitte füllen Sie alle Felder aus.', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwörter stimmen nicht überein.', 'danger')
            return render_template('register.html')

        conn = sqlite3.connect('key_system.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Einladungscode überprüfen
        c.execute('SELECT * FROM invite_codes WHERE code = ? AND used_by IS NULL', (invite_code,))
        invite_entry = c.fetchone()

        if not invite_entry:
            flash('Ungültiger oder bereits verwendeter Einladungscode.', 'danger')
            conn.close()
            return render_template('register.html')

        # Überprüfen, ob der Benutzername bereits existiert
        c.execute('SELECT * FROM users WHERE username = ?', (username,))
        if c.fetchone():
            flash('Benutzername existiert bereits.', 'danger')
            conn.close()
            return render_template('register.html')

        hashed_password = generate_password_hash(password)

        try:
            # Füge created_at beim neuen Benutzer hinzu
            c.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)', (username, hashed_password, datetime.now()))
            # Einladungscode als verwendet markieren
            c.execute('UPDATE invite_codes SET used_by = ?, used_at = ? WHERE code = ?',
                      (username, datetime.now(), invite_code))
            conn.commit()
            flash('Benutzer erfolgreich registriert!', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Fehler bei der Registrierung.', 'danger')
        finally:
            conn.close()
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('Sie wurden abgemeldet.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('key_system.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('SELECT * FROM keys ORDER BY created_at DESC')
    keys = c.fetchall()

    c.execute('SELECT * FROM redemptions ORDER BY redeemed_at DESC')
    redemptions = c.fetchall()

    conn.close()

    return render_template('dashboard.html', keys=keys, redemptions=redemptions, username=session.get('username'))


# NEU: Admin-Route für die Benutzerübersicht
@app.route('/admin_users')
def admin_users():
    if not session.get('logged_in') or not is_admin():
        flash('Sie haben keine Berechtigung, diese Seite aufzurufen.', 'danger')
        return redirect(url_for('dashboard')) # Oder login, je nach gewünschtem Verhalten

    conn = sqlite3.connect('key_system.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Alle Benutzer abrufen
    c.execute('SELECT id, username, created_at FROM users ORDER BY created_at DESC')
    users = c.fetchall()

    # Alle Einladungscodes abrufen
    c.execute('SELECT * FROM invite_codes ORDER BY used_at DESC, code ASC')
    invite_codes = c.fetchall()

    conn.close()

    return render_template('admin_users.html', users=users, invite_codes=invite_codes, username=session.get('username'))

@app.route('/generate_key', methods=['POST'])
def generate_key():
    if not session.get('logged_in'):
        flash('Sie müssen angemeldet sein, um Keys zu generieren.', 'danger')
        return redirect(url_for('login'))

    try:
        duration_days = int(request.form.get('duration', 30))
        uses = int(request.form.get('uses', 1))

        key_prefix = "PREMIUM-"
        key = key_prefix + secrets.token_hex(8).upper()

        conn = sqlite3.connect('key_system.db')
        c = conn.cursor()

        # created_by ist jetzt der eingeloggte Benutzer
        c.execute('''
            INSERT INTO keys (key, duration_days, created_at, created_by, uses_left)
            VALUES (?, ?, ?, ?, ?)
        ''', (key, duration_days, datetime.now(), session.get('username', 'Unknown'), uses))

        conn.commit()
        conn.close()
        flash('Key erfolgreich generiert!', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        flash(f"Fehler beim Generieren des Keys: {str(e)}", 'danger')
        return redirect(url_for('dashboard'))

@app.route('/delete_key/<key>', methods=['POST'])
def delete_key(key):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('key_system.db')
    c = conn.cursor()
    c.execute('DELETE FROM keys WHERE key = ?', (key,))
    conn.commit()
    conn.close()
    flash(f'Key {key} wurde gelöscht.', 'info')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    init_db()
    # Generiere einen Einladungscode beim Start der App und gib ihn in der Konsole aus
    generate_invite_code()
    app.run(debug=True, host='0.0.0.0', port=5000)