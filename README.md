# my-stickynotes

A stickynote app that remembers its workspace.

## Feature

- Save each note state:
  - Text content
  - Window location and size
  - Workspace each note is located
  - font that can be changed
  - color that can be changed
- Each note has own workspace

## Environment

- XUBUNTU 25.04
- Python 3.13
- tasktray: AppIndicator

## Requirements

See Requirements.txt
If using task tray, tasktray backend may be needed.

```bash
apt install libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1

```

I do not know what is needed. My machine already had them.
And in venv envrironment, my machine needs following setting

```cfg venv/pyvenv.cfg
include-system-site-packages = true
```

## Usage

``` python
python main.py # with task tray
python stickynotes.py # without task tray

```

## Todo

- The features of backup and general settigs.
