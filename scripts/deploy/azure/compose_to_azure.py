"""Turn `docker compose config --format json` into what the Azure deploy needs.

docker-compose.yml stays the single description of the app. This reads its
resolved form on stdin and prints one of:

  images  a compose file whose services carry registry image names, for
          `docker compose build` and `docker compose push` (build-images.sh)
  apps    one line of `az containerapp create` arguments per service,
          shell-quoted (deploy-azure.sh)

Only services with a `build` are deployed; the student-N grouping containers
are a local convenience.
"""

import argparse
import json
import re
import shlex
import sys


def is_public(name):
    return name == "shared-ui" or name.endswith("-frontend")


def port_of(service):
    if service.get("expose"):
        return int(service["expose"][0])
    return int(service["ports"][0]["target"])


def image_ref(registry, name, tag):
    return f"{registry}/tripgenie-{name}:{tag}"


def built(config):
    return {n: s for n, s in config["services"].items() if "build" in s}


def images(config, registry, tag):
    services = built(config)
    for name, service in services.items():
        service["image"] = image_ref(registry, name, tag)
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


def apps(config, registry, tag, domain):
    services = built(config)
    # A browser reaches each public service at its published host port locally,
    # and at its own HTTPS address in Azure: https://<app>.<environment domain>.
    # Only public apps qualify; a backend's loopback port has no cloud address.
    by_port = {
        str(p["published"]): name
        for name, s in services.items()
        if is_public(name)
        for p in s.get("ports", [])
    }

    def cloud(value):
        # Any other localhost URL (a host AI service, say) is left as it is: in
        # Azure it simply fails to connect, which is what "disabled" means there.
        return re.sub(
            r"http://localhost:(\d+)",
            lambda m: f"https://{by_port[m[1]]}.{domain}" if m[1] in by_port else m[0],
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
        result.append(
            {
                "name": name,
                "image": image_ref(registry, name, tag),
                "port": port_of(service),
                "external": is_public(name),
                "env": dict(sorted(env.items())),
            }
        )
    return result


def az_args(app, environment, registry, frontend_min_replicas):
    port = str(app["port"])
    if app["external"]:
        ingress = ["--ingress", "external", "--target-port", port]
        min_replicas = frontend_min_replicas
    else:
        # Internal TCP on the compose port, so service URLs such as
        # http://student-1-database:8002 work unchanged and nothing outside the
        # environment can reach a backend or database.
        ingress = ["--ingress", "internal", "--transport", "tcp"]
        ingress += ["--target-port", port, "--exposed-port", port]
        min_replicas = "1"
    args = ["--name", app["name"], "--environment", environment]
    args += ["--image", app["image"], *ingress]
    args += ["--registry-server", registry, "--registry-identity", "system"]
    args += ["--workload-profile-name", "Consumption"]
    args += ["--cpu", "0.25", "--memory", "0.5Gi"]
    # ponytail: one replica and no Azure Files share, as in Lab 11. A database
    # keeps its SQLite file only for the life of its replica: a restart or
    # redeploy brings back the seed data. Mount a share (or move to a managed
    # database) if cloud data must survive.
    args += ["--min-replicas", min_replicas, "--max-replicas", "1"]
    if app["env"]:
        args += ["--env-vars", *(f"{k}={v}" for k, v in app["env"].items())]
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["images", "apps"])
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--environment", help="apps: Container Apps environment")
    parser.add_argument("--domain", help="apps: the environment's default domain")
    parser.add_argument("--frontend-min-replicas", default="0")
    args = parser.parse_args()
    config = json.load(sys.stdin)
    if args.mode == "images":
        json.dump(images(config, args.registry, args.tag), sys.stdout, indent=2)
        return
    for app in apps(config, args.registry, args.tag, args.domain):
        line = az_args(app, args.environment, args.registry, args.frontend_min_replicas)
        print(shlex.join(line))


if __name__ == "__main__":
    main()
