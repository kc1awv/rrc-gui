# RRC GUI Client

A standalone graphical user interface client for RRC (Reticulum Relay Chat).

This is a complete, self-contained GUI application for RRC. It includes all necessary
protocol implementation and does not depend on the rrc-client package.

## Features

- Connect to RRC hubs over Reticulum
- Multi-room chat with tab-based room switching
- Nickname support with identity-based recognition
- Message delivery tracking
- Customizable color themes (light/dark)
- System tray integration

## Installation

```bash
pip install -e .
```

## Usage

```bash
rrc-gui
```

On first run, the application will create a default configuration file at `~/.rrc-gui/config.json`.

## Configuration

The configuration file supports:

- Default hub connection settings
- Identity file path
- Nickname
- Auto-join room
- Theme colors
- Window size and position

## Requirements

- Python 3.11+
- wxPython 4.2+
- Reticulum (RNS) 0.8+
- cbor2 5.6+

## License

MIT License - see LICENSE file for details.
