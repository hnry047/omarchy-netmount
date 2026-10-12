"""Validated profiles and CIFS operations; no GUI or keyring access here."""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


class OperationError(Exception):
    """A message safe to show in the UI, optionally tied to the form field to fix."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


class FieldError(ValueError):
    """Invalid input with the name of the form field that caused it."""

    def __init__(self, message, field):
        super().__init__(message)
        self.field = field


def _clean(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Fields cannot contain line breaks or control characters.")
    return value.strip()


def normalize(server, remote, local):
    server = _clean(server).replace("\\", "/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,252}[A-Za-z0-9])?", server):
        raise FieldError(
            "Enter an IP address or hostname, such as fileserver.", "server"
        )
    remote = _clean(remote).replace("\\", "/")
    if remote.startswith("//"):
        pieces = remote[2:].split("/", 1)
        if len(pieces) != 2 or pieces[0].lower() != server.lower():
            raise FieldError("The remote path must use the same server.", "remote")
        remote = pieces[1]
    remote = remote.strip("/")
    parts = remote.split("/")
    if (
        not remote
        or any(p in ("", ".", "..") for p in parts)
        or any(c in remote for c in ",;=")
    ):
        raise FieldError(
            "Enter a share and optional subfolder without commas or traversal.",
            "remote",
        )
    local = _clean(local)
    if (
        not local.startswith("/")
        or any(p in (".", "..") for p in local.split("/"))
        or "," in local
    ):
        raise FieldError(
            "Choose an absolute local folder without traversal or commas.", "local"
        )
    local = os.path.normpath(local)
    home = str(Path.home())
    allowed = ("/mnt/", "/media/", home + "/")
    if not local.startswith(allowed) or local.startswith(home + "/."):
        raise FieldError(
            "Choose a subfolder inside /mnt, /media, or your home folder.", "local"
        )
    return {
        "server": server,
        "remote": remote,
        "local": local,
        "source": "//" + server + "/" + remote,
    }


def _unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def read_mounts():
    mounts = []
    # Mount metadata does not touch the NAS or enumerate its files.
    with open("/proc/self/mountinfo", encoding="utf-8") as stream:
        for line in stream:
            before, after = line.rstrip("\n").split(" - ", 1)
            left, right = before.split(), after.split()
            mounts.append(
                {
                    "target": _unescape(left[4]),
                    "root": _unescape(left[3]),
                    "fstype": right[0],
                    "source": _unescape(right[1]),
                }
            )
    return mounts


def mount_state(profile, mounts):
    matching = [m for m in mounts if m["target"] == profile["local"]]
    if not matching:
        return "unmounted"
    # The last entry is the uppermost mount when mounts are stacked.
    item = matching[-1]
    source = item["source"].rstrip("/")
    root = item.get("root", "/").strip("/")
    full = source + ("/" + root if root else "")
    intended = profile["source"].rstrip("/")

    def comparison_key(remote):
        host, separator, path = remote.removeprefix("//").partition("/")
        return host.casefold(), separator, path

    if item["fstype"] == "cifs" and comparison_key(full) == comparison_key(intended):
        return "mounted"
    return "occupied"


def load_profiles(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as stream:
        records = json.load(stream)
    if not isinstance(records, list):
        raise ValueError("Saved connection file has an invalid format.")
    result = []
    seen = set()
    for record in records:
        profile = normalize(record["server"], record["remote"], record["local"])
        ident, label = _clean(record["id"]), _clean(record["label"])
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident)
            or ident in seen
            or not label
        ):
            raise ValueError("Saved connection identity is invalid.")
        seen.add(ident)
        result.append(
            dict(
                profile,
                id=ident,
                label=label,
                remember_login=record.get("remember_login") is True,
                # Profiles saved before these flags existed get the safe defaults.
                encrypt=record.get("encrypt") is not False,
                allow_exec=record.get("allow_exec") is True,
            )
        )
    return result


def save_profiles(path, profiles):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    public = []
    for p in profiles:
        normalize(p["server"], p["remote"], p["local"])
        record = {k: p[k] for k in ("id", "label", "server", "remote", "local")}
        record["remember_login"] = p.get("remember_login") is True
        record["encrypt"] = p.get("encrypt") is not False
        record["allow_exec"] = p.get("allow_exec") is True
        public.append(record)
    fd, temporary = tempfile.mkstemp(prefix=".profiles-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(public, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _run(args, runner, unsupported=None):
    try:
        result = runner(args, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise OperationError(
            "Operation timed out. Check NAS connectivity and refresh status."
        ) from None
    except OSError:
        raise OperationError("A required system tool could not run.") from None
    if result.returncode:
        detail = (result.stderr or "").lower()
        field = None
        if result.returncode in (126, 127):
            message = "Authorization was cancelled or denied. Try again and accept the system prompt."
        elif "busy" in detail:
            message = "The mount is busy. Close files and terminals using this folder, then try again."
        elif "permission denied" in detail or "logon" in detail:
            message = (
                "NAS login failed. Check the username, password, and optional domain."
            )
            field = "password"
        elif "resolve" in detail or "name or service" in detail:
            message = "The hostname could not be resolved. Try the NAS IP address."
            field = "server"
        elif unsupported and "not supported" in detail:
            message, field = unsupported, "encrypt"
        elif "no such file" in detail:
            message = "The share or folder was not found. Check both paths."
            field = "remote"
        elif any(
            s in detail
            for s in ("unreachable", "timed out", "no route", "host is down")
        ):
            message = "The NAS is unreachable. Check its address, VPN, and network connection."
        else:
            message = "Operation failed. Check the NAS address, share, login, and network connection."
        raise OperationError(message, field)


def validate_login(login):
    clean = {}
    for key in ("username", "password", "domain"):
        value = login.get(key, "")
        if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
            raise ValueError(
                "Login fields cannot contain line breaks or NUL characters."
            )
        clean[key] = value
    if not clean["username"].strip():
        raise FieldError("A username is required.", "username")
    return clean


def mount(profile, login, runner=subprocess.run, mounts_fn=read_mounts):
    p = normalize(profile["server"], profile["remote"], profile["local"])
    login = validate_login(login)
    state = mount_state(p, mounts_fn())
    if state == "mounted":
        # This share is already mounted here: nothing to do, and no prompt.
        return
    if state != "unmounted":
        raise OperationError(
            "Something else is mounted in this folder. Choose another folder.",
            "local",
        )
    # Only an explicit mount action inspects the local filesystem. Status and
    # unmount stay metadata-only, even when a NAS is offline.
    if os.path.realpath(p["local"]) != p["local"]:
        raise ValueError("Choose the actual local folder, not a symlink to it.")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid())))
    if (
        not runtime.is_dir()
        or runtime.stat().st_uid != os.getuid()
        or runtime.stat().st_mode & 0o077
    ):
        raise OperationError(
            "A private user runtime directory is required for mounting."
        )
    with tempfile.TemporaryDirectory(prefix="omarchy-netmount-", dir=runtime) as tmp:
        data_path = Path(tmp) / "login-data"
        fd = os.open(data_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for key in ("username", "password", "domain"):
                    if key != "domain" or login[key]:
                        stream.write(key + "=" + login[key] + "\n")
            if not os.path.isdir(p["local"]):
                _run(
                    ["/usr/bin/pkexec", "/usr/bin/mkdir", "-p", "--", p["local"]],
                    runner,
                )
            if mount_state(p, mounts_fn()) != "unmounted":
                raise OperationError(
                    "The local folder became occupied. No mount was performed."
                )
            options = f"credentials={data_path},uid={os.getuid()},gid={os.getgid()},iocharset=utf8,nosuid,nodev"
            # Fixed strings only: profile values never become mount options.
            encrypt = profile.get("encrypt") is not False
            if encrypt:
                options += ",vers=3,seal"
            # Owner-only modes: without them CIFS defaults to 0755, letting other
            # local users read the share through this user's NAS login.
            if profile.get("allow_exec") is not True:
                options += ",noexec,file_mode=0600,dir_mode=0700"
            else:
                options += ",file_mode=0700,dir_mode=0700"
            _run(
                [
                    "/usr/bin/pkexec",
                    "/usr/bin/mount",
                    "-t",
                    "cifs",
                    p["source"],
                    p["local"],
                    "-o",
                    options,
                ],
                runner,
                unsupported=(
                    "The NAS does not support encrypted SMB 3 connections. "
                    "Turn off Encrypt traffic in this connection's settings."
                )
                if encrypt
                else None,
            )
        finally:
            data_path.unlink(missing_ok=True)
    if mount_state(p, mounts_fn()) != "mounted":
        raise OperationError(
            "The mount could not be confirmed. Refresh status before retrying."
        )


def unmount(profile, runner=subprocess.run, mounts_fn=read_mounts):
    p = normalize(profile["server"], profile["remote"], profile["local"])
    if mount_state(p, mounts_fn()) != "mounted":
        raise OperationError(
            "This connection is not mounted here. No unmount was performed."
        )
    _run(["/usr/bin/pkexec", "/usr/bin/umount", "--", p["local"]], runner)
    if mount_state(p, mounts_fn()) != "unmounted":
        raise OperationError(
            "The folder still has a mount. Refresh status before retrying."
        )
