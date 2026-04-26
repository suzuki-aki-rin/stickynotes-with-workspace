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

- XUBUNTU 26.04
- Python 3.14
- tasktray: ayatana-appindicator, xfce4-indicator-plugin (I checked only this gtk environment)

## Requirements

- wmctrl --- Essential for changing workspace

``` bash
apt install wmctrl
```

- Python modules: See Requirements.txt
- See Systray section about systray backend.

### Systray

The tasktray backend of your system may be used when no systray backend is specified.

```python:main.py
# maybe systerm tasktray manager(backend) is used
# Can specify xorg for backend by the following code.
#But it does not respond for mouse click.
os.environ["PYSTRAY_BACKEND"] = "xorg"
```

- case: ayataka-appindicator(gtk backend)

1. if no ayataka backend, install it. These package may not enough.
My environment has already ayatana-appindicator and gi. I cannot confirm it.

```bash
# if using ayatana indicator for backend, the install may be:
apt install python3-gi gir1.2-appindicator3-0.1
```

1. set these packages so that they can be used in venv environment.
    1. modify pyvenv.cfg. or venv ---system-site-packages when making venv

    ```cfg:venv/pyvenv.cfg
    # false → true
    # include-system-site-packages = false
    include-system-site-packages = true
    ```

    1. make sybolic link to gi library

    ```bash
    # get location of gi
    python3 -c "import gi; print(gi.__file__)"
    # maybe /usr/lib/python3/dist-packages/gi
    # make link like this
    ln -s /usr/lib/python3/dist-packages/gi ./venv/lib/python3.14/site-packages/gi
    ```

## Usage

``` python
python main.py # with task tray
python stickynotes.py # without task tray
```

- Attention:
When notes move to another workspace by using window manager,
such as using title bar menu, the app cannot track it.

## Todo

- The features of backup and general settigs.
