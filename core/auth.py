"""Optional password protection (bcrypt).

Protection is **opt-in**: the application has no password until the user
enables one from the in-app security dialog. When (and only when) a password
hash is stored in ``settings.password_hash`` the login dialog gates startup.

This module holds pure logic only (no Qt); the dialogs live in the ``ui``
package. The admin hash provides a recovery path if the user forgets their
password (admin password: ``PHMadmin2026!``).
"""

import logging

import bcrypt

from core.database import Database

logger = logging.getLogger(__name__)

SETTING_PASSWORD_HASH = "password_hash"
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 30
MIN_PASSWORD_LENGTH = 4

# Hardcoded admin hash — recovery path. Admin password: PHMadmin2026!
_ADMIN_HASH = "$2b$12$XjeAf7ZdL6grdVHdRssqJOyf0I8eRn0Ufr0MnBtN44ukjek43/8LS"


def hash_password(password: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return True if the password matches the stored bcrypt hash."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def verify_admin(password: str) -> bool:
    """Return True if the password matches the hardcoded admin hash."""
    return verify_password(password, _ADMIN_HASH)


def is_protection_enabled(db: Database) -> bool:
    """Return True if a user password is currently set."""
    return bool(db.get_setting(SETTING_PASSWORD_HASH, ""))


def get_password_hash(db: Database) -> str:
    """Return the stored password hash ('' if protection is disabled)."""
    return db.get_setting(SETTING_PASSWORD_HASH, "")


def set_password(db: Database, password: str) -> None:
    """Enable/replace protection by storing a hash of the given password."""
    db.set_setting(SETTING_PASSWORD_HASH, hash_password(password))
    logger.info("Heslo aplikácie nastavené.")


def clear_password(db: Database) -> None:
    """Disable protection by clearing the stored hash."""
    db.set_setting(SETTING_PASSWORD_HASH, "")
    logger.info("Ochrana heslom vypnutá.")
