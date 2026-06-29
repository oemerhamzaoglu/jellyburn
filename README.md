# jellyburn
<<<<<<< HEAD

A GTK3 music player for Jellyfin with CD burning support - browse your library, build a playlist, burn it to CD. All on Linux, no proprietary dependencies.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)
![Status](https://img.shields.io/badge/status-alpha-orange)

## Features

- Connects to any Jellyfin server (local or remote via HTTPS)
- Browse and search your music library
- Playback via `mpv`
- Build playlists with real-time CD capacity indicator (max. 74 min)
- Burn directly to CD via `wodim` - no intermediate steps

## Requirements

System packages (install once):

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 mpv ffmpeg wodim
```

## Installation

```bash
pip install jellyburn
```

## Run

```bash
jellyburn
```

Or without installing:

```bash
git clone https://github.com/oemeraky/jellyburn
cd jellyburn
pip install -e .
jellyburn
```

## Setup

1. Click the settings icon (top right)
2. Enter your Jellyfin server URL, e.g. `https://jellyfin.example.com`
3. Enter an API key (Jellyfin Dashboard -> Administration -> API Keys -> New)
4. Check CD device (default: `/dev/sr0`)
5. Save and connect

Config is stored in `~/.config/jellyburn.json`.

## Usage

- **Search** - type to filter by title, artist or album
- **Play** - double-click a track, or select + play button (requires `mpv`)
- **Add to playlist** - select one or more tracks (Ctrl+click), then click the add button
- **Remove from playlist** - right-click in the playlist
- **Burn** - click "CD brennen" when your playlist is ready

The CD bar turns red if the playlist exceeds 74 minutes.

## Burn process

1. Tracks are downloaded from Jellyfin
2. Converted to WAV (44100 Hz, stereo) via `ffmpeg`
3. Written to CD as audio disc via `wodim`

Temporary files are cleaned up automatically.

## Verify your CD drive

```bash
wodim dev=/dev/sr0 -checkdrive
```

## Contributing

PRs welcome. Please open an issue first for larger changes.

## License

MIT - see [LICENSE](LICENSE)
=======
GTK3 music player for Jellyfin with CD burning support: browse your library, build a playlist, burn it to disc.
>>>>>>> bb5c7e10716ec4e038836f66b34c688a6a3adee9
