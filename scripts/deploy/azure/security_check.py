"""Check a TripGenie Azure deployment's configuration for its security controls.

    python scripts/deploy/azure/security_check.py APPS_JSON REGISTRY_JSON

APPS_JSON holds `az containerapp list -o json` and REGISTRY_JSON
`az acr show -o json`. Prints a Markdown table and exits non-zero on any
failure. Stdlib only.
"""

import json
import re
import sys
from pathlib import Path

CREDENTIAL = re.compile(
    r"(^|_)(PASSWORD|SECRET|TOKEN|API_KEY|CREDENTIALS?|CONNECTION_STRING)$",
    re.IGNORECASE,
)


def is_public(name):
    return name == "shared-ui" or name.endswith("-frontend")


def names(apps):
    return ", ".join(sorted(apps)) or "none"


def checks(apps, registry):
    by_name = {app["name"]: app["properties"] for app in apps}
    ingress = {n: p["configuration"].get("ingress") or {} for n, p in by_name.items()}

    exposed = [n for n, i in ingress.items() if i.get("external") and not is_public(n)]
    public = [n for n, i in ingress.items() if i.get("external")]
    yield (
        "Only shared-ui and the frontends are public",
        not exposed and len(public) > 0,
        f"exposed: {names(exposed)}" if exposed else f"{len(public)} public",
    )

    insecure = [n for n in public if ingress[n].get("allowInsecure")]
    yield "Public apps redirect HTTP to HTTPS", not insecure, names(insecure)

    unmanaged = [
        n
        for n, p in by_name.items()
        if not p["configuration"].get("registries")
        or any(
            not r.get("identity") or r.get("passwordSecretRef")
            for r in p["configuration"]["registries"]
        )
    ]
    yield (
        "Images pulled with a managed identity",
        not unmanaged,
        names(unmanaged),
    )

    plain = [
        f"{n}:{e['name']}"
        for n, p in by_name.items()
        for c in p["template"]["containers"]
        for e in c.get("env") or []
        if CREDENTIAL.search(e["name"]) and not e.get("secretRef")
    ]
    yield "No credentials in plain app settings", not plain, names(plain)

    yield (
        "Registry admin user disabled",
        registry.get("adminUserEnabled") is False,
        registry.get("adminUserEnabled"),
    )
    yield (
        "Registry anonymous pull disabled",
        not registry.get("anonymousPullEnabled"),
        bool(registry.get("anonymousPullEnabled")),
    )


def main(apps_file, registry_file):
    apps = json.loads(Path(apps_file).read_text())
    registry = json.loads(Path(registry_file).read_text())
    print("| Check | Result | Detail |\n| --- | --- | --- |")
    failed = 0
    for name, ok, detail in checks(apps, registry):
        failed += not ok
        print(f"| {name} | {'pass' if ok else 'FAIL'} | {detail} |")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
