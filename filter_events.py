#!/usr/bin/env python3
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

LEVELS = ["critical", "warn", "info"]
COLORS = {"critical": "\033[1;31m", "warn": "\033[33m", "info": "\033[2m"}
NAMES = {"critical": "критичных", "warn": "предупреждений", "info": "информационных"}
RESET = "\033[0m"
SYSTEM = platform.system()


def level_by(value, warn, crit):
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warn"
    return "info"


def gb(n):
    return f"{n / 1024 ** 3:.1f} ГБ"


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def mount_points():
    if SYSTEM == "Windows":
        return [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
    if SYSTEM != "Linux":
        return ["/"]
    real = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat", "ntfs", "ntfs3",
            "fuseblk", "9p", "f2fs"}
    points, seen = [], set()
    try:
        with open("/proc/mounts") as f:
            for line in f:
                dev, mp, fs = line.split()[:3]
                if fs in real and dev not in seen and not mp.startswith("/snap"):
                    seen.add(dev)
                    points.append(mp.encode().decode("unicode_escape"))
    except OSError:
        pass
    return points or ["/"]


def check_disks():
    out, seen = [], set()
    for mp in mount_points():
        try:
            u = shutil.disk_usage(mp)
        except OSError:
            continue
        if not u.total or (u.total, u.used) in seen:
            continue
        seen.add((u.total, u.used))
        pct = u.used / u.total * 100
        out.append((level_by(pct, 80, 90),
                    f"диск {mp} занят на {pct:.0f}% ({gb(u.used)} из {gb(u.total)})",
                    "разросшиеся логи, кэш, старые бэкапы или загрузки; "
                    "скоро может не хватить места для записи"))
    return out


def memory_info():
    """(всего, доступно, swap всего, swap свободно) в байтах или None."""
    if SYSTEM == "Linux":
        vals = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                vals[k] = int(v.split()[0]) * 1024
        return (vals["MemTotal"], vals["MemAvailable"],
                vals.get("SwapTotal", 0), vals.get("SwapFree", 0))
    if SYSTEM == "Windows":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("ptotal", ctypes.c_ulonglong), ("pavail", ctypes.c_ulonglong),
                        ("vtotal", ctypes.c_ulonglong), ("vavail", ctypes.c_ulonglong),
                        ("ext", ctypes.c_ulonglong)]

        s = Status()
        s.length = ctypes.sizeof(s)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return s.total, s.avail, 0, 0
    return None


def check_memory():
    try:
        info = memory_info()
    except (OSError, KeyError, ValueError):
        info = None
    if not info:
        return [("info", "память: на этой системе не измеряется", "")]
    total, avail, swap_total, swap_free = info
    used = total - avail
    pct = used / total * 100
    out = [(level_by(pct, 80, 90), f"память занята на {pct:.0f}% ({gb(used)} из {gb(total)})",
            "много открытых программ или утечка памяти в одном из процессов; "
            "возможны тормоза и завершение процессов системой")]
    if swap_total:
        spct = (swap_total - swap_free) / swap_total * 100
        out.append((level_by(spct, 50, 80), f"swap занят на {spct:.0f}%",
                    "не хватает оперативной памяти, система выгружает данные на диск "
                    "и работает медленнее"))
    return out


def check_load():
    cores = os.cpu_count() or 1
    if not hasattr(os, "getloadavg"):
        return [("info", f"процессор: {cores} ядер, нагрузка на этой системе не измеряется", "")]
    l1, l5, l15 = os.getloadavg()
    ratio = l1 / cores
    return [(level_by(ratio, 1.0, 2.0),
             f"нагрузка cpu {l1:.2f} / {l5:.2f} / {l15:.2f} на {cores} ядер",
             "тяжёлый процесс, зависшая программа или майнер; "
             "посмотрите top / htop, что грузит процессор")]


def check_uptime():
    if SYSTEM == "Linux":
        try:
            with open("/proc/uptime") as f:
                sec = float(f.read().split()[0])
        except OSError:
            return []
    elif SYSTEM == "Windows":
        import ctypes
        sec = ctypes.windll.kernel32.GetTickCount64() / 1000
    else:
        return []
    days, rest = divmod(int(sec), 86400)
    return [("info", f"система работает {days} д {rest // 3600} ч", "")]


def check_services():
    out = run(["systemctl", "--failed", "--no-legend", "--plain"])
    if out is None:
        return []
    units = [l.split()[0] for l in out.splitlines() if l.strip()]
    if not units:
        return [("info", "упавших systemd-служб нет", "")]
    return [("critical", f"служба не запустилась: {u}",
             f"ошибка в конфиге, занятый порт или нет зависимости; "
             f"причину покажет systemctl status {u}") for u in units]


def check_journal():
    out = run(["journalctl", "-p", "err", "--since", "-1h", "--no-pager", "-q"])
    if out is None:
        return []
    n = len([l for l in out.splitlines() if l.strip()])
    return [(level_by(n, 1, 20), f"ошибок в системном журнале за час: {n}",
             "сбои служб, драйверов или диска; подробности: journalctl -p err --since -1h")]


def check_network():
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
    except OSError:
        return [("warn", "нет доступа в интернет",
                 "отключён кабель или Wi-Fi, проблемы у провайдера, DNS или файрвол")]
    return [("info", "интернет доступен", "")]


CHECKS = [check_disks, check_memory, check_load, check_services,
          check_journal, check_network, check_uptime]


def collect():
    events = []
    for check in CHECKS:
        try:
            for level, text, hint in check():
                ev = {"event": text, "level": level}
                if hint and level != "info":
                    ev["hint"] = hint
                events.append(ev)
        except Exception as e:
            events.append({"event": f"проверка {check.__name__} не выполнена: {e}",
                           "level": "warn",
                           "hint": "нет прав или команда недоступна на этой системе"})
    return events


def ask():
    print("Что показать?  1 - critical, 2 - warn, 3 - info, 4 - всё, q - выход")
    raw = input("> ").split()
    if "q" in raw:
        return None
    if "4" in raw:
        return LEVELS
    picked = [LEVELS[int(x) - 1] for x in raw if x in ("1", "2", "3")]
    return picked or ["critical"]


def show(events, levels, source):
    shown = [e for e in events if e["level"] in levels]
    print(f"\n{source}: {len(events)} событий, показываю {', '.join(levels)}\n")
    for i, e in enumerate(shown, 1):
        lvl = e["level"]
        print(f"{i:>3}. {COLORS[lvl]}{lvl:<8}{RESET} {e['event']}")
        if e.get("hint"):
            print(f"     возможно: {e['hint']}")

    print()
    for lvl in levels:
        print(f"{NAMES[lvl]} {sum(e['level'] == lvl for e in shown)}")
    print(f"скрыто {len(events) - len(shown)}")


def main():
    args = sys.argv[1:]
    if "--file" in args:
        i = args.index("--file")
        with open(args[i + 1], encoding="utf-8") as f:
            events = json.load(f)
        source = args[i + 1]
        del args[i:i + 2]
    else:
        print(f"Анализ {socket.gethostname()} ({SYSTEM}), {time.strftime('%d.%m.%Y %H:%M')}...")
        events = collect()
        source = "анализ системы"

    if args:
        levels = LEVELS if "all" in args else [a for a in args if a in LEVELS]
        if not levels:
            sys.exit("уровни: " + ", ".join(LEVELS) + ", all")
        show(events, levels, source)
        return

    while True:
        levels = ask()
        if levels is None:
            break
        show(events, levels, source)
        print("\nEnter - назад в меню, q - выход, r - обновить данные")
        answer = input("> ").strip()
        if answer == "q":
            break
        if answer == "r" and source == "анализ системы":
            events = collect()
        print()


if __name__ == "__main__":
    main()
