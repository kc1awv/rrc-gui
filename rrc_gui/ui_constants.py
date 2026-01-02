"""UI constants for RRC GUI."""

# UI sizing constants
ROOM_LIST_WIDTH = 150
USER_LIST_WIDTH = 180
BUTTON_WIDTH = 70
DEFAULT_BORDER = 5
DEFAULT_SPACING = 10

# Maximum messages to keep per room (prevent unbounded memory growth)
MAX_MESSAGES_PER_ROOM = 1000

# Maximum number of parted rooms to keep message history for
MAX_PARTED_ROOMS_HISTORY = 10

# Timeout for pending messages (seconds) - mark as failed after this
PENDING_MESSAGE_TIMEOUT = 30.0

# Connection timeout (seconds)
CONNECTION_TIMEOUT = 30.0

# Maximum message length (characters)
MAX_MESSAGE_LENGTH = 256

# Client-side rate limiting (messages per minute)
RATE_LIMIT_MESSAGES_PER_MINUTE = 60
RATE_LIMIT_WARNING_THRESHOLD = 0.8  # Warn at 80% of limit

# Input history size
INPUT_HISTORY_SIZE = 50

# Timer intervals (milliseconds)
PENDING_CHECK_TIMER_INTERVAL = 5000
STATUS_UPDATE_TIMER_INTERVAL = 2000

# Maximum user last message cache entries
MAX_USER_LAST_MESSAGE_CACHE = 1000
