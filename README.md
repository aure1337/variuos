# VLESS Checker

Проверяет VLESS конфиги на работоспособность.

## Установка

```bash
npm install
```

## Использование

1. Добавь VLESS URLs в `subscription.json`:
```json
{
  "urls": [
    "vless://uuid@server.com:443?type=ws&path=/vless#Name1",
    "vless://uuid@server2.com:443?type=ws&path=/vless#Name2"
  ]
}
```

2. Запусти проверку:
```bash
npm run check
```

3. Результаты:
- `results.json` - полный отчет
- `working.txt` - только рабочие конфиги

## Формат VLESS URL

```
vless://UUID@ADDRESS:PORT?type=NETWORK&path=PATH&security=TLS#NAME
```

Пример:
```
vless://c60f60ee-fe9b-402f-952f-c7abc2f3e5e6@example.com:443?type=ws&path=/vless&security=tls#MyServer
```
