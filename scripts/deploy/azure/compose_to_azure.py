"""Turn `docker compose config --format json` into what the Azure deploy needs.

docker-compose.yml stays the single description of the app. This reads its
resolved form on stdin and prints one of:

  images  a compose file whose services carry registry image names, for
          `docker compose build` and `docker compose push`
  apps    the `apps` parameter file for infra/azure/main.bicep

Only services with a `build` are deployed; the student-N grouping containers
are a local convenience.
"""

import argparse
import json
import re
import sys

# Deliberately left as a placeholder: the environment's DNS suffix only exists
# once Azure creates it, so main.bicep substitutes it.
DOMAIN = "__DOMAIN__"


def is_public(name):
    return name == "shared-ui" or name.endswith("-frontend")


def port_of(service):
    if service.get("expose"):
        return int(service["expose"][0])
    return int(service["ports"][0]["target"])


def built(config):
    return {n: s for n, s in config["services"].items() if "build" in s}


def images(config, registry, tag):
    services = built(config)
    for name, service in services.items():
        service["image"] = f"{registry}/tripgenie-{name}:{tag}"
        # Container Apps runs linux/amd64 only; a laptop on Apple silicon would
        # otherwise push arm64 images Azure cannot start.
        service["platform"] = "linux/amd64"
        # The grouping containers are gone, and so must be references to them.
        service.pop("depends_on", None)
    return {
        "name": config.get("name", "tripgenie"),
        "services": services,
        "volumes": config.get("volumes", {}),
    }


def apps(config, registry, tag):
    services = built(config)
    # A browser reaches each public service at its published host port locally,
    # and at its own HTTPS address in Azure.
    by_port = {
        str(p["published"]): name
        for name, s in services.items()
        for p in s.get("ports", [])
    }

    def cloud(value):
        return re.sub(
            r"http://localhost:(\d+)",
            lambda m: f"https://{by_port[m[1]]}.{DOMAIN}",
            value,
        )

    result = []
    for name, service in services.items():
        env = {
            key: cloud(value)
            for key, value in (service.get("environment") or {}).items()
            # Blank means "off" for the switches that read an empty URL as
            # disabled; leave it unset so the code default applies.
            if value
        }
        volumes = [v["target"] for v in service.get("volumes", [])]
        result.append(
            {
                "name": name,
                "image": f"{registry}/tripgenie-{name}:{tag}",
                "port": port_of(service),
                "external": is_public(name),
                "env": [{"name": k, "value": v} for k, v in sorted(env.items())],
                "volumePath": volumes[0] if volumes else "",
            }
        )
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {"apps": {"value": result}},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["images", "apps"])
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    render = images if args.mode == "images" else apps
    rendered = render(json.load(sys.stdin), args.registry, args.tag)
    json.dump(rendered, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
