"""Network utility functions for interface detection."""

import ipaddress
import json
import logging
import re
import shutil
import socket
import struct
import subprocess

logger = logging.getLogger(__name__)

# Interfaces to exclude from selection
EXCLUDED_INTERFACE_PREFIXES = ("lo", "docker", "br-", "veth", "virbr")

# Resolve full path to `ip` command (may not be in PATH for service users)
_IP_CMD: str | None = shutil.which("ip") or shutil.which("ip", path="/usr/sbin:/sbin:/usr/bin:/bin")


def _is_excluded(name: str) -> bool:
    """Check if an interface name should be excluded."""
    return any(name.startswith(prefix) for prefix in EXCLUDED_INTERFACE_PREFIXES)


def get_network_interfaces() -> list[dict]:
    """Get all network interfaces with their IPs and subnets.

    Returns:
        List of dicts with name, ip, netmask, subnet, broadcast
    """
    interfaces = []

    try:
        import fcntl

        for iface in socket.if_nameindex():
            name = iface[1]

            # Skip excluded interfaces
            if _is_excluded(name):
                continue

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

                # Get IP address
                ip_bytes = fcntl.ioctl(
                    s.fileno(),
                    0x8915,  # SIOCGIFADDR
                    struct.pack("256s", name[:15].encode()),
                )[20:24]
                ip = socket.inet_ntoa(ip_bytes)

                # Get netmask
                netmask_bytes = fcntl.ioctl(
                    s.fileno(),
                    0x891B,  # SIOCGIFNETMASK
                    struct.pack("256s", name[:15].encode()),
                )[20:24]
                netmask = socket.inet_ntoa(netmask_bytes)

                # Calculate subnet
                network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)

                interfaces.append(
                    {
                        "name": name,
                        "ip": ip,
                        "netmask": netmask,
                        "subnet": str(network),
                    }
                )

                s.close()
            except OSError:
                # Interface doesn't have an IP or other error
                pass
            except Exception as e:
                logger.debug("Error getting info for interface %s: %s", name, e)

    except ImportError:
        # fcntl not available (Windows)
        logger.warning("fcntl not available, interface detection limited")
    except Exception as e:
        logger.error("Error enumerating interfaces: %s", e)

    return interfaces


def _get_all_ips_from_ip_text() -> list[dict] | None:
    """Parse text output of 'ip addr show' — works with BusyBox ip.

    BusyBox's ip does not support -j (JSON) but does list secondary/alias
    addresses in its plain text output. This provides alias IP enumeration
    on Alpine containers where iproute2 is not installed or shadowed.

    Returns None if the command fails or produces no results.
    """
    if not _IP_CMD:
        return None

    try:
        result = subprocess.run(
            [_IP_CMD, "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        entries = []
        current_iface: str | None = None
        ipv4_count_per_iface: dict[str, int] = {}

        for line in result.stdout.splitlines():
            # Interface line: "2: eth1: <FLAGS>" — capture name before @ or :
            if re.match(r"^\d+:", line):
                m = re.match(r"^\d+:\s+([^@:\s]+)", line)
                if m:
                    current_iface = m.group(1)
                    if current_iface not in ipv4_count_per_iface:
                        ipv4_count_per_iface[current_iface] = 0
                continue

            # inet line: "    inet 192.168.1.1/24 ..."
            m = re.match(r"^\s+inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", line)
            if m and current_iface and not _is_excluded(current_iface):
                try:
                    iface_obj = ipaddress.IPv4Interface(m.group(1))
                    ip = str(iface_obj.ip)
                    network = iface_obj.network
                    count = ipv4_count_per_iface.get(current_iface, 0)
                    ipv4_count_per_iface[current_iface] = count + 1
                    entries.append(
                        {
                            "name": current_iface,
                            "ip": ip,
                            "netmask": str(network.netmask),
                            "subnet": str(network),
                            "is_alias": count > 0,
                            "label": current_iface,
                        }
                    )
                except ValueError:
                    continue

        return entries if entries else None
    except Exception:
        return None


def get_all_interface_ips() -> list[dict]:
    """Get all IPs (primary + aliases) for all non-excluded interfaces.

    Tries three methods in order:
    1. ip -j addr show  (iproute2 JSON — most reliable)
    2. ip addr show     (BusyBox-compatible text parsing — handles aliases)
    3. ioctl fallback   (primary IPs only, no aliases)

    Returns:
        List of dicts with name, ip, netmask, subnet, is_alias, label
    """
    if not _IP_CMD:
        logger.debug("ip command not found, using ioctl fallback")
        return _fallback_get_all_ips()

    # Method 1: iproute2 JSON
    try:
        result = subprocess.run(
            [_IP_CMD, "-j", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            interfaces_data = json.loads(result.stdout)
            entries = []
            for iface in interfaces_data:
                ifname = iface.get("ifname", "")
                if _is_excluded(ifname):
                    continue

                ipv4_count = 0
                for addr_info in iface.get("addr_info", []):
                    if addr_info.get("family") != "inet":
                        continue

                    ip = addr_info.get("local", "")
                    prefix = addr_info.get("prefixlen", 24)
                    label = addr_info.get("label", ifname)

                    try:
                        network = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
                        netmask = str(network.netmask)
                    except ValueError:
                        continue

                    is_alias = ":" in label or ipv4_count > 0

                    entries.append(
                        {
                            "name": ifname,
                            "ip": ip,
                            "netmask": netmask,
                            "subnet": str(network),
                            "is_alias": is_alias,
                            "label": label,
                        }
                    )
                    ipv4_count += 1

            entries.sort(key=lambda e: (e["name"], e["is_alias"], e["ip"]))
            return entries
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    # Method 2: BusyBox-compatible text parsing (handles aliases)
    logger.debug("ip -j failed, trying text-based ip addr show")
    text_result = _get_all_ips_from_ip_text()
    if text_result is not None:
        text_result.sort(key=lambda e: (e["name"], e["is_alias"], e["ip"]))
        return text_result

    # Method 3: ioctl (primary IPs only — no aliases)
    logger.debug("Text parsing failed, falling back to ioctl (no alias support)")
    return _fallback_get_all_ips()


def _fallback_get_all_ips() -> list[dict]:
    """Fallback: wrap get_network_interfaces() result with alias fields."""
    return [
        {
            **iface,
            "is_alias": False,
            "label": iface["name"],
        }
        for iface in get_network_interfaces()
    ]


def find_interface_for_ip(target_ip: str) -> dict | None:
    """Find which interface is on the same subnet as the target IP.

    Args:
        target_ip: IP address to find the matching interface for

    Returns:
        Interface dict or None if not found
    """
    try:
        target = ipaddress.IPv4Address(target_ip)
    except ValueError:
        logger.error("Invalid target IP: %s", target_ip)
        return None

    interfaces = get_all_interface_ips()

    for iface in interfaces:
        if iface.get("is_alias"):
            continue
        try:
            network = ipaddress.IPv4Network(iface["subnet"], strict=False)
            if target in network:
                logger.debug("Found interface %s (%s) for target %s", iface["name"], iface["ip"], target_ip)
                return iface
        except ValueError:
            continue

    logger.warning("No interface found for target IP %s", target_ip)
    return None


def get_other_interfaces(exclude_ip: str) -> list[dict]:
    """Get all interfaces except the one with the given IP.

    Args:
        exclude_ip: IP address of interface to exclude

    Returns:
        List of interface dicts
    """
    interfaces = get_network_interfaces()
    return [iface for iface in interfaces if iface["ip"] != exclude_ip]
