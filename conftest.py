"""
pytest configuration and test harness isolation (WP0.1 B / Rule 10).
Guarantees that test sessions:
  1. Never send Telegram, Discord, desktop or webhook alerts (stubs with recording fake).
  2. Clear TELEGRAM_* and webhook credentials from the test environment.
  3. Block outbound socket network connections unless explicitly flagged.
  4. Ensure ALERTS_ENABLED defaults to False.
"""

import os
import socket
import pytest

class BlockedNetworkCallError(RuntimeError):
    """Raised when test code attempts an unauthorized outbound network connection."""
    pass

class AlertRecorder:
    """Recording fake for alert and notification calls during test sessions."""
    def __init__(self):
        self.recorded_calls = []

    def dispatch_alert(self, *args, **kwargs):
        self.recorded_calls.append({"type": "dispatch_alert", "args": args, "kwargs": kwargs})

    def send_desktop_notification(self, *args, **kwargs):
        self.recorded_calls.append({"type": "send_desktop_notification", "args": args, "kwargs": kwargs})

    def clear(self):
        self.recorded_calls.clear()

# Global singleton recorder accessible by tests
ALERT_RECORDER = AlertRecorder()

# Save original socket.connect
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect

def _guarded_socket_connect(self, address):
    # Allow local IPC loopback if explicitly opted-in
    if getattr(self, "_allow_test_network", False) or getattr(socket, "_allow_test_network", False):
        return _ORIGINAL_SOCKET_CONNECT(self, address)
    raise BlockedNetworkCallError(
        f"Outbound network connection blocked by test harness: connect to {address}. "
        "All tests must run 100% offline without external network access (Rule 10)."
    )

def install_test_network_and_alert_guards():
    """Installs network blocking and alert stubbing into the active process."""
    # 1. Clear credential environment variables
    for var in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "WEBHOOK_URL"]:
        os.environ.pop(var, None)
    os.environ["ALERTS_ENABLED"] = "false"

    # 2. Block outbound socket connections
    socket.socket.connect = _guarded_socket_connect

    # 3. Stub alert dispatchers in notifier and main
    try:
        import notifier
        notifier.dispatch_alert = ALERT_RECORDER.dispatch_alert
        notifier.send_desktop_notification = ALERT_RECORDER.send_desktop_notification
    except Exception:
        pass

    try:
        import main
        main.dispatch_alert = ALERT_RECORDER.dispatch_alert
    except Exception:
        pass

# Automatically install guards on import
install_test_network_and_alert_guards()

@pytest.fixture(autouse=True, scope="session")
def isolate_test_session():
    """Session-level autouse fixture to enforce offline isolated test execution."""
    install_test_network_and_alert_guards()
    yield
    # Restore original socket connect upon test session completion
    socket.socket.connect = _ORIGINAL_SOCKET_CONNECT

@pytest.fixture(autouse=True)
def reset_alert_recorder_each_test():
    """Resets the alert call log between each individual test."""
    ALERT_RECORDER.clear()
    yield

@pytest.fixture
def alert_recorder():
    """Provides test access to recorded alert events."""
    return ALERT_RECORDER
