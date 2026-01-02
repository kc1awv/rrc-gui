# RRC GUI Client

A standalone graphical user interface client for RRC (Reticulum Relay Chat).

#### Under heavy development. Expect bugs and incomplete features.

## Installation

```bash
pip install -e .
```

### Development Installation

```bash
pip install -e .[dev]
```



## Usage

```bash
rrc-gui
```

On first run, the application will create a default configuration file at
`~/.rrc/gui_config.json`.

### Logging

By default, the application logs at INFO level. To enable debug logging for
troubleshooting:

```bash
RRC_LOG_LEVEL=DEBUG rrc-gui
```

Valid log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Configuration File

The default configuration file is located at `~/.rrc/gui_config.json`. You can
override this location:

```bash
RRC_GUI_CONFIG=/path/to/custom/config.json rrc-gui
```

## Configuration

The configuration file supports:

- Default hub connection settings
- Identity file path
- Nickname
- Auto-join room
- Theme colors
- Window size and position

## Slash Commands

rrc-gui supports slash commands for both client-side actions and server
administration with rrcd.

**Client-side commands:**
- `/ping` - Test connection latency to the server

**Server-side commands** (sent to rrcd for processing):
- `/stats`, `/reload`, `/who`, `/kline` - Server operator commands
- `/topic`, `/mode`, `/kick`, `/ban`, `/invite` - Room moderation commands
- And many more...

## Requirements

- Python 3.11+
- wxPython 4.2+
- Reticulum (RNS) 1.0+
- cbor2 5.6+

## License

MIT License - see LICENSE file for details.
