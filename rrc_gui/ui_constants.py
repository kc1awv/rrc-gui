"""UI constants for RRC GUI."""

# UI sizing constants
ROOM_LIST_WIDTH = 150
USER_LIST_WIDTH = 180
BUTTON_WIDTH = 70
DEFAULT_BORDER = 5
DEFAULT_SPACING = 10

# Maximum messages to keep per room (prevent unbounded memory growth)
MAX_MESSAGES_PER_ROOM = 1000

# Timeout for pending messages (seconds) - mark as failed after this
PENDING_MESSAGE_TIMEOUT = 30.0

# Connection timeout (seconds)
CONNECTION_TIMEOUT = 30.0

# Maximum message length (characters)
MAX_MESSAGE_LENGTH = 4000

# Client-side rate limiting (messages per minute)
RATE_LIMIT_MESSAGES_PER_MINUTE = 60
RATE_LIMIT_WARNING_THRESHOLD = 0.8  # Warn at 80% of limit

# Input history size
INPUT_HISTORY_SIZE = 50
