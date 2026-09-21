# Фильтр событий

Читает `events.json` (8 событий уровней info, warn, critical) и выводит только
выбранные уровни. В конце считает, сколько событий каждого уровня показано.

## Запуск

Нужен Python 3.8+, зависимости не нужны.

```
python3 filter_events.py                 # меню (Enter - critical, q - выход)
python3 filter_events.py critical        # только критичные
python3 filter_events.py warn critical   # несколько уровней
python3 filter_events.py all             # все события
```

В меню после каждого результата Enter возвращает назад к выбору уровней,
`q` завершает работу. С аргументами скрипт один раз печатает результат и выходит.

## Пример

```
$ python3 filter_events.py critical

events.json: 8 событий, показываю critical

  1. critical disk 90%
  2. critical payment failed
  3. critical db timeout

критичных 3
скрыто 5
```

## Формат данных

`events.json` - список объектов `{"event": "...", "level": "info|warn|critical"}`.
Чтобы проверить другие данные, замените файл.
