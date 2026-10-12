"""One manager per user: the lock file and hand-off to a running manager.

No GUI or keyring access here.
"""

import fcntl
import os
import time

from nas_toggle import request_toggle


def claim_manager(
    lock_path, socket_path, request, toggle=request_toggle, sleep=time.sleep
):
    """Return ("owner", fd), ("handed_off", None) or ("busy", None).

    The owner keeps `fd` open (and so the lock) for as long as it runs. A second
    launch passes its request to the owner instead; a click may race the
    preload process while GTK is importing, so it retries briefly.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return "owner", fd
    except BlockingIOError:
        pass
    try:
        for _ in range(20):
            if toggle(socket_path, request):
                return "handed_off", None
            sleep(0.02)
        return "busy", None
    finally:
        os.close(fd)
