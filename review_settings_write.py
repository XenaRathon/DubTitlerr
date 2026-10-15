"""The exporter the shell loops and the container entrypoint call (specs/webui-full-settings, S-5).

Nothing ever `source`s settings.json or secrets.json. The shell runs

    eval "$(python3 "$APP_DIR/review_settings_write.py" export --scope gen --reset-to-init 2>/dev/null)"

and this program prints only registry keys, re-validated, as shell-quoted `export NAME='value'` lines, so a hand-edited or
hostile file can produce nothing but registered settings with valid values. It always exits 0 on a read problem and prints ONE
stderr line naming what it ignored, so a bad file falls back to the container environment audibly.

Subcommands
  export --scope gen|merge|server|container [--plain] [--boot] [--reset-to-init]
      the stored settings of one scope (a merge pass also receives the gen keys, as it always has).
      --plain       NAME=value lines, no `export`, stored values only (for tests and for reading). Never a secret.
      --boot        also `export DT_BOOT_<KEY>=<container value>` for each stored key the container already sets, so the server
                    can still report the pre-store value and the "overrides env" flag (container_run.sh passes it).
                    Never a secret.
      --reset-to-init  for every key of the scope with no stored value, restore the value the loop saw at start (the _INIT_
                    snapshot below) or unset it, so a reset takes effect in a long-running loop without a restart.
  snapshot --scope gen|merge
      the `_INIT_<KEY>` / `_HAS_INIT_<KEY>` assignments that --reset-to-init restores from, generated from the registry so the
      list of keys cannot drift from it.

stdout carries only `export`/`unset` lines (what the shell evaluates): everything else, including the store's own log lines,
goes to stderr."""

import contextlib
import os
import shlex
import sys

import settings_registry as reg
import settings_store as store

SCOPES = ("gen", "merge", "server", "container")
USAGE = "usage: review_settings_write.py export|snapshot --scope gen|merge|server|container [--plain] [--boot] [--reset-to-init]"


def scope_names(scope):
    """Every environment name a process of this scope may be given, in a fixed order."""
    return sorted(reg.keys_for_scope(scope))


def export_assignments(environ=None, scope="merge", notes=None, boot=False, plain=False):
    """([(NAME, value)] to export, {NAME} of every scope key that has a stored value). Re-validated on load, so a bad file
    yields nothing but a note. --plain and --boot never include a secret."""
    notes = [] if notes is None else notes
    environ = os.environ if environ is None else environ
    with contextlib.redirect_stdout(sys.stderr):  # store.load logs through common.log, which prints to stdout
        state = store.load(environ)
    if state.error:
        notes.append(state.error)
    if state.secrets_error:
        notes.append(state.secrets_error)
    notes.extend(state.notes)
    out, stored = [], set()
    for key in sorted(reg.keys_for_scope(scope)):
        entry = reg.REGISTRY[key]
        if entry["secret"]:
            if key in state.secret_values and not (plain or boot):
                out.append((key, state.secret_values[key]))
                stored.add(key)
        elif key in state.values:
            out.append((key, reg.to_env(state.values[key])))
            stored.add(key)
    if boot:
        out.extend(("DT_BOOT_" + key, environ[key]) for key in sorted(stored) if key in environ)
    return out, stored


def format_assignments(assignments, plain=False):
    prefix = "" if plain else "export "
    return "".join(f"{prefix}{name}={shlex.quote(value)}\n" for name, value in assignments)


def format_restore(name):
    return f'if [ -n "${{_HAS_INIT_{name}:-}}" ]; then export {name}="$_INIT_{name}"; else unset {name}; fi\n'


def format_snapshot(scope):
    return "".join(f'_INIT_{n}="${{{n}:-}}"\n_HAS_INIT_{n}="${{{n}+1}}"\n' for n in scope_names(scope))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("export", "snapshot"):
        print(USAGE, file=sys.stderr)
        return 2
    command, plain, boot, reset, scope = argv[0], False, False, False, "merge"
    rest = argv[1:]
    while rest:
        arg = rest.pop(0)
        if arg == "--plain":
            plain = True
        elif arg == "--boot":
            boot = True
        elif arg == "--reset-to-init":
            reset = True
        elif arg == "--scope" and rest:
            scope = rest.pop(0)
        elif arg.startswith("--scope="):
            scope = arg.split("=", 1)[1]
        else:
            print(f"unknown argument: {arg}\n{USAGE}", file=sys.stderr)
            return 2
    if scope not in SCOPES or (command == "snapshot" and scope not in ("gen", "merge")):
        print(f"unknown scope: {scope}\n{USAGE}", file=sys.stderr)
        return 2
    notes = []
    out = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):  # anything printed while computing must not reach the shell's eval
            if command == "snapshot":
                text = format_snapshot(scope)
            else:
                assignments, stored = export_assignments(scope=scope, notes=notes, boot=boot, plain=plain)
                text = format_assignments(assignments, plain)
                if reset and not plain:
                    text += "".join(format_restore(n) for n in scope_names(scope) if n not in stored)
        out.write(text)
    except Exception as e:  # noqa: BLE001 - a loop must never die because a settings file is odd
        notes.append(f"unexpected {e.__class__.__name__}")
    if notes:
        print("review_settings_write: ignored: " + "; ".join(notes), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
