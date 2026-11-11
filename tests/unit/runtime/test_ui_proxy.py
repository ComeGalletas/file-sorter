"""RUN-019.1: the localhost-only UI proxy (RUN-001.D5, R-RUN-1).

Parses docker-compose.yml with PyYAML and reads docker/ui-proxy/nginx.conf and the Makefile.
Nothing runs.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
NGINX = REPO / "docker" / "ui-proxy" / "nginx.conf"


def compose() -> dict:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def services() -> dict:
    return compose()["services"]


def networks_of(service: dict) -> set[str]:
    # The list form and the mapping form both iterate as network names.
    return set(service.get("networks") or [])


def nginx_conf() -> str:
    # Drop comments, so a word in a comment can't satisfy or break a check.
    lines = NGINX.read_text(encoding="utf-8").splitlines()
    return "\n".join(line.split("#", 1)[0] for line in lines)


def test_every_published_port_binds_to_localhost() -> None:
    for name, service in services().items():
        for port in service.get("ports") or []:
            if isinstance(port, str):
                text = port
            else:
                text = f"{port.get('host_ip', '')}:{port.get('published')}"
            assert text.startswith("127.0.0.1:"), f"{name} publishes a port off localhost"


def test_only_the_proxy_publishes_a_port_and_it_is_8000() -> None:
    published = {name for name, s in services().items() if s.get("ports")}
    assert published == {"ui-proxy"}
    assert services()["ui-proxy"]["ports"] == ["127.0.0.1:8000:8000"]


def test_the_ui_network_is_the_proxys_alone() -> None:
    assert networks_of(services()["ui-proxy"]) == {"internal", "ui"}
    on_ui = {name for name, s in services().items() if "ui" in networks_of(s)}
    assert on_ui == {"ui-proxy"}
    assert not (compose()["networks"].get("ui") or {}).get("internal")  # it must publish


def test_app_stays_on_the_internal_network_only() -> None:
    assert networks_of(services()["app"]) == {"internal"}
    assert not services()["app"].get("ports")


def test_the_proxy_image_is_pinned_and_the_container_read_only() -> None:
    proxy = services()["ui-proxy"]
    assert re.fullmatch(r"nginx:\d+\.\d+\.\d+-alpine", proxy["image"])
    assert proxy.get("read_only") is True
    assert "./docker/ui-proxy/nginx.conf:/etc/nginx/nginx.conf:ro" in proxy["volumes"]
    # nginx writes only to these, so read_only holds.
    assert set(proxy["tmpfs"]) == {"/var/cache/nginx", "/var/run", "/tmp"}


def test_app_serves_on_the_internal_network() -> None:
    # RUN-019.D2: app runs serve; only the proxy publishes it.
    assert services()["app"]["command"] == ["classifier", "serve", "--host", "0.0.0.0"]


def test_nginx_resolves_only_through_dockers_dns_and_pins_host() -> None:
    conf = nginx_conf()
    assert re.findall(r"resolver\s+([^;]+);", conf) == ["127.0.0.11 valid=30s ipv6=off"]
    assert re.findall(r"proxy_set_header\s+Host\s+([^;]+);", conf) == ["127.0.0.1:8000"]


def test_nginx_forwards_get_only_to_app_and_buffers_nothing() -> None:
    conf = nginx_conf()
    upstreams = set(re.findall(r"https?://([\w.-]+(?::\d+)?)", conf))
    assert upstreams == {"app:8000"}
    assert re.search(r"limit_except\s+GET\s*\{\s*deny\s+all;\s*\}", conf)
    assert re.search(r"proxy_buffering\s+off;", conf)  # SSE
    assert re.search(r"server_tokens\s+off;", conf)
    assert re.search(r"access_log\s+off;", conf)  # request lines carry filters and hashes
    assert re.search(r"error_log\s+\S+\s+crit;", conf)  # `error` lines quote the request line
    assert re.search(r"listen\s+8000;", conf)


def test_gate_4_runs_from_the_main_checkout_with_the_dsn_by_name() -> None:
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    rule = make.split("\ngate-4:", 1)[1].split("\nendif", 1)[0]
    main_branch, worktree_branch = rule.split("\nelse\n", 1)
    assert "-e APP_DB_DSN " in main_branch and "scripts/gate_4.py" in main_branch
    assert "-e APP_DB_DSN=" not in rule  # by name only: a value here would be echoed
    # A worktree has no app database: it fails with fixed text and never runs the gate.
    assert "gate 4 FAIL" in worktree_branch and "exit 1" in worktree_branch
    assert "scripts/gate_4.py" not in worktree_branch
    assert "echo $$APP_DB_DSN" not in rule and "echo $${APP_DB_DSN}" not in rule
    # The line that builds the DSN is @-silenced, so make never echoes it.
    dsn_lines = [line for line in rule.splitlines() if "DB_PASSWORD=" in line]
    assert dsn_lines and all(line.lstrip("\t").startswith("@") for line in dsn_lines)
