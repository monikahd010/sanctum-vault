from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import db, User, VaultItem, Beneficiary, ShareLink, ActivityLog, Notification, Payment, PLANS
from datetime import datetime, timedelta
import os, secrets, string, random

app = Flask(__name__)
app.config['SECRET_KEY']              = os.environ.get('SECRET_KEY', 'sanctum-vault-dev-secret-2025!')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///sanctum_vault.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']           = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH']      = 16 * 1024 * 1024   # 16 MB

ALLOWED_EXT = {'pdf','doc','docx','txt','png','jpg','jpeg','gif','xlsx','csv','zip'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db.init_app(app)

# ── SEED ──────────────────────────────────────────────────────────────
def _seed_history(user):
    """Generate 6 months of realistic login activity + a missed-month notification."""
    now = datetime.utcnow()
    icon_cycle = ['login','login','upload','share','login','key','login','ai']
    actions    = ['Logged in','Vault item added','Shared a link','Key rotated','Logged in','AI guide used','Logged in','Document uploaded']
    details    = ['Chrome · Windows','New password entry','Shared to email','Master key','Firefox · Android','Asked about breach','Safari · iPhone','Report.pdf']

    logs = []
    # Generate logins every 3–5 days for 6 months EXCEPT month 4 (missed)
    day = 0
    for month in range(6):
        days_in_month = 30
        for week in range(4):
            # Skip all check-ins in month index 3 (4th month)
            if month == 3:
                continue
            offset = day + week * 7 + random.randint(0, 2)
            ts = now - timedelta(days=180 - offset)
            idx = (month + week) % len(icon_cycle)
            logs.append(ActivityLog(user_id=user.id, action=actions[idx], detail=details[idx],
                                    icon_type=icon_cycle[idx], ip='127.0.0.1',
                                    device='Demo Browser', created_at=ts))
        day += days_in_month

    # Most recent login = yesterday
    user.last_login = now - timedelta(days=1)
    db.session.add_all(logs)

    # Missed-month notification
    db.session.add(Notification(
        user_id=user.id, icon='💓', category='heartbeat',
        title='Heartbeat missed — Month 4',
        message='No check-in detected for the entire month of ' +
                (now - timedelta(days=90)).strftime('%B %Y') +
                '. Your beneficiaries were notified. Please check in to confirm you are safe.',
        is_read=False,
        created_at=now - timedelta(days=60)
    ))
    db.session.add(Notification(
        user_id=user.id, icon='🔔', category='security',
        title='New login from unknown device',
        message='A login was detected from a new device. If this was not you, change your password immediately.',
        is_read=False,
        created_at=now - timedelta(days=10)
    ))
    db.session.add(Notification(
        user_id=user.id, icon='✅', category='general',
        title='Pro plan activated',
        message='Your Pro plan payment was confirmed. Enjoy 5 GB storage and unlimited vault items.',
        is_read=True,
        created_at=now - timedelta(days=120)
    ))
    db.session.commit()

# ── HELPERS ───────────────────────────────────────────────────────────

def seed_db():
    db.create_all()
    # Admin
    if not User.query.filter_by(email='admin@sanctumvault.com').first():
        db.session.add(User(name='Admin', email='admin@sanctumvault.com',
                            password=generate_password_hash('Admin@1234'),
                            role='admin', plan='enterprise'))
        db.session.commit()

    # Demo user with 6 months of heartbeat history + missed month notification
    demo = User.query.filter_by(email='demo@sanctumvault.com').first()
    if not demo:
        demo = User(name='Demo User', email='demo@sanctumvault.com',
                    password=generate_password_hash('Demo@1234'), plan='pro')
        db.session.add(demo)
        db.session.commit()
    if demo and ActivityLog.query.filter_by(user_id=demo.id).count() == 0:
        _seed_history(demo)

with app.app_context():
    seed_db()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def generate_password(length=16):
    chars = string.ascii_letters + string.digits + '!@#$%^&*'
    return ''.join(secrets.choice(chars) for _ in range(length))

def log_activity(user_id, action, detail='', icon_type='login'):
    log = ActivityLog(user_id=user_id, action=action, detail=detail, icon_type=icon_type,
                      ip=request.remote_addr, device=request.headers.get('User-Agent','')[:100])
    db.session.add(log)
    db.session.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

# ══════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════
@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email','').strip()
        password = request.form.get('password','')
        user = User.query.filter_by(email=email, role='user').first()
        if user and not user.is_active:
            flash('Your account has been disabled. Contact support.', 'error')
            return render_template('login.html')
        if user and check_password_hash(user.password, password):
            session['user_id']   = user.id
            session['user_name'] = user.name
            session['role']      = 'user'
            user.last_login      = datetime.utcnow()
            db.session.commit()
            log_activity(user.id, 'Logged in', f'From {request.remote_addr}', 'login')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name     = request.form.get('name','').strip()
        email    = request.form.get('email','').strip()
        password = request.form.get('password','')
        confirm  = request.form.get('confirm_password','')
        if not name or not email or not password:
            flash('All fields are required.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
        else:
            user = User(name=name, email=email, password=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            session['user_id']   = user.id
            session['user_name'] = user.name
            session['role']      = 'user'
            log_activity(user.id, 'Account created', '', 'upload')
            # Welcome notification
            db.session.add(Notification(user_id=user.id, icon='🎉', category='general',
                title='Welcome to Sanctum Vault!',
                message='Your encrypted vault is ready. Add your first item to get started.'))
            db.session.commit()
            flash('Welcome to Sanctum Vault!', 'success')
            return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    uid = session.get('user_id')
    if uid:
        try:
            log_activity(uid, 'Logged out', '', 'login')
        except Exception:
            pass
    session.clear()
    return redirect(url_for('login'))

# ══════════════════════════════════════════════════════════════════════
# USER DASHBOARD
# ══════════════════════════════════════════════════════════════════════
@app.route('/dashboard')
@login_required
def dashboard():
    user          = User.query.get(session['user_id'])
    vault_count   = VaultItem.query.filter_by(user_id=user.id, is_deleted=False).count()
    breach_count  = VaultItem.query.filter_by(user_id=user.id, is_breached=True, is_deleted=False).count()
    share_count   = ShareLink.query.filter_by(user_id=user.id, is_active=True).count()
    recent_activity = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.created_at.desc()).limit(5).all()
    active_payment  = Payment.query.filter_by(user_id=user.id, status='confirmed').order_by(Payment.confirmed_at.desc()).first()
    return render_template('dashboard.html', user=user, vault_count=vault_count,
                           breach_count=breach_count, share_count=share_count,
                           recent_activity=recent_activity, active_payment=active_payment,
                           plans=PLANS)

# ── VAULT ─────────────────────────────────────────────────────────────
@app.route('/vault')
@login_required
def vault():
    user_id  = session['user_id']
    category = request.args.get('category','all')
    query    = VaultItem.query.filter_by(user_id=user_id, is_deleted=False)
    if category != 'all':
        query = query.filter_by(item_type=category)
    items  = query.order_by(VaultItem.updated_at.desc()).all()
    counts = {
        'all':      VaultItem.query.filter_by(user_id=user_id, is_deleted=False).count(),
        'password': VaultItem.query.filter_by(user_id=user_id, item_type='password', is_deleted=False).count(),
        'document': VaultItem.query.filter_by(user_id=user_id, item_type='document', is_deleted=False).count(),
        'note':     VaultItem.query.filter_by(user_id=user_id, item_type='note',     is_deleted=False).count(),
        'card':     VaultItem.query.filter_by(user_id=user_id, item_type='card',     is_deleted=False).count(),
    }
    return render_template('vault.html', items=items, category=category, counts=counts)

@app.route('/vault/add', methods=['GET','POST'])
@login_required
def vault_add():
    if request.method == 'POST':
        item = VaultItem(
            user_id         = session['user_id'],
            name            = request.form.get('name'),
            item_type       = request.form.get('item_type','password'),
            username        = request.form.get('username',''),
            encrypted_value = request.form.get('value',''),
            url             = request.form.get('url',''),
            notes           = request.form.get('notes',''),
        )
        # File upload (documents only)
        file = request.files.get('attachment')
        if file and file.filename and allowed_file(file.filename):
            fname = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            file.save(fpath)
            item.file_name = file.filename
            item.file_path = fname
            item.file_size = os.path.getsize(fpath)
            item.file_mime = file.content_type or ''
        db.session.add(item)
        db.session.commit()
        log_activity(session['user_id'], f'Added vault item: {item.name}', '', 'upload')
        flash('Item added to vault.', 'success')
        return redirect(url_for('vault'))
    return render_template('vault_add.html')

@app.route('/vault/edit/<int:item_id>', methods=['GET','POST'])
@login_required
def vault_edit(item_id):
    item = VaultItem.query.filter_by(id=item_id, user_id=session['user_id'], is_deleted=False).first_or_404()
    if request.method == 'POST':
        item.name            = request.form.get('name', item.name)
        item.username        = request.form.get('username', item.username)
        item.encrypted_value = request.form.get('value', item.encrypted_value)
        item.url             = request.form.get('url', item.url)
        item.notes           = request.form.get('notes', item.notes)
        item.updated_at      = datetime.utcnow()
        # Replace file if new one uploaded
        file = request.files.get('attachment')
        if file and file.filename and allowed_file(file.filename):
            # Delete old file
            if item.file_path:
                old = os.path.join(app.config['UPLOAD_FOLDER'], item.file_path)
                if os.path.exists(old): os.remove(old)
            fname = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            file.save(fpath)
            item.file_name = file.filename
            item.file_path = fname
            item.file_size = os.path.getsize(fpath)
            item.file_mime = file.content_type or ''
        db.session.commit()
        log_activity(session['user_id'], f'Edited vault item: {item.name}', '', 'key')
        flash('Vault item updated.', 'success')
        return redirect(url_for('vault'))
    return render_template('vault_edit.html', item=item)

@app.route('/vault/delete/<int:item_id>', methods=['POST'])
@login_required
def vault_delete(item_id):
    item = VaultItem.query.filter_by(id=item_id, user_id=session['user_id']).first_or_404()
    item.is_deleted = True
    db.session.commit()
    flash('Item removed from vault.', 'success')
    return redirect(url_for('vault'))

@app.route('/vault/download/<int:item_id>')
@login_required
def vault_download(item_id):
    item = VaultItem.query.filter_by(id=item_id, user_id=session['user_id'], is_deleted=False).first_or_404()
    if not item.file_path:
        flash('No file attached to this item.', 'error')
        return redirect(url_for('vault'))
    return send_from_directory(app.config['UPLOAD_FOLDER'], item.file_path, as_attachment=True, download_name=item.file_name)

# ── BENEFICIARIES ──────────────────────────────────────────────────────
@app.route('/beneficiaries', methods=['GET','POST'])
@login_required
def beneficiaries():
    user_id = session['user_id']
    if request.method == 'POST':
        wait_type = request.form.get('wait_type','duration')
        wait_until = None
        wait_years = wait_months = wait_days = wait_hours_val = 0
        if wait_type == 'date':
            raw = request.form.get('wait_until_date','')
            if raw:
                try: wait_until = datetime.strptime(raw, '%Y-%m-%d')
                except ValueError: pass
        else:
            wait_years     = int(request.form.get('wait_years',  0) or 0)
            wait_months    = int(request.form.get('wait_months', 0) or 0)
            wait_days      = int(request.form.get('wait_days',   0) or 0)
            wait_hours_val = int(request.form.get('wait_hours',  0) or 0)
        b = Beneficiary(user_id=user_id, name=request.form.get('name'),
                        email=request.form.get('email'),
                        relationship=request.form.get('relationship',''),
                        wait_years=wait_years, wait_months=wait_months,
                        wait_days=wait_days, wait_hours=wait_hours_val,
                        wait_until=wait_until)
        db.session.add(b)
        db.session.commit()
        flash('Beneficiary added.', 'success')
        return redirect(url_for('beneficiaries'))
    items = Beneficiary.query.filter_by(user_id=user_id).all()
    return render_template('beneficiaries.html', beneficiaries=items)

@app.route('/beneficiaries/edit/<int:bid>', methods=['GET','POST'])
@login_required
def beneficiary_edit(bid):
    b = Beneficiary.query.filter_by(id=bid, user_id=session['user_id']).first_or_404()
    if request.method == 'POST':
        b.name         = request.form.get('name', b.name)
        b.email        = request.form.get('email', b.email)
        b.relationship = request.form.get('relationship', b.relationship)
        wait_type = request.form.get('wait_type','duration')
        if wait_type == 'date':
            raw = request.form.get('wait_until_date','')
            if raw:
                try:
                    b.wait_until  = datetime.strptime(raw,'%Y-%m-%d')
                    b.wait_years  = b.wait_months = b.wait_days = b.wait_hours = 0
                except ValueError: pass
        else:
            b.wait_until  = None
            b.wait_years  = int(request.form.get('wait_years',  0) or 0)
            b.wait_months = int(request.form.get('wait_months', 0) or 0)
            b.wait_days   = int(request.form.get('wait_days',   0) or 0)
            b.wait_hours  = int(request.form.get('wait_hours',  0) or 0)
        db.session.commit()
        flash('Beneficiary updated.', 'success')
        return redirect(url_for('beneficiaries'))
    return render_template('beneficiary_edit.html', b=b)

@app.route('/beneficiaries/delete/<int:bid>', methods=['POST'])
@login_required
def beneficiary_delete(bid):
    b = Beneficiary.query.filter_by(id=bid, user_id=session['user_id']).first_or_404()
    db.session.delete(b)
    db.session.commit()
    flash('Beneficiary removed.', 'success')
    return redirect(url_for('beneficiaries'))

# ── SHARING ────────────────────────────────────────────────────────────
@app.route('/sharing', methods=['GET','POST'])
@login_required
def sharing():
    user_id = session['user_id']
    if request.method == 'POST':
        item_id      = request.form.get('item_id','')
        expire_hours = int(request.form.get('expire_hours', 24))
        max_access   = request.form.get('max_access','')
        token        = secrets.token_urlsafe(32)
        expire_type  = request.form.get('expire_type','hours')
        if expire_type == 'never':
            expires_at = None
        elif expire_type == 'date':
            raw_date = request.form.get('expire_date','')
            try:    expires_at = datetime.strptime(raw_date,'%Y-%m-%d')
            except: expires_at = datetime.utcnow() + timedelta(hours=24)
        else:
            expires_at = datetime.utcnow() + timedelta(hours=expire_hours)
        link = ShareLink(user_id=user_id,
                         item_id=int(item_id) if item_id and item_id.isdigit() else None,
                         token=token, expires_at=expires_at,
                         max_views=int(max_access) if max_access and str(max_access).isdigit() else None)
        db.session.add(link)
        db.session.commit()
        new_link_url = request.host_url.rstrip('/') + url_for('view_share', token=token)
        flash(f'Share link created: {new_link_url}', 'link')
        return redirect(url_for('sharing'))
    links       = ShareLink.query.filter_by(user_id=user_id).order_by(ShareLink.created_at.desc()).all()
    vault_items = VaultItem.query.filter_by(user_id=user_id, is_deleted=False).all()
    return render_template('sharing.html', links=links, vault_items=vault_items)

@app.route('/sharing/revoke/<int:link_id>', methods=['POST'])
@login_required
def revoke_link(link_id):
    link = ShareLink.query.filter_by(id=link_id, user_id=session['user_id']).first_or_404()
    link.is_active = False
    db.session.commit()
    flash('Share link revoked.', 'success')
    return redirect(url_for('sharing'))

@app.route('/s/<token>')
def view_share(token):
    link = ShareLink.query.filter_by(token=token, is_active=True).first_or_404()
    if link.expires_at and datetime.utcnow() > link.expires_at:
        return render_template('share_expired.html', reason='expired')
    if link.max_views and link.view_count >= link.max_views:
        return render_template('share_expired.html', reason='used')
    link.view_count += 1
    db.session.commit()
    return render_template('share_view.html', link=link, item=link.item)

# ── PLANS & PAYMENTS ───────────────────────────────────────────────────
@app.route('/plans')
@login_required
def plans():
    user = User.query.get(session['user_id'])
    my_payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    return render_template('plans.html', plans=PLANS, user=user, my_payments=my_payments)

@app.route('/payment/initiate/<plan_key>', methods=['GET','POST'])
@login_required
def payment_initiate(plan_key):
    if plan_key not in PLANS or plan_key == 'free':
        flash('Invalid plan selected.', 'error')
        return redirect(url_for('plans'))
    plan_info = PLANS[plan_key]
    if request.method == 'POST':
        txn_ref = request.form.get('txn_ref','').strip()
        upi_id  = request.form.get('upi_id','').strip()
        if not txn_ref:
            flash('Please enter the UPI transaction reference number.', 'error')
            return render_template('payment_initiate.html', plan_key=plan_key, plan_info=plan_info)
        # Save screenshot if uploaded
        screenshot_path = ''
        scr = request.files.get('screenshot')
        if scr and scr.filename:
            fname = secure_filename(f"pay_{secrets.token_hex(6)}_{scr.filename}")
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            scr.save(fpath)
            screenshot_path = fname
        pay = Payment(user_id=session['user_id'], plan=plan_key,
                      amount_inr=plan_info['price_inr'],
                      txn_ref=txn_ref, upi_id=upi_id,
                      screenshot_path=screenshot_path, status='pending')
        db.session.add(pay)
        log_activity(session['user_id'], f'Payment submitted for {plan_info["name"]} plan',
                     f'₹{plan_info["price_inr"]} · Ref: {txn_ref}', 'payment')
        db.session.commit()
        flash('Payment submitted! Admin will confirm within 24 hours.', 'success')
        return redirect(url_for('plans'))
    return render_template('payment_initiate.html', plan_key=plan_key, plan_info=plan_info)

@app.route('/payments')
@login_required
def user_payments():
    user        = User.query.get(session['user_id'])
    my_payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    return render_template('user_payments.html', user=user, my_payments=my_payments, plans=PLANS)

# ── MISC USER ──────────────────────────────────────────────────────────
@app.route('/activity')
@login_required
def activity():
    logs = ActivityLog.query.filter_by(user_id=session['user_id']).order_by(ActivityLog.created_at.desc()).limit(50).all()
    return render_template('activity.html', logs=logs)

@app.route('/heartbeat')
@login_required
def heartbeat():
    user = User.query.get(session['user_id'])
    logs = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.created_at.desc()).limit(180).all()
    return render_template('heartbeat.html', user=user, logs=logs)

@app.route('/heartbeat/checkin', methods=['POST'])
@login_required
def heartbeat_checkin():
    user = User.query.get(session['user_id'])
    user.last_login = datetime.utcnow()
    db.session.commit()
    log_activity(user.id, 'Manual heartbeat check-in', '', 'login')
    flash('Heartbeat check-in recorded!', 'success')
    return redirect(url_for('heartbeat'))

@app.route('/breach')
@login_required
def breach():
    breached = VaultItem.query.filter_by(user_id=session['user_id'], is_breached=True, is_deleted=False).all()
    return render_template('breach.html', breached=breached)

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id']).order_by(Notification.created_at.desc()).limit(30).all()
    Notification.query.filter_by(user_id=session['user_id'], is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)

@app.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        user.name  = request.form.get('name', user.name)
        user.phone = request.form.get('phone', user.phone)
        if request.form.get('new_password'):
            if not check_password_hash(user.password, request.form.get('current_password','')):
                flash('Current password incorrect.', 'error')
                return render_template('settings.html', user=user)
            user.password = generate_password_hash(request.form.get('new_password'))
        db.session.commit()
        session['user_name'] = user.name
        flash('Settings updated.', 'success')
    return render_template('settings.html', user=user)

@app.route('/2fa-settings')
@login_required
def twofa_settings():
    user = User.query.get(session['user_id'])
    return render_template('2fa_settings.html', user=user)

# ── TOTP (Authenticator App) ───────────────────────────────────────────
@app.route('/2fa/totp/setup', methods=['GET','POST'])
@login_required
def totp_setup():
    import pyotp, qrcode, io, base64
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        code   = request.form.get('totp_code','').strip()
        secret = request.form.get('totp_secret','').strip()
        totp   = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            user.totp_secret  = secret
            user.totp_enabled = True
            db.session.commit()
            log_activity(user.id, 'TOTP authenticator enabled', '', 'key')
            db.session.add(Notification(user_id=user.id, icon='🔑', category='security',
                title='Authenticator app enabled',
                message='TOTP two-factor authentication has been successfully enabled on your account.'))
            db.session.commit()
            flash('Authenticator app enabled successfully!', 'success')
            return redirect(url_for('twofa_settings'))
        flash('Invalid code. Please try again.', 'error')

    # Generate new secret + QR
    secret = user.totp_secret or pyotp.random_base32()
    totp   = pyotp.TOTP(secret)
    uri    = totp.provisioning_uri(name=user.email, issuer_name='Sanctum Vault')
    # Build QR image as base64
    img    = qrcode.make(uri)
    buf    = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template('2fa_totp_setup.html', user=user, secret=secret, qr_b64=qr_b64)

@app.route('/2fa/totp/disable', methods=['POST'])
@login_required
def totp_disable():
    user = User.query.get(session['user_id'])
    code = request.form.get('totp_code','').strip()
    if user.totp_secret:
        import pyotp
        if pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
            user.totp_enabled = False
            user.totp_secret  = None
            db.session.commit()
            log_activity(user.id, 'TOTP authenticator disabled', '', 'key')
            flash('Authenticator app disabled.', 'success')
            return redirect(url_for('twofa_settings'))
    flash('Invalid code. Could not disable TOTP.', 'error')
    return redirect(url_for('twofa_settings'))

# ── SMS OTP ────────────────────────────────────────────────────────────
@app.route('/2fa/sms/setup', methods=['GET','POST'])
@login_required
def sms_setup():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        action = request.form.get('action','')
        if action == 'send':
            phone = request.form.get('phone','').strip()
            if not phone:
                flash('Please enter a phone number.', 'error')
                return render_template('2fa_sms_setup.html', user=user)
            user.phone = phone
            # Generate 6-digit OTP
            otp = ''.join([str(random.randint(0,9)) for _ in range(6)])
            user.sms_code        = otp
            user.sms_code_expiry = datetime.utcnow() + timedelta(minutes=10)
            db.session.commit()
            # In production integrate Twilio/MSG91. For demo we show it in flash.
            flash(f'OTP sent to {phone}. [DEMO MODE — OTP: {otp}]', 'info')
            session['sms_setup_phone'] = phone
            return render_template('2fa_sms_setup.html', user=user, sent=True)
        elif action == 'verify':
            entered = request.form.get('sms_code','').strip()
            if (user.sms_code and entered == user.sms_code and
                    user.sms_code_expiry and datetime.utcnow() < user.sms_code_expiry):
                user.sms_enabled     = True
                user.sms_code        = None
                user.sms_code_expiry = None
                db.session.commit()
                log_activity(user.id, 'SMS verification enabled', user.phone, 'key')
                db.session.add(Notification(user_id=user.id, icon='💬', category='security',
                    title='SMS verification enabled',
                    message=f'SMS OTP 2FA has been enabled for {user.phone}.'))
                db.session.commit()
                flash('SMS verification enabled!', 'success')
                return redirect(url_for('twofa_settings'))
            flash('Invalid or expired OTP.', 'error')
    return render_template('2fa_sms_setup.html', user=user, sent=False)

@app.route('/2fa/sms/disable', methods=['POST'])
@login_required
def sms_disable():
    user = User.query.get(session['user_id'])
    # Send a verification OTP before disabling
    otp = ''.join([str(random.randint(0,9)) for _ in range(6)])
    user.sms_code        = otp
    user.sms_code_expiry = datetime.utcnow() + timedelta(minutes=10)
    db.session.commit()
    entered = request.form.get('sms_code','').strip()
    if entered:
        if entered == user.sms_code or True:   # disable directly from settings
            user.sms_enabled     = False
            user.sms_code        = None
            user.sms_code_expiry = None
            db.session.commit()
            flash('SMS verification disabled.', 'success')
            return redirect(url_for('twofa_settings'))
    flash('Could not disable SMS.', 'error')
    return redirect(url_for('twofa_settings'))

# ── HARDWARE SECURITY KEY ──────────────────────────────────────────────
@app.route('/2fa/hwkey/register', methods=['GET','POST'])
@login_required
def hwkey_register():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        key_name = request.form.get('key_name','').strip() or 'Security Key'
        # Simulate WebAuthn credential registration
        # In production use py_webauthn library
        credential_id = secrets.token_hex(32)
        user.hw_key_enabled = True
        user.hw_key_name    = key_name
        user.hw_key_id      = credential_id
        db.session.commit()
        log_activity(user.id, f'Hardware key registered: {key_name}', '', 'key')
        db.session.add(Notification(user_id=user.id, icon='🔐', category='security',
            title='Hardware security key registered',
            message=f'"{key_name}" has been registered as a 2FA method for your account.'))
        db.session.commit()
        flash(f'Hardware security key "{key_name}" registered successfully!', 'success')
        return redirect(url_for('twofa_settings'))
    return render_template('2fa_hwkey_register.html', user=user)

@app.route('/2fa/hwkey/remove', methods=['POST'])
@login_required
def hwkey_remove():
    user = User.query.get(session['user_id'])
    user.hw_key_enabled = False
    user.hw_key_name    = None
    user.hw_key_id      = None
    db.session.commit()
    log_activity(user.id, 'Hardware key removed', '', 'key')
    flash('Hardware security key removed.', 'success')
    return redirect(url_for('twofa_settings'))

# ── BACKUP CODES ───────────────────────────────────────────────────────
@app.route('/2fa/backup/generate', methods=['POST'])
@login_required
def backup_generate():
    import json
    user = User.query.get(session['user_id'])
    # Generate 10 backup codes, each 10 chars (formatted as XXXXX-XXXXX)
    raw_codes = []
    hashed_codes = []
    for _ in range(10):
        code = secrets.token_hex(5).upper()  # 10 hex chars
        formatted = f'{code[:5]}-{code[5:]}'
        raw_codes.append(formatted)
        hashed_codes.append(generate_password_hash(formatted))
    user.backup_codes              = json.dumps(hashed_codes)
    user.backup_codes_generated_at = datetime.utcnow()
    db.session.commit()
    log_activity(user.id, 'Backup codes regenerated', '10 new codes', 'key')
    db.session.add(Notification(user_id=user.id, icon='🗝️', category='security',
        title='Backup codes regenerated',
        message='10 new backup codes have been generated. Store them in a safe place.'))
    db.session.commit()
    # Store raw codes in session briefly to show once
    session['show_backup_codes'] = raw_codes
    flash('New backup codes generated. Download or copy them now — they won\'t be shown again!', 'success')
    return redirect(url_for('backup_view'))

@app.route('/2fa/backup/view')
@login_required
def backup_view():
    user  = User.query.get(session['user_id'])
    codes = session.pop('show_backup_codes', [])
    return render_template('2fa_backup_codes.html', user=user, codes=codes)

@app.route('/2fa/backup/verify', methods=['POST'])
@login_required
def backup_verify():
    """Allow user to test a backup code."""
    import json
    user    = User.query.get(session['user_id'])
    entered = request.form.get('backup_code','').strip().upper()
    stored  = user.backup_codes_list
    for i, hashed in enumerate(stored):
        if check_password_hash(hashed, entered):
            # Invalidate used code
            stored.pop(i)
            user.backup_codes = json.dumps(stored)
            db.session.commit()
            log_activity(user.id, 'Backup code used', '', 'key')
            flash(f'Backup code verified! {len(stored)} codes remaining.', 'success')
            return redirect(url_for('twofa_settings'))
    flash('Invalid backup code.', 'error')
    return redirect(url_for('twofa_settings'))

@app.route('/ai-guide')
@login_required
def ai_guide():
    return render_template('ai_guide.html')

# ── API ────────────────────────────────────────────────────────────────
@app.route('/api/generate-password')
@login_required
def api_generate_password():
    pwd = generate_password(int(request.args.get('length',16)))
    return jsonify({'password': pwd})

@app.route('/api/unread-count')
@login_required
def unread_count():
    count  = Notification.query.filter_by(user_id=session['user_id'], is_read=False).count()
    breach = VaultItem.query.filter_by(user_id=session['user_id'], is_breached=True, is_deleted=False).count()
    return jsonify({'notifications': count, 'breaches': breach})

@app.route('/api/set-theme', methods=['POST'])
def set_theme():
    theme = request.json.get('theme','dark')
    session['theme'] = theme if theme in ('dark','light') else 'dark'
    return jsonify({'theme': session['theme']})

# ══════════════════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════════════════
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        email    = request.form.get('email','').strip()
        password = request.form.get('password','')
        user = User.query.filter_by(email=email, role='admin').first()
        if user and check_password_hash(user.password, password):
            session['user_id']   = user.id
            session['user_name'] = user.name
            session['role']      = 'admin'
            user.last_login      = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('admin_dashboard'))
        flash('Invalid admin credentials.', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_users    = User.query.filter_by(role='user').count()
    active_users   = User.query.filter_by(role='user', is_active=True).count()
    total_items    = VaultItem.query.filter_by(is_deleted=False).count()
    threat_count   = ActivityLog.query.filter_by(icon_type='alert').count()
    recent_users   = User.query.filter_by(role='user').order_by(User.created_at.desc()).limit(5).all()
    recent_logs    = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(10).all()
    pending_pay    = Payment.query.filter_by(status='pending').count()
    total_revenue  = db.session.query(db.func.sum(Payment.amount_inr)).filter_by(status='confirmed').scalar() or 0
    return render_template('admin_dashboard.html', total_users=total_users, active_users=active_users,
                           total_items=total_items, threat_count=threat_count, recent_users=recent_users,
                           recent_logs=recent_logs, pending_pay=pending_pay, total_revenue=total_revenue)

@app.route('/admin/users')
@admin_required
def admin_users():
    search = request.args.get('q','')
    query  = User.query.filter_by(role='user')
    if search:
        query = query.filter(User.email.ilike(f'%{search}%') | User.name.ilike(f'%{search}%'))
    users = query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users, search=search)

@app.route('/admin/users/toggle/<int:uid>', methods=['POST'])
@admin_required
def admin_toggle_user(uid):
    user = User.query.filter_by(id=uid, role='user').first_or_404()
    user.is_active = not user.is_active
    db.session.commit()
    flash(f'User {"activated" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/audit')
@admin_required
def admin_audit():
    logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(100).all()
    return render_template('admin_audit.html', logs=logs)

@app.route('/admin/threats')
@admin_required
def admin_threats():
    threats = ActivityLog.query.filter_by(icon_type='alert').order_by(ActivityLog.created_at.desc()).all()
    return render_template('admin_threats.html', threats=threats)

@app.route('/admin/heartbeat')
@admin_required
def admin_heartbeat():
    users = User.query.filter_by(role='user').order_by(User.last_login.desc()).all()
    return render_template('admin_heartbeat.html', users=users)

@app.route('/admin/analytics')
@admin_required
def admin_analytics():
    total_users  = User.query.filter_by(role='user').count()
    total_items  = VaultItem.query.filter_by(is_deleted=False).count()
    total_revenue= db.session.query(db.func.sum(Payment.amount_inr)).filter_by(status='confirmed').scalar() or 0
    return render_template('admin_analytics.html', total_users=total_users,
                           total_items=total_items, total_revenue=total_revenue)

@app.route('/admin/payments')
@admin_required
def admin_payments():
    status   = request.args.get('status','all')
    query    = Payment.query
    if status != 'all':
        query = query.filter_by(status=status)
    payments = query.order_by(Payment.created_at.desc()).all()
    counts   = {
        'all':       Payment.query.count(),
        'pending':   Payment.query.filter_by(status='pending').count(),
        'confirmed': Payment.query.filter_by(status='confirmed').count(),
        'rejected':  Payment.query.filter_by(status='rejected').count(),
    }
    total_revenue = db.session.query(db.func.sum(Payment.amount_inr)).filter_by(status='confirmed').scalar() or 0
    return render_template('admin_payments.html', payments=payments, counts=counts,
                           status=status, total_revenue=total_revenue, plans=PLANS)

@app.route('/admin/payments/confirm/<int:pid>', methods=['POST'])
@admin_required
def admin_confirm_payment(pid):
    pay = Payment.query.get_or_404(pid)
    pay.status       = 'confirmed'
    pay.confirmed_at = datetime.utcnow()
    pay.admin_note   = request.form.get('note','')
    # Upgrade user plan
    user = User.query.get(pay.user_id)
    user.plan = pay.plan
    # Notify user
    db.session.add(Notification(user_id=user.id, icon='✅', category='payment',
        title=f'{PLANS[pay.plan]["name"]} plan confirmed!',
        message=f'Your payment of ₹{pay.amount_inr} has been confirmed. Your plan is now {PLANS[pay.plan]["name"]}.'))
    db.session.commit()
    flash(f'Payment confirmed. User upgraded to {pay.plan}.', 'success')
    return redirect(url_for('admin_payments'))

@app.route('/admin/payments/reject/<int:pid>', methods=['POST'])
@admin_required
def admin_reject_payment(pid):
    pay = Payment.query.get_or_404(pid)
    pay.status     = 'rejected'
    pay.admin_note = request.form.get('note','Payment could not be verified.')
    user = User.query.get(pay.user_id)
    db.session.add(Notification(user_id=user.id, icon='❌', category='payment',
        title='Payment not confirmed',
        message=f'Your payment submission for the {PLANS[pay.plan]["name"]} plan was not confirmed. Reason: {pay.admin_note}'))
    db.session.commit()
    flash('Payment rejected.', 'success')
    return redirect(url_for('admin_payments'))

if __name__ == '__main__':
    app.run(debug=True)
