# TRIADA runtime flow

## Основной поток

```mermaid
flowchart TD
    H[Human / UI] --> TS[TaskService]
    TS -->|task_started| OE[ExecutionEngine]
    OE --> O[Orchestrator]
    O -->|ExecutionContract proposal| PG[Policy Gate]
    PG -->|effective contract| OE
    OE --> B[Balancer]
    B --> S[BoundedStepScheduler]
    S --> W1[Worker 1]
    S --> W2[Worker 2]
    S --> W3[Worker 3]
    W1 --> L1[LLM preparation]
    W2 --> L2[LLM preparation]
    W3 --> L3[LLM preparation]
    L1 --> T1[Tool adapter]
    L2 --> T2[Tool adapter]
    L3 --> T3[Tool adapter]
    T1 --> E[Append-only audit events]
    T2 --> E
    T3 --> E
    E --> A[Auditor]
    A --> C[Chief auditor / human review packet]
    C --> TS
    TS --> F[Final task status]
```

Балансировщик теперь получает `resource_budget` из effective
`ExecutionContract`. Системный `SwarmContract` по-прежнему задаёт верхние
границы пар и concurrency; контракт Orchestrator может только сузить работу в
этих границах.

## Research run completion

Для целей, которые Orchestrator распознаёт как research/analysis, создаётся
`ResearchContract`. В нём фиксируются вопросы, глубина, минимальное количество
tool evidence, обязательные артефакты и схема отчёта. `CompletionGate` проверяет
этот контракт после Worker и Auditor. Поэтому успешная команда вроде `git
status` сама по себе больше не может завершить архитектурное исследование:
без `research_report` и достаточного evidence run получает
`completion_gate_failed` и статус `failed`.

LLM boundaries имеют отдельные таймеры:

- `ORCHESTRATOR_LLM_TIMEOUT_SECONDS` — planning;
- `WORKER_LLM_TIMEOUT_SECONDS` — подготовка worker step;
- `AUDITOR_LLM_TIMEOUT_SECONDS` — review evidence.

OpenAI-compatible SSE responses дополнительно ограничены абсолютным 30-секундным
stream deadline. Это важно потому, что transport read timeout ограничивает паузу
между chunks, но не общий lifetime потока, который может бесконечно присылать
частичные deltas. Deadline применяется и к ожиданию первого/следующего chunk,
поэтому silent upstream тоже завершается.

Если клиентский запрос `run_once` отменяется до завершения execution,
`TaskService` перехватывает cancellation и добавляет `task_cancelled` с причиной
`execution_cancelled`, чтобы persisted task не оставался в `running`.

Timeout planning публикует `llm_unavailable` и завершает задачу как `blocked`.
Timeout auditor публикует `audit_failed`, формирует FAIL verdict и завершает
задачу как `failed`. Ни один из этих случаев не должен оставлять task в
`running`.

Поверх компонентных таймеров `TaskService` имеет общий
`TASK_EXECUTION_TIMEOUT_SECONDS` (по умолчанию 300 секунд). Он оборачивает весь
`run_once`; если зависнет сетевой клиент или другой участок execution flow,
публикуется `task_timeout`, а задача переходит в `timed_out`.

При старте процесса `TaskService` также закрывает persisted-задачи, оставшиеся
в `running` после перезапуска API: они переходят в `timed_out`, в metadata
фиксируется `recovery.reason=process_restart`, а в append-only trail добавляется
`task_recovered`. Это предотвращает вечные orphaned-записи в Observatory UI.

Каждый worker сначала получает публичную модельную подготовку шага, затем
запускает allowlisted tool. Orchestrator не выполняет инструменты напрямую,
Auditor не меняет исходные audit events.

## Защищённый поток при зависшем LLM

```mermaid
sequenceDiagram
    participant TS as TaskService
    participant OE as ExecutionEngine
    participant W as Worker
    participant PG as Policy Gate
    participant B as Balancer
    participant LLM as LLM provider
    participant Audit as Audit repository

    TS->>OE: run_once(task)
    OE->>PG: validate ExecutionContract
    PG-->>OE: effective contract or rejection
    OE->>B: allocate within contract budget
    B-->>OE: selected workers / concurrency
    OE->>W: run_step(step)
    W->>LLM: complete_json(worker_result)
    Note over W,LLM: asyncio.wait_for(timeout=WORKER_LLM_TIMEOUT_SECONDS)
    alt LLM отвечает вовремя
        LLM-->>W: structured response
        W->>W: execute tool
        W->>Audit: worker_step_completed + tool_execution_completed
        OE->>Audit: audit verdict / review packet
        OE-->>TS: completed
    else LLM timeout или exception
        W-->>W: failed_before_tool()
        W->>Audit: worker_step_failed
        OE-->>TS: failed
        TS->>Audit: task_failed
    end
```

## Что происходило в задаче `dd654c78-df89-435a-8897-bc167345d84b`

```mermaid
flowchart LR
    P[Planning completed] --> D[3 worker steps dispatched]
    D --> A1[worker-1: succeeded]
    D --> A2[worker-2: succeeded]
    D --> A3[worker-3: waiting in LLM preparation]
    A3 --> X[Раньше: без timeout → вечный running]
    A3 --> Y[Теперь: timeout → worker_step_failed → task_failed]
```

## Настройка

`WORKER_LLM_TIMEOUT_SECONDS` задаёт максимальное время ожидания подготовки
worker-моделью. Значение по умолчанию — 60 секунд. Таймер применяется только
к вызову LLM worker’а; timeout инструментов остаётся отдельной границей
`ShellTool`/`GitTool`.
