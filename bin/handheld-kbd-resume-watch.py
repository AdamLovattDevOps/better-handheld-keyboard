#!/usr/bin/env python3
"""Re-init the Better Handheld Keyboard on resume-from-sleep. Uses Gio signal_subscribe
(a normal match rule — works as non-root, unlike dbus-monitor eavesdropping) on logind's
PrepareForSleep signal. Argument False = waking up."""
import os, subprocess, gi
import fcntl
_lk=open('/tmp/handheld-kbd-resume-watch.lock','w')
try: fcntl.flock(_lk, fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError: raise SystemExit(0)
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib
RESUME = os.path.expanduser('~/.local/bin/handheld-kbd-resume.sh')
def fire():
    subprocess.Popen(['bash', RESUME]); return False
def on_sig(conn, sender, path, iface, signal, params):
    try: going = params.unpack()[0]
    except Exception: return
    if going is False:
        GLib.timeout_add_seconds(3, fire)
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
bus.signal_subscribe(None, 'org.freedesktop.login1.Manager', 'PrepareForSleep',
                     '/org/freedesktop/login1', None, Gio.DBusSignalFlags.NONE, on_sig)
GLib.MainLoop().run()
