# jellyburn

A GTK3 desktop app for Linux to browse your Jellyfin music library, build playlists, and burn them directly to audio CD.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)
![Status](https://img.shields.io/badge/status-alpha-orange)

## Features

- Connects to any Jellyfin server (API key auth)
- Browse and search your music library by title, artist or album
- Album art display from Jellyfin
- Playback via `mpv` with now-playing info and progress bar
- Playlist builder with track numbers, save/load as JSON
- Real-time CD capacity bar (green → yellow → red, max. 74 min)
- Burn directly to audio CD via `wodim` — no extra steps
- Detects missing system dependencies on startup

## Requirements

System packages:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 mpv ffmpeg wodim
```

Python 3.10 or newer. The only Python dependency (`requests`) is installed automatically.

## Installation

```bash
pip install jellyburn
```

Or run from source:

```bash
git clone https://github.com/oemerhamzaoglu/jellyburn
cd jellyburn
pip install -e .
jellyburn
```

## Setup

1. Click the settings icon (top right)
2. Enter your Jellyfin server URL, e.g. `https://jellyfin.example.com`
3. Enter an API key — Jellyfin Dashboard → Administration → API Keys → New
4. Check CD device (default: `/dev/sr0`)
5. Save — the app connects and loads your library

Config is stored in `~/.config/jellyburn.json` (no passwords saved).

## Usage

| Action | How |
|---|---|
| Search | Type in the search bar — filters by title, artist, album |
| Play | Double-click a track in the library, or select + press play |
| Add to playlist | Select one or more tracks (Ctrl+click), then "+ Auswahl hinzufügen" |
| Reorder playlist | Drag and drop (planned, see issue tracker) |
| Save/load playlist | Use the open/save icons in the playlist header |
| Remove from playlist | Right-click in the playlist |
| Burn | Click "● CD BRENNEN" when your playlist is ready |

The CD capacity bar turns yellow above 85 % and red when the playlist exceeds 74 minutes.

## Burn process

1. Tracks are downloaded from Jellyfin one by one
2. Each track is converted to WAV (44100 Hz, 16-bit stereo) via `ffmpeg`
3. All WAV files are written to CD as an audio disc via `wodim`

Temporary files in `/tmp/jellyfin_burn_*/` are cleaned up automatically.

## Verify your CD drive

```bash
wodim dev=/dev/sr0 -checkdrive
```

## Contributing

Open an issue before starting larger changes. PRs welcome.

## License

MIT — see [LICENSE](LICENSE)
