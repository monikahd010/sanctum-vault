from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(200), unique=True, nullable=False)
    password      = db.Column(db.String(300), nullable=False)
    phone         = db.Column(db.String(30),  default='')
    role          = db.Column(db.String(20),  default='user')   # user | admin
    plan          = db.Column(db.String(30),  default='free')   # free | pro | enterprise
    is_active     = db.Column(db.Boolean,     default=True)
    last_login    = db.Column(db.DateTime,    nullable=True)
    heartbeat_interval = db.Column(db.Integer, default=30)      # days
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)

    # ── 2FA fields ──
    totp_secret      = db.Column(db.String(64),  nullable=True)   # TOTP secret (base32)
    totp_enabled     = db.Column(db.Boolean,     default=False)
    sms_enabled      = db.Column(db.Boolean,     default=False)
    sms_code         = db.Column(db.String(10),  nullable=True)   # current OTP sent via SMS
    sms_code_expiry  = db.Column(db.DateTime,    nullable=True)
    hw_key_enabled   = db.Column(db.Boolean,     default=False)
    hw_key_name      = db.Column(db.String(100), nullable=True)   # e.g. "YubiKey 5"
    hw_key_id        = db.Column(db.String(200), nullable=True)   # simulated credential id
    backup_codes     = db.Column(db.Text,        nullable=True)   # JSON list of hashed codes
    backup_codes_generated_at = db.Column(db.DateTime, nullable=True)

    vault_items   = db.relationship('VaultItem',   backref='user', lazy=True)
    beneficiaries = db.relationship('Beneficiary', backref='user', lazy=True)
    share_links   = db.relationship('ShareLink',   backref='user', lazy=True)
    activity_logs = db.relationship('ActivityLog', backref='user', lazy=True)
    notifications = db.relationship('Notification',backref='user', lazy=True)
    payments      = db.relationship('Payment',     backref='user', lazy=True)

    @property
    def initials(self):
        parts = self.name.strip().split()
        return (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else self.name[:2].upper()

    @property
    def days_since_login(self):
        if not self.last_login:
            return None
        return (datetime.utcnow() - self.last_login).days

    @property
    def heartbeat_status(self):
        if not self.last_login:
            return 'unknown'
        days = self.days_since_login
        if days is None:        return 'unknown'
        if days <= 1:           return 'active'
        if days <= self.heartbeat_interval: return 'idle'
        return 'inactive'

    @property
    def active_2fa_count(self):
        return sum([self.totp_enabled, self.sms_enabled, self.hw_key_enabled])

    @property
    def backup_codes_list(self):
        if not self.backup_codes:
            return []
        try:
            return json.loads(self.backup_codes)
        except Exception:
            return []


class VaultItem(db.Model):
    __tablename__ = 'vault_items'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name            = db.Column(db.String(200), nullable=False)
    item_type       = db.Column(db.String(30),  default='password')
    username        = db.Column(db.String(200), default='')
    encrypted_value = db.Column(db.Text,        default='')
    url             = db.Column(db.String(500), default='')
    notes           = db.Column(db.Text,        default='')
    file_name       = db.Column(db.String(300), default='')
    file_path       = db.Column(db.String(500), default='')
    file_size       = db.Column(db.Integer,     default=0)
    file_mime       = db.Column(db.String(100), default='')
    is_breached     = db.Column(db.Boolean,     default=False)
    is_deleted      = db.Column(db.Boolean,     default=False)
    created_at      = db.Column(db.DateTime,    default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    TYPE_ICONS = {'password':'🔑','document':'📄','note':'🗒️','card':'💳','identity':'🪪'}

    @property
    def icon(self):
        return self.TYPE_ICONS.get(self.item_type, '📦')

    @property
    def age_label(self):
        diff = datetime.utcnow() - self.updated_at
        if diff.days == 0:  return 'Today'
        if diff.days == 1:  return 'Yesterday'
        return f'{diff.days} days ago'

    @property
    def file_size_label(self):
        if not self.file_size: return ''
        if self.file_size < 1024:      return f'{self.file_size} B'
        if self.file_size < 1048576:   return f'{self.file_size//1024} KB'
        return f'{self.file_size//1048576} MB'


class Beneficiary(db.Model):
    __tablename__ = 'beneficiaries'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    email        = db.Column(db.String(200), nullable=False)
    relationship = db.Column(db.String(100), default='')
    wait_years   = db.Column(db.Integer, default=0)
    wait_months  = db.Column(db.Integer, default=0)
    wait_days    = db.Column(db.Integer, default=2)
    wait_hours   = db.Column(db.Integer, default=0)
    wait_until   = db.Column(db.DateTime, nullable=True)
    status       = db.Column(db.String(20), default='pending')
    created_at   = db.Column(db.DateTime,  default=datetime.utcnow)

    @property
    def initials(self):
        parts = self.name.strip().split()
        return (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else self.name[:2].upper()

    @property
    def wait_label(self):
        if self.wait_until:
            return f'Until {self.wait_until.strftime("%b %d, %Y")}'
        parts = []
        if self.wait_years:  parts.append(f'{self.wait_years} yr{"s" if self.wait_years>1 else ""}')
        if self.wait_months: parts.append(f'{self.wait_months} mo')
        if self.wait_days:   parts.append(f'{self.wait_days} day{"s" if self.wait_days>1 else ""}')
        if self.wait_hours:  parts.append(f'{self.wait_hours} hr{"s" if self.wait_hours>1 else ""}')
        return ', '.join(parts) if parts else 'Immediate'


class ShareLink(db.Model):
    __tablename__ = 'share_links'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    item_id    = db.Column(db.Integer, db.ForeignKey('vault_items.id'), nullable=True)
    token      = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    max_views  = db.Column(db.Integer, nullable=True)
    view_count = db.Column(db.Integer, default=0)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship('VaultItem', foreign_keys=[item_id])

    @property
    def status(self):
        if not self.is_active: return 'revoked'
        if self.expires_at and datetime.utcnow() > self.expires_at: return 'expired'
        if self.max_views and self.view_count >= self.max_views: return 'used'
        return 'active'

    @property
    def expires_label(self):
        if not self.expires_at: return 'Never'
        diff = self.expires_at - datetime.utcnow()
        if diff.total_seconds() < 0: return 'Expired'
        if diff.days == 0: return f'{int(diff.total_seconds()/3600)}h left'
        return f'{diff.days}d left'


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action     = db.Column(db.String(200), nullable=False)
    detail     = db.Column(db.String(300), default='')
    icon_type  = db.Column(db.String(30),  default='login')
    ip         = db.Column(db.String(50),  default='')
    device     = db.Column(db.String(150), default='')
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

    ICON_MAP = {'login':'🔑','upload':'⬆️','share':'🔗','alert':'⚠️','key':'🗝️','ai':'🤖','payment':'💳'}

    @property
    def icon(self):
        return self.ICON_MAP.get(self.icon_type, '📋')

    @property
    def time_ago(self):
        diff = datetime.utcnow() - self.created_at
        if diff.total_seconds() < 60:   return 'Just now'
        if diff.total_seconds() < 3600: return f'{int(diff.total_seconds()/60)}m ago'
        if diff.days == 0:              return f'{int(diff.total_seconds()/3600)}h ago'
        return f'{diff.days}d ago'


class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text,        default='')
    icon       = db.Column(db.String(10),  default='🔔')
    category   = db.Column(db.String(30),  default='general')
    is_read    = db.Column(db.Boolean,     default=False)
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

    @property
    def time_ago(self):
        diff = datetime.utcnow() - self.created_at
        if diff.total_seconds() < 3600: return f'{int(diff.total_seconds()/60)}m ago'
        if diff.days == 0:              return f'{int(diff.total_seconds()/3600)}h ago'
        if diff.days < 7:               return f'{diff.days} days ago'
        return f'{diff.days//7} week(s) ago'


# ── PLAN DEFINITIONS (used across app) ──
PLANS = {
    'free':       {'name':'Free',       'price':0,    'price_inr':0,    'items':50,   'storage':'100 MB', 'color':'gray',   'badge':'Free'},
    'pro':        {'name':'Pro',        'price':4.99, 'price_inr':399,  'items':500,  'storage':'5 GB',   'color':'blue',   'badge':'Pro'},
    'enterprise': {'name':'Enterprise', 'price':9.99, 'price_inr':799,  'items':9999, 'storage':'50 GB',  'color':'purple', 'badge':'Enterprise'},
}


class Payment(db.Model):
    __tablename__ = 'payments'
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan           = db.Column(db.String(30),  nullable=False)
    amount_inr     = db.Column(db.Integer,     nullable=False)        # paise or rupees
    txn_ref        = db.Column(db.String(100), default='')            # user-entered UPI ref
    upi_id         = db.Column(db.String(100), default='')
    status         = db.Column(db.String(20),  default='pending')     # pending|confirmed|rejected
    admin_note     = db.Column(db.String(300), default='')
    screenshot_path= db.Column(db.String(500), default='')
    created_at     = db.Column(db.DateTime,    default=datetime.utcnow)
    confirmed_at   = db.Column(db.DateTime,    nullable=True)

    @property
    def plan_info(self):
        return PLANS.get(self.plan, {})

    @property
    def status_badge(self):
        return {'pending':'amber','confirmed':'green','rejected':'red'}.get(self.status,'gray')

    @property
    def time_ago(self):
        diff = datetime.utcnow() - self.created_at
        if diff.days == 0:  return f'{int(diff.total_seconds()/3600)}h ago'
        return f'{diff.days}d ago'
