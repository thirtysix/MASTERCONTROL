"""Window manager for finding and activating terminal windows by title.

Uses python-xlib to interact with X11 _NET_WM hints for window
discovery, activation, and workspace movement.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _get_display():
    """Get an X11 Display connection. Returns None if unavailable."""
    try:
        from Xlib import display
        return display.Display()
    except Exception as e:
        log.warning("Cannot connect to X11 display: %s", e)
        return None


def find_window_by_title(substring: str) -> int | None:
    """Find first window whose title contains *substring*.

    Returns the X11 window ID (int) or None.
    """
    d = _get_display()
    if d is None:
        return None

    try:
        from Xlib import X
        root = d.screen().root
        client_list_atom = d.intern_atom("_NET_CLIENT_LIST")
        resp = root.get_full_property(client_list_atom, X.AnyPropertyType)
        if not resp:
            return None

        net_wm_name = d.intern_atom("_NET_WM_NAME")
        utf8 = d.intern_atom("UTF8_STRING")

        for wid in resp.value:
            w = d.create_resource_object("window", wid)
            try:
                prop = w.get_full_property(net_wm_name, utf8)
                if prop and substring in prop.value.decode("utf-8", errors="replace"):
                    return wid
            except Exception:
                continue
        return None
    finally:
        d.close()


def activate_window(wid: int) -> bool:
    """Activate (bring to front) the window with the given X11 ID.

    Moves it to the current desktop first, then sends _NET_ACTIVE_WINDOW.
    Returns True on success.
    """
    d = _get_display()
    if d is None:
        return False

    try:
        from Xlib import X

        root = d.screen().root
        w = d.create_resource_object("window", wid)

        net_wm_desktop = d.intern_atom("_NET_WM_DESKTOP")
        net_current_desktop = d.intern_atom("_NET_CURRENT_DESKTOP")
        net_active_window = d.intern_atom("_NET_ACTIVE_WINDOW")

        # Get current desktop
        cur = root.get_full_property(net_current_desktop, X.AnyPropertyType)
        current_desktop = cur.value[0] if cur else 0

        # Move window to current desktop
        _send_client_message(d, root, w, net_wm_desktop, [current_desktop, 1])

        # Activate window
        _send_client_message(d, root, w, net_active_window, [1, X.CurrentTime, 0])

        d.flush()
        return True
    except Exception as e:
        log.warning("Failed to activate window %s: %s", wid, e)
        return False
    finally:
        d.close()


def _send_client_message(d, root, window, message_type, data: list[int]):
    """Send an X11 ClientMessage event to the root window."""
    from Xlib import X

    # Pad data to 5 ints (20 bytes for 32-bit format)
    while len(data) < 5:
        data.append(0)

    # Build the client message event
    ev = xevent_from_data(d, window, message_type, data)
    root.send_event(
        ev,
        event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
    )


def xevent_from_data(d, window, message_type, data: list[int]):
    """Construct a ClientMessage X event manually."""
    from Xlib.protocol import event as xevent

    return xevent.ClientMessage(
        window=window,
        client_type=message_type,
        data=(32, data),
    )


def find_and_activate(title_substring: str) -> bool:
    """Find a window by title substring and activate it.

    Returns True if a window was found and activated, False otherwise.
    """
    wid = find_window_by_title(title_substring)
    if wid is None:
        return False
    return activate_window(wid)
