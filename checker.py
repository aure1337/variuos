#!/usr/bin/env python3
import re
import requests
import socket
import time
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

BLACK_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt"
BLACK_MOBILE_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt"
WHITE_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-CIDR-RU-checked.txt"
TEMNUK_WIFI_URL = "https://raw.githubusercontent.com/Temnuk/naabuzil/refs/heads/main/wifi"
TEMNUK_LTE_URL = "https://raw.githubusercontent.com/Temnuk/naabuzil/refs/heads/main/lte"
TEMNUK_WHITELIST_URL = "https://raw.githubusercontent.com/Temnuk/naabuzil/refs/heads/main/whitelist"
SILENTGHOST_URL = "https://raw.githubusercontent.com/SilentGhostCodes/WhiteListVpn/refs/heads/main/Whitelist%20%E2%84%962.txt"

MAX_WORKERS = 20
TEST_TIMEOUT = 5
MAX_LATENCY_MS = 2000

COUNTRIES = {
    "baltics":     ["lithuania", "estonia", "latvia"],
    "finland":     ["finland"],
    "germany":     ["germany"],
    "sweden":      ["sweden"],
    "netherlands": ["netherlands"],
    "poland":      ["poland"],
}

WHITE_COUNTRIES = {
    "baltics":     ["lithuania", "estonia", "latvia"],
    "finland":     ["finland"],
    "germany":     ["germany"],
    "sweden":      ["sweden"],
    "netherlands": ["netherlands"],
    "poland":      ["poland"],
}

COUNTRIES_ALL_KEYWORDS = [kw for kws in COUNTRIES.values() for kw in kws]
WHITE_COUNTRIES_ALL_KEYWORDS = [kw for kws in WHITE_COUNTRIES.values() for kw in kws]

SKIP_COUNTRY_NAMES = {"anycast", "anycast-ip", "unknown"}



def parse_country_from_key(key):
    """Returns (country_name, flag_emoji) parsed from the key's URL fragment."""
    if '#' not in key:
        return None, None
    from urllib.parse import unquote
    fragment = unquote(key.split('#', 1)[1])
    match = re.search(
        r'([A-Z][A-Za-z\u00C0-\u017E](?:[A-Za-z\u00C0-\u017E\s\-]*[A-Za-z\u00C0-\u017E])?)(?:\s*[,|])',
        fragment
    )
    if not match:
        return None, None
    country = match.group(1).strip()
    flag = fragment[:match.start()].strip()
    return country, flag


def fetch_keys(url):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    lines = resp.text.strip().splitlines()
    keys = [line.strip() for line in lines if line.strip().startswith("vless://")]

    # Очистка от рекламы в именах ключей
    cleaned_keys = []
    for key in keys:
        # Убираем рекламные домены из имен
        key = key.replace('@xex_vpn', '@server')
        key = key.replace('@XEX_VPN', '@server')
        key = key.replace('xex_vpn', 'server')
        key = key.replace('XEX_VPN', 'server')
        cleaned_keys.append(key)

    return cleaned_keys


def filter_keys(keys, mode):
    countries_dict = WHITE_COUNTRIES if mode.startswith("w_") or mode == "russia" else COUNTRIES

    if mode in countries_dict:
        keywords = countries_dict[mode]
        return [k for k in keys if any(kw in k.lower() for kw in keywords)]
    if mode == "other":
        return [k for k in keys if not any(kw in k.lower() for kw in COUNTRIES_ALL_KEYWORDS) and "russia" not in k.lower()]
    if mode == "russia":
        return [k for k in keys if "russia" in k.lower()]
    if mode.startswith("w_"):
        country = mode[2:]
        if country in WHITE_COUNTRIES:
            keywords = WHITE_COUNTRIES[country]
            return [k for k in keys if any(kw in k.lower() for kw in keywords)]
        if country == "other":
            return [k for k in keys if not any(kw in k.lower() for kw in WHITE_COUNTRIES_ALL_KEYWORDS) and "russia" not in k.lower()]
    return keys


def parse_host_port(key):
    try:
        without_scheme = key[len("vless://"):]
        at_idx = without_scheme.rfind("@")
        after_at = without_scheme[at_idx + 1:]
        host_port = after_at.split("?")[0].split("#")[0]
        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
            return host.strip("[]"), int(port)
    except Exception:
        pass
    return None, None


def test_key(key):
    host, port = parse_host_port(key)
    if not host:
        return None
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except Exception:
        return None
    best = None
    for (family, socktype, proto, canonname, sockaddr) in infos:
        start = time.time()
        try:
            sock = socket.socket(family, socktype)
            sock.settimeout(TEST_TIMEOUT)
            result = sock.connect_ex(sockaddr)
            sock.close()
            elapsed = round((time.time() - start) * 1000, 1)
            if result == 0 and elapsed <= MAX_LATENCY_MS:
                if best is None or elapsed < best["latency_ms"]:
                    best = {"key": key, "host": host, "port": port, "latency_ms": elapsed}
        except Exception:
            pass
    return best


def check_mode(keys, old_first_seen=None):
    if old_first_seen is None:
        old_first_seen = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    working = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_key, key): key for key in keys}
        for future in as_completed(futures):
            result = future.result()
            if result:
                working.append(result)

    working.sort(key=lambda x: x["latency_ms"])

    for r in working:
        r["first_seen"] = old_first_seen.get(r["key"], now)

    return {
        "best": working[0]["key"] if working else None,
        "top10": working[:10],
        "total_working": len(working),
        "total": len(keys),
    }


def load_old_first_seen():
    try:
        with open("docs/keys.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        seen = {}
        for mode_data in old.values():
            top_key = "top10" if "top10" in mode_data else "top5"
            if isinstance(mode_data, dict) and top_key in mode_data:
                for entry in mode_data[top_key]:
                    if "key" in entry and "first_seen" in entry:
                        seen[entry["key"]] = entry["first_seen"]
        return seen
    except Exception:
        return {}


def main():
    old_first_seen = load_old_first_seen()

    print("Загружаем BLACK ключи...")
    black_keys = fetch_keys(BLACK_URL)
    print(f"Загружено {len(black_keys)} BLACK ключей")

    print("Загружаем BLACK mobile ключи...")
    black_mobile_keys = fetch_keys(BLACK_MOBILE_URL)
    print(f"Загружено {len(black_mobile_keys)} BLACK mobile ключей")

    print("Загружаем TEMNUK WiFi ключи...")
    try:
        temnuk_wifi_keys = fetch_keys(TEMNUK_WIFI_URL)
        print(f"Загружено {len(temnuk_wifi_keys)} TEMNUK WiFi ключей")
    except Exception as e:
        print(f"Ошибка загрузки TEMNUK WiFi: {e}")
        temnuk_wifi_keys = []

    black_keys = list(dict.fromkeys(black_keys + black_mobile_keys + temnuk_wifi_keys))
    print(f"Итого уникальных BLACK ключей: {len(black_keys)}")

    print("Загружаем WHITE ключи...")
    white_keys = fetch_keys(WHITE_URL)
    print(f"Загружено {len(white_keys)} WHITE ключей")

    print("Загружаем TEMNUK Whitelist ключи...")
    try:
        temnuk_white_keys = fetch_keys(TEMNUK_WHITELIST_URL)
        print(f"Загружено {len(temnuk_white_keys)} TEMNUK Whitelist ключей")
    except Exception as e:
        print(f"Ошибка загрузки TEMNUK Whitelist: {e}")
        temnuk_white_keys = []

    print("Загружаем SilentGhost Whitelist ключи...")
    try:
        silentghost_keys = fetch_keys(SILENTGHOST_URL)
        print(f"Загружено {len(silentghost_keys)} SilentGhost ключей")
    except Exception as e:
        print(f"Ошибка загрузки SilentGhost: {e}")
        silentghost_keys = []

    white_keys = list(dict.fromkeys(white_keys + temnuk_white_keys + silentghost_keys))
    print(f"Итого уникальных WHITE ключей: {len(white_keys)}")

    results = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    for country in list(COUNTRIES.keys()):
        filtered = filter_keys(black_keys, country)
        print(f"[{country}] {len(filtered)} ключей, проверяем...")
        results[country] = check_mode(filtered, old_first_seen)
        print(f"[{country}] Рабочих: {results[country]['total_working']}/{results[country]['total']}")

    other_keys = filter_keys(black_keys, "other")
    print(f"[other] {len(other_keys)} ключей, группируем по странам...")
    country_groups = defaultdict(list)
    country_flags = {}
    for key in other_keys:
        name, flag = parse_country_from_key(key)
        if not name or name.lower() in SKIP_COUNTRY_NAMES:
            name = "Other"
            flag = "🌍"
        country_groups[name].append(key)
        if name not in country_flags:
            country_flags[name] = flag

    other_countries = {}
    for name, keys in country_groups.items():
        print(f"  [{name}] {len(keys)} ключей, проверяем...")
        checked = check_mode(keys, old_first_seen)
        print(f"  [{name}] Рабочих: {checked['total_working']}/{checked['total']}")
        checked["flag"] = country_flags[name]
        other_countries[name] = checked
    results["other_countries"] = other_countries

    white_modes = ["w_" + c for c in WHITE_COUNTRIES.keys()] + ["w_other", "russia"]
    for mode in white_modes:
        filtered = filter_keys(white_keys, mode)
        print(f"[{mode}] {len(filtered)} ключей, проверяем...")
        results[mode] = check_mode(filtered, old_first_seen)
        print(f"[{mode}] Рабочих: {results[mode]['total_working']}/{results[mode]['total']}")

    os.makedirs("docs", exist_ok=True)
    with open("docs/keys.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("Сохранено в docs/keys.json")

    # Генерация подписок
    print("\nГенерация подписок...")
    generate_subscriptions(results)


def generate_subscriptions(results):
    """Генерирует файлы подписок для WiFi и LTE"""

    # Собираем все рабочие ключи
    all_working_keys = []

    # BLACK ключи (обычный VPN)
    for country in COUNTRIES.keys():
        if country in results and results[country].get('top10'):
            all_working_keys.extend([item['key'] for item in results[country]['top10']])

    # Other countries
    if 'other_countries' in results:
        for country_data in results['other_countries'].values():
            if country_data.get('top10'):
                all_working_keys.extend([item['key'] for item in country_data['top10']])

    # WHITE ключи (белые списки)
    for mode in ["w_" + c for c in WHITE_COUNTRIES.keys()] + ["w_other", "russia"]:
        if mode in results and results[mode].get('top10'):
            all_working_keys.extend([item['key'] for item in results[mode]['top10']])

    # Убираем дубликаты
    all_working_keys = list(dict.fromkeys(all_working_keys))

    # WiFi подписка (все ключи)
    wifi_header = """#profile-title: 🌐 VPN Keys Hub WiFi
#announce: Совет: Настройки>Подписки>Сортировать по пингу, затем нажми на спидометр. Меньше ms лучше, регулярно нажимайте на 🔄️
#profile-update-interval: 1
#support-url: https://github.com/aure1337/vless-private
#profile-web-page-url: https://aure1337.github.io/vless-private/

"""

    with open("docs/subscribe_wifi.txt", "w", encoding="utf-8") as f:
        f.write(wifi_header)
        f.write("\n".join(all_working_keys))

    print(f"✅ WiFi подписка: {len(all_working_keys)} ключей → docs/subscribe_wifi.txt")

    # LTE подписка (топ-50 самых быстрых)
    # Собираем ключи с latency
    keys_with_latency = []

    for country in COUNTRIES.keys():
        if country in results and results[country].get('top10'):
            keys_with_latency.extend(results[country]['top10'])

    if 'other_countries' in results:
        for country_data in results['other_countries'].values():
            if country_data.get('top10'):
                keys_with_latency.extend(country_data['top10'])

    for mode in ["w_" + c for c in WHITE_COUNTRIES.keys()] + ["w_other", "russia"]:
        if mode in results and results[mode].get('top10'):
            keys_with_latency.extend(results[mode]['top10'])

    # Сортируем по latency и берем топ-50
    keys_with_latency.sort(key=lambda x: x['latency_ms'])
    top_lte_keys = [item['key'] for item in keys_with_latency[:50]]
    top_lte_keys = list(dict.fromkeys(top_lte_keys))  # Убираем дубликаты

    lte_header = """#profile-title: 📱 VPN Keys Hub LTE
#announce: Совет: Настройки>Подписки>Сортировать по пингу, затем нажми на спидометр. Меньше ms лучше, регулярно нажимайте на 🔄️
#profile-update-interval: 1
#support-url: https://github.com/aure1337/vless-private
#profile-web-page-url: https://aure1337.github.io/vless-private/

"""

    with open("docs/subscribe_lte.txt", "w", encoding="utf-8") as f:
        f.write(lte_header)
        f.write("\n".join(top_lte_keys))

    print(f"✅ LTE подписка: {len(top_lte_keys)} ключей (топ-50 быстрых) → docs/subscribe_lte.txt")


if __name__ == "__main__":
    main()
