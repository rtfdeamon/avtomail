# Avtomail

Автоматизированный backend на Python для ведения многоязычной переписки с клиентами по электронной почте. Сервис подключается к IMAP/SMTP ящику, извлекает новые письма, расставляет статусы диалогов, формирует ответы через LLM (Ollama) и предоставляет REST API для менеджерского веб-интерфейса.

## Основные возможности

- FastAPI API `/api/conversations` для списка переписок, истории сообщений, отправки ответов и закрытия диалога.
- Реляционная модель данных (SQLAlchemy) с сущностями клиентов, переписок, сообщений и пользователей.
- Сервис статусов (`awaiting_response`, `answered_by_llm`, `needs_human`, `closed`) и хранение AI-черновиков.
- Интеграция с IMAP/SMTP: чтение непрочитанных писем, перемещение обработанных писем, отправка исходящих с корректными заголовками Reply-To/References.
- Интеграция с Ollama (или совместимым LLM API) для генерации черновиков ответов и сигнализации о необходимости ручной проверки.
- Автоматическое определение языка (langdetect) и ответы на языке клиента.
- Фоновый поллер `InboxPoller`, который периодически забирает письма из почтового ящика и запускает автоматизацию.
- Система аутентификации на основе JWT: вход через `/api/auth/token`, проверка текущего пользователя `/api/auth/me`, роль суперпользователя для административных действий (например, закрытие диалога).
- Расширяемое логирование и аккуратная обработка ошибок интеграций.

## Структура проекта

```
backend/
  app/
    main.py                # точка входа FastAPI
    core/                  # конфигурация и логирование
    db/                    # SQLAlchemy engine и декларативная база
    models/                # ORM-модели (Client, Conversation, Message, User)
    schemas/               # Pydantic-схемы API
    api/                   # маршруты FastAPI
    services/              # прикладные сервисы (LLM, IMAP/SMTP, автоматизация, аутентификация)
    workers/               # запуск фонового IMAP-поллера
  alembic/                 # скрипты миграций БД
  tests/                   # заготовки под тесты
pyproject.toml             # зависимости проекта
.env.example               # пример настроек окружения
```

## Требования

- Python 3.11+
- PostgreSQL (или другой поддерживаемый движок — при необходимости скорректируйте `DATABASE_URL`)
- Доступ к IMAP/SMTP ящику и экземпляру Ollama (или совместимому LLM API)

## Быстрый старт

1. Скопируйте пример настроек и заполните реальные значения:
   ```bash
   cp .env.example .env
   ```
2. Активируйте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -e .[dev]
   ```
3. Выполните миграции базы данных:
   ```bash
   alembic upgrade head
   ```
4. (Опционально) Создайте первого пользователя напрямую в БД и задайте пароль через `AuthService.hash_password` в интерактивной оболочке Python.
5. Запустите приложение:
   ```bash
   uvicorn app.main:app --reload
   ```
6. Откройте http://localhost:8000/docs, чтобы исследовать Swagger-документацию.

## API кратко

- `POST /api/auth/token` — обмен email/пароля на JWT-токен (формат OAuth2 Password Grant).
- `GET /api/auth/me` — данные текущего авторизованного пользователя.
- `GET /api/conversations` — список переписок со статусами и счётчиком ожиданий (требует авторизации).
- `GET /api/conversations/{id}` — история сообщений выбранной переписки.
- `POST /api/conversations/{id}/send` — отправить ответ (AI-черновик или ручной текст).
- `POST /api/conversations/{id}/close` — закрыть переписку (требует роли суперпользователя).

Все защищённые маршруты принимают заголовок `Authorization: Bearer <token>`.

## Миграции Alembic

Alembic уже настроен (`backend/alembic.ini`). Основные команды:

- Создать новую миграцию (после изменения моделей):
  ```bash
  alembic revision --autogenerate -m "описание изменений"
  ```
- Применить миграции:
  ```bash
  alembic upgrade head
  ```
- Откатить на один шаг назад:
  ```bash
  alembic downgrade -1
  ```

Команды выполняются из корня репозитория. Подключение берётся из `DATABASE_URL` (переменные окружения `.env`).

## Аутентификация и роли

## Управление пользователями

Для работы с учётными записями предусмотрен CLI (Typer). Запускайте его из корня проекта:

```bash
python -m app.cli.manage create-user [email] --superuser
```

Основные команды:

- `python -m app.cli.manage create-user EMAIL --superuser` — создать или обновить пользователя, при необходимости сделав его суперпользователем (пароль запрашивается интерактивно).
- `python -m app.cli.manage ensure-admin EMAIL` — гарантировать наличие суперпользователя; если пользователь уже существует, пароль не изменяется.

Команды взаимодействуют с той же БД, что и приложение, поэтому перед запуском убедитесь, что настроены переменные окружения (`DATABASE_URL`, `SECRET_KEY` и т.д.).


- Значение `SECRET_KEY` обязано быть уникальным и секретным в продакшене. По умолчанию используется алгоритм `HS256` и срок жизни токена `ACCESS_TOKEN_EXPIRE_MINUTES` минут.
- Для создания пользователя можно воспользоваться shell-сессией FastAPI/SQLAlchemy и методом `AuthService.hash_password`.
- Конечной точкой `/api/conversations/{id}/close` могут пользоваться только суперпользователи (`is_superuser = true`).

## Фоновая обработка почты

- `InboxPoller` запускается при старте FastAPI (если указаны IMAP-учётные данные) и каждые `POLL_INTERVAL_SECONDS` секунд опрашивает почтовый ящик.
- Обработку письма выполняет `AutomationService`: находит/создаёт клиента и переписку, сохраняет входящее сообщение, вызывает LLM и решает, отправлять ли ответ автоматически или пометить для менеджера.
- Успешно обработанные входящие письма можно перемещать в папку `Processed`, исходящие — дублировать в `Sent`.

## План дальнейшего развития

1. Добавить Alembic-скрипт для автоматического создания пользователя-администратора или UI для управления учётными записями.
2. Подготовить фронтенд (SPA или шаблоны) для работы менеджеров.
3. Вынести ресурсоёмкие задачи (LLM, SMTP) в очередь (Celery/RQ) для повышения устойчивости.
4. Добавить поддержку вложений и просмотр файлов.
5. Интегрировать систему мониторинга (Sentry/ELK) для отслеживания ошибок и метрик SLA.
6. Покрыть ключевые сервисы тестами и настроить CI.

## Полезные команды

```bash
uvicorn app.main:app --reload          # запуск API
pytest                                 # тесты (после добавления)
ruff check backend/app                 # статический анализ
```

### -

    `run_project.ps1`     http://127.0.0.1:8000/ (   ).       (  `python -m app.cli.manage ensure-admin`).  - :

-     ,    ;
-      ,   ,   ;
-   (     );
-   (,   , );
-     .

## One-command startup

Use the platform-specific helper to set up the virtualenv, install dependencies, apply migrations, and run the API.

```powershell
# Windows / PowerShell
pwsh scripts/dev.ps1

# Install only
pwsh scripts/dev.ps1 -InstallOnly

# Start without auto-reload
pwsh scripts/dev.ps1 -NoReload
```

```bash
# macOS / Linux
./scripts/dev.sh

# Install only
./scripts/dev.sh --install-only

# Start without auto-reload
./scripts/dev.sh --no-reload
```

The older `run_project.ps1` script remains available, but the new helpers provide the same behaviour for both Windows and POSIX environments.
