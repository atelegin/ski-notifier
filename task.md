# SKI_SNOW_NOTIFIER — Variant B (Telegram, daily 17:00, Nov–Mar)

## Goal
Каждый день (только в сезон Nov–Mar) в 17:00 Europe/Berlin отправлять в Telegram одно сообщение:
- “куда ехать завтра и почему”
- с оценкой условий (score) на основе погоды/снега
- с показом условий в 2 точках (низ/верх)
- с отображением стоимости доступа и ски-пасса (НО: цены НЕ участвуют в скоринге)

## Non-goals
- Никакой stateful-логики (никаких “помню вчера”).
- Не подтягивать цены автоматически. Ски-пасс — вручную раз в сезон (поле ski_pass_day_adult_eur).
- Никаких email. Только Telegram.

## Inputs (hardcoded)
- Список RESORTS (см. python-структуру).
- Паром Konstanz–Meersburg RT для PKW<=4m: 24.20 EUR.
- Австрийская 1-day vignette: 9.60 EUR.
- Правило: assume_ferry_used = True (можно переопределять вручную позже).

## Weather/Snow data
Источник: Open-Meteo (free).
Для каждого resort:
- Запрашиваем прогноз на завтра для двух точек: points.low и points.high.
- Окно катания: 09:00–16:00 local (Europe/Berlin; для CH/AT можно считать тем же, они рядом).

Рекомендуемые фичи (простые, без “сложных” алертов):
- temp_C_avg_9_16 (по точкам)
- wind_gust_kmh_max_9_16 (по точкам)
- precip_mm_sum_9_16 (по точкам)  # снег во время катания НЕ штрафуем
- snow_depth_cm (daily) (по точкам, если доступно)
- snowfall_cm (daily) (по точкам, если доступно)

Если snow_depth/snowfall недоступны в Open-Meteo по точке:
- fallback: использовать ближайший набор переменных (или пропускать и снижать confidence).

## Scoring (no cost inside)
Считаем два под-скора (low/high) и агрегируем.

### Per-point subscore (0..100)
- base = 50
- + clamp(snow_depth_cm, 0..60) * 0.6
- + clamp(snowfall_cm, 0..30)  * 0.4   # НЕ штрафуем снегопад, это “плюс/нейтрально”
- - max(0, wind_gust_kmh_max - 35) * 0.8
- - max(0, precip_mm_sum - 8) * 1.0     # только если очень мокро/ливень
- - max(0, temp_C_avg - 4) * 3.0        # тепло = хуже
- - max(0, -temp_C_avg - 18) * 1.0      # экстремальный холод слегка ухудшает комфорт

### Resort score
score = 0.45 * score_low + 0.55 * score_high

### Confidence (0..1)
- 1.0 если есть snow_depth и snowfall по обеим точкам
- 0.7 если нет snow_* по одной точке
- 0.4 если нет snow_* по обеим (тогда ранжируем в основном по temp/wind/precip)

## Message (single Telegram message)
Отправляем 1 сообщение в 17:00:
- Заголовок: “Завтра (YYYY-MM-DD): куда ехать”
- Рекомендация (топ-1) + 2 запасных варианта.
- Фразы:
  - Если top-1 score сильно выше остальных (например, +12 пунктов и confidence>=0.7): “завтра почти наверняка будет лучший день недели”.
  - Если у всех score < порога (например, 35): “завтра бессмысленно ехать”.

### Формат для каждого варианта
- Name — drive_time_min
- Score (0..100) + confidence
- Low: snow_depth, snowfall, temp avg, wind gust, precip (09–16)
- High: то же
- Costs line (info only):
  - “Access: ferry RT €24.20 (+ AT vignette €9.60 if AT). Skipass: €X (manual)”
  - Для XC не показывать skipass.

## Scheduling
- GitHub Actions cron:
  - каждый день в 17:00 Europe/Berlin
  - только Nov–Mar: реализовать early-exit в коде (if month not in [11,12,1,2,3] -> return without send)

## Telegram (personal bot)
- Создать бота через @BotFather, получить BOT_TOKEN.
- Узнать chat_id:
  - либо через @userinfobot
  - либо через getUpdates (после того как ты напишешь боту /start).
- Секреты хранить в GitHub Secrets:
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID

## Repo structure (suggested)
- ski_notifier/
  - resorts.py (RESORTS list)
  - fetch.py (Open-Meteo client)
  - score.py (scoring + confidence)
  - message.py (formatting)
  - main.py (orchestrator)
  - requirements.txt
- .github/workflows/ski.yml

## User tasks (you)
1) Создать репо на GitHub.
2) Завести Telegram bot через @BotFather, взять token.
3) Получить chat_id.
4) Добавить GitHub Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
5) Включить GitHub Actions (permissions default).
6) (Раз в сезон) вручную обновить ski_pass_day_adult_eur в RESORTS для alpine.

## Dev tasks (Claude Code)
1) Реализовать Open-Meteo запросы по двум точкам на “завтра”, окно 09–16.
2) Реализовать scoring + confidence (простые clamp/penalty).
3) Сгенерировать сообщение (топ-1 + 2 альтернативы, + фразы “лучший день недели” / “бессмысленно ехать”).
4) Telegram send (requests POST).
5) GitHub Actions workflow с cron 17:00 Europe/Berlin (учесть, что GH cron в UTC).
6) Добавить README с шагами setup (token/chat_id/secrets).
