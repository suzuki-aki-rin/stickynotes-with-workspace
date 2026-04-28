import sys

# Prepend system site-packages so bundled code (like pystray) can find gi
sys.path.insert(0, "/usr/lib/python3/dist-packages")
sys.path.insert(0, "/usr/lib/python3/dist-packages/gi")
