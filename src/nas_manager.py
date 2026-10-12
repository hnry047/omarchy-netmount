"""Connection lifecycle independent of the graphical interface."""

from nas_core import (
    FieldError,
    OperationError,
    load_profiles,
    mount_state,
    normalize,
    read_mounts,
    save_profiles,
    validate_login,
)


class Manager:
    def __init__(self, path, keyring, mounts_fn=read_mounts):
        self.path = path
        self.keyring = keyring
        self.mounts_fn = mounts_fn
        self.profiles = load_profiles(path)
        self.persistent = {p["id"] for p in self.profiles}
        self.session_logins = {}

    def find(self, ident):
        return next(p for p in self.profiles if p["id"] == ident)

    def state(self, profile):
        return mount_state(profile, self.mounts_fn())

    def status(self):
        mounts = self.mounts_fn()
        states = [mount_state(p, mounts) for p in self.profiles]
        return {
            "mounted": states.count("mounted"),
            "saved": len(self.persistent),
            "occupied": states.count("occupied"),
        }

    def login(self, ident):
        if ident in self.session_logins:
            return self.session_logins[ident]
        if not self.find(ident).get("remember_login", False):
            return None
        try:
            login = self.keyring.get_login(ident)
            return validate_login(login) if login else None
        except Exception:
            raise OperationError(
                "The keyring could not be unlocked. Enter the login for this session."
            ) from None

    def save(self, profile, login, remember, remember_login):
        if remember_login and not remember:
            raise ValueError("Remember the connection before remembering its login.")
        if remember_login and login is None:
            raise ValueError("A login is required to remember it.")
        clean = dict(
            normalize(profile["server"], profile["remote"], profile["local"]),
            id=profile["id"],
            label=profile["label"].strip(),
            remember_login=remember_login,
            encrypt=profile.get("encrypt") is not False,
            allow_exec=profile.get("allow_exec") is True,
        )
        if not clean["label"]:
            raise ValueError("Enter a connection name.")
        same = next(
            (
                p
                for p in self.profiles
                if p["id"] != clean["id"]
                and p["local"] == clean["local"]
                and p["source"] == clean["source"]
            ),
            None,
        )
        if same:
            # Adding a share that is already saved for this folder updates that
            # connection instead of failing or creating a duplicate.
            clean["id"] = same["id"]
        old = next((p for p in self.profiles if p["id"] == clean["id"]), None)
        moved = old and (old["source"], old["local"]) != (
            clean["source"],
            clean["local"],
        )
        if moved and self.state(old) != "unmounted":
            raise OperationError("Unmount this connection before editing it.")
        other = next(
            (
                p
                for p in self.profiles
                if p["id"] != clean["id"] and p["local"] == clean["local"]
            ),
            None,
        )
        if other:
            raise FieldError(
                f"“{other['label']}” already uses this folder. Choose another folder.",
                "local",
            )
        login = validate_login(login) if login is not None else None
        updated = [clean if p["id"] == clean["id"] else p for p in self.profiles]
        if old is None:
            updated.append(clean)
        persistent = (
            self.persistent | {clean["id"]}
            if remember
            else self.persistent - {clean["id"]}
        )
        save_profiles(self.path, [p for p in updated if p["id"] in persistent])
        self.profiles, self.persistent = updated, persistent
        if login is not None:
            self.session_logins[clean["id"]] = login
        warning = ""
        try:
            if remember_login:
                if login is None:
                    raise ValueError("A login is required to remember it.")
                self.keyring.store_login(clean["id"], login)
            else:
                self.keyring.forget_login(clean["id"])
        except Exception:
            clean["remember_login"] = False
            save_profiles(
                self.path, [p for p in self.profiles if p["id"] in self.persistent]
            )
            warning = (
                "The keyring could not save or remove the remembered login. "
                "This login is available for this session only; any previous keyring login may remain."
            )
        return warning

    def move(self, ident, position):
        """Place a connection at `position` (clamped); order only, no mounts."""
        moving = next((p for p in self.profiles if p["id"] == ident), None)
        if moving is None:
            raise ValueError("That connection no longer exists.")
        rest = [p for p in self.profiles if p["id"] != ident]
        position = max(0, min(position, len(rest)))
        updated = rest[:position] + [moving] + rest[position:]
        save_profiles(self.path, [p for p in updated if p["id"] in self.persistent])
        self.profiles = updated

    def forget(self, ident):
        profile = self.find(ident)
        if self.state(profile) != "unmounted":
            raise OperationError("Unmount this connection before forgetting it.")
        try:
            self.keyring.forget_login(ident)
        except Exception:
            raise OperationError(
                "The keyring could not remove the login. Unlock it and try Forget again."
            ) from None
        remaining = [p for p in self.profiles if p["id"] != ident]
        save_profiles(self.path, [p for p in remaining if p["id"] in self.persistent])
        self.profiles = remaining
        self.persistent.discard(ident)
        self.session_logins.pop(ident, None)
