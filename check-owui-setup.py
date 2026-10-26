#!/usr/bin/env python3
"""Read only check of Open WebUI's accounts for the native chat (SECURITY.md 14, 136).

Opens Open WebUI's database read only (mode=ro), from the host: it prints
the accounts and their roles, the groups with their members and permissions, who may use the
julz-mem and julz-claude collections and the julz models, and whether each account has an API
key. It never prints a key, a password hash or a token: such columns are reported as present
or missing only. It changes nothing.

Usage, in my own terminal, reading the volume from the host (the container's AppArmor profile
forbids docker exec, and stays that way):
  sudo python3 -I check-owui-setup.py /var/lib/docker/volumes/open-webui/_data/webui.db
"""
import json
import sqlite3
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/docker/volumes/open-webui/_data/webui.db"
DB = f"file:{PATH}?mode=ro"
SECRET = ("key", "password", "token", "secret", "hash", "oauth")
WANTED_KB = ("julz-mem", "julz-claude")


def cols(c, table):
    return [r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]


def safe(name, value):
    if any(s in name.lower() for s in SECRET):
        return "present" if value else "missing"
    return value


def main():
    c = sqlite3.connect(DB, uri=True)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("tables:", ", ".join(sorted(t for t in tables if any(w in t for w in ("user", "group", "knowledge", "model", "api", "access")))))

    users = {}
    if "user" in tables:
        uc = cols(c, "user")
        for row in c.execute(f'SELECT * FROM "user"'):
            r = dict(zip(uc, row))
            users[r.get("id")] = r.get("email")
            extra = {k: safe(k, r[k]) for k in r if any(s in k.lower() for s in SECRET)}
            print(f"user  {r.get('email'):28} role={r.get('role'):8} {extra}")

    for t in ("api_key", "apikey"):
        if t in tables:
            tc = cols(c, t)
            for row in c.execute(f'SELECT * FROM "{t}"'):
                r = dict(zip(tc, row))
                print(f"api key  owner={users.get(r.get('user_id'), r.get('user_id'))}  {{key: present}}")

    groups = {}
    if "group" in tables:
        gc = cols(c, "group")
        for row in c.execute('SELECT * FROM "group"'):
            r = dict(zip(gc, row))
            groups[r.get("id")] = r.get("name")
    if "group" in tables:
        for row in c.execute('SELECT * FROM "group"'):
            r = dict(zip(gc, row))
            members = r.get("user_ids")
            try:
                members = [users.get(u, u) for u in json.loads(members or "[]")]
            except (ValueError, TypeError):
                pass
            perms = r.get("permissions")
            print(f"group {r.get('name'):20} members={members}")
            print(f"      permissions={perms}")
    for t in ("group_member",):
        if t in tables:
            tc = cols(c, t)
            for row in c.execute(f'SELECT * FROM "{t}"'):
                r = dict(zip(tc, row))
                print(f"group member  group={groups.get(r.get('group_id'), r.get('group_id'))}  user={users.get(r.get('user_id'), r.get('user_id'))}")

    kbs = {}
    if "knowledge" in tables:
        kc = cols(c, "knowledge")
        for row in c.execute('SELECT * FROM "knowledge"'):
            r = dict(zip(kc, row))
            kbs[r.get("id")] = r.get("name")
        for row in c.execute('SELECT * FROM "knowledge"'):
            r = dict(zip(kc, row))
            if r.get("name") in WANTED_KB:
                print(f"knowledge {r.get('name'):12} owner={users.get(r.get('user_id'))} access={r.get('access_control')}")

    if "model" in tables:
        mc = cols(c, "model")
        for row in c.execute('SELECT * FROM "model"'):
            r = dict(zip(mc, row))
            if str(r.get("id", "")).startswith("julz"):
                print(f"model {r.get('id'):16} access={r.get('access_control')} active={r.get('is_active')}")
                # Which filters and tools the model runs (202: does julz_language reach julz-chat)
                try:
                    meta = json.loads(r.get("meta") or "{}")
                except (ValueError, TypeError):
                    meta = {}
                print(f"      filterIds={meta.get('filterIds')} toolIds={meta.get('toolIds')}")

    # Functions: names and switches only, never their code
    if "function" in tables:
        fc = cols(c, "function")
        for row in c.execute('SELECT * FROM "function"'):
            r = dict(zip(fc, row))
            print(f"function {r.get('id'):20} type={r.get('type'):7} active={r.get('is_active')} global={r.get('is_global')}")

    for t in tables:
        if "access" in t or "grant" in t:
            tc = cols(c, t)
            print(f"{t}: columns {tc}")
            for row in c.execute(f'SELECT * FROM "{t}" LIMIT 40'):
                r = dict(zip(tc, row))
                for k in ("user_id", "principal_id"):
                    if k in r and r[k] in users:
                        r[k] = users[r[k]]
                    elif k in r and r[k] in groups:
                        r[k] = "group " + groups[r[k]]
                if r.get("resource_type") == "knowledge" and r.get("resource_id") in kbs:
                    r["resource_id"] = kbs[r["resource_id"]]
                print(f"  {r}")

    # Settings, one row per key in this version; only the ones this check needs
    if "config" in tables:
        cc = cols(c, "config")
        print("config columns:", cc)
        if "key" in cc and "value" in cc:
            for k, v in c.execute('SELECT "key", "value" FROM "config"'):
                if k.startswith(("auth.api_key", "auth.enable_api", "user.permissions", "direct")) or "direct_connection" in k:
                    print(f"config {k} = {str(v)[:400]}")


if __name__ == "__main__":
    main()
