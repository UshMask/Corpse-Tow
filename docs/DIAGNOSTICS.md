# Диагностика производительности

`CVP_Diagnostics` — отключаемый, ограниченный по памяти сборщик агрегатов.
Он не печатает ничего на каждом кадре и **не устанавливает обёртки, пока
выключен**, поэтому обычная игра не платит за него.

## Включение и выгрузка

```lua
local D = require 'CVP_Diagnostics'
D.enable()                       -- по умолчанию выключено
-- ... игровой прогон ...
print(D.report())                -- одна агрегированная таблица в лог
local snapshot = D.snapshot()    -- таблица для локального JSON
print(D.toJson(snapshot))        -- детерминированный JSON, удобно писать в local/runs/
D.disable()                      -- снять обёртки, вернуть исходные методы
```

`D.reset()` очищает только измерения (`phases/counters/gauges/memory`), но не
список установленных обёрток. Поэтому `enable → reset → disable` корректно
восстанавливает исходные методы, а повторный `enable` не накапливает слои
обёрток; это закреплено тестом `test_reset_does_not_forget_wrappers_and_cycles_do_not_stack`.

Для точечного замера без обёрток:

```lua
local mark = D.mark()
local ok, err = D.time('my.phase', myFunction, arg1, arg2)
D.count('my.events', 1)
D.gauge('my.heap', collectgarbage and collectgarbage('count') or 0, 'KB')
D.bytes('network.publish', estimatedBytes)  -- всегда помечается как оценка
D.latency('network.result', elapsedMs)
```

`D.bind('authority', runtime)`/`D.bind('motion', motion)` — подсказка, какой
живой объект оборачивать, если модули загружены вне обычного клиента/сервера.

## Что собирается

- Время `tick` мода: count/min/median/p95/p99/max/mean/stdDev, длинные выбросы
  видны по max и `samples/dropped`.
- `tick.simulate`, `tick.samples`, `tick.discover`, `tick.skeletons`, `publish`,
  `capture`, `presentation.update`, `service.tick/refresh/flush`, `save.runtime`.
- `mp.server.capture`/`mp.server.publish`/`mp.server.tick`, `mp.client.tick`.
- Счётчики: `capture.frames`, `publish.frames`, `sim.planRebuilds`,
  `graph.indexBuilds`, `graph.advanceCalls`, `obstacles.checks`,
  `host.body.misses`, `host.vehicle.misses`, `bridge.*Calls`,
  `sim.bodyLoopPasses.estimated`, `sim.linkLoopPasses.estimated`,
  `sim.solveSteps`, `action.requests/confirmed/rejected`.
- `action.latency` — от запроса игрока до подтверждённого результата.
- `network.bytes.estimate` — оценка по числу полей, **не** реальный размер пакета.
- Lua heap (`memory.checked`/KB), если доступен; GC/JVM — только реальным
  профилировщиком игры.

Все буферы и словари ограничены (`samples`, `maxPhases`, `maxCounters`,
`maxGauges`), переполнение увеличивает `overflow` и не растит память.

## Отчёты и ограничения

Формат `snapshot` стабилен: `schema='cvp-diagnostics'`, `version=1`,
`phases[]`, `counters[]`, `gauges[]`, `memory`, `hooks{installed,unavailable}`,
`overflow`. Проценты — nearest-rank по сохранившимся сэмплам, описательные.

Автономный стенд `tools/diagnostics_bench.py` повторяет матрицу 0/4/32/128
тел, повороты/торможение/назад/препятствия, запросы и MP-модель на lupa Lua 5.1:

```powershell
.venv/Scripts/python.exe -B tools/diagnostics_bench.py --phase baseline `
  --label diagnostics-baseline --output local/runs/diagnostics-baseline --write-readme
.venv/Scripts/python.exe -B tools/diagnostics_bench.py --quick --diagnostics `
  --phase adhoc --output local/runs/diagnostics-adhoc
```

Это **не FPS игры**: нет Kahlua, JVM/JIT, Bullet, Java-моста, реального рендера,
сети и сохранений. Числа годятся для сравнения одинаковых прогонов на одной
машине, но не как обещание ускорения в игре. Для профиля игры нужны отдельные
сеансы `Project.ps1`/`performance_*.py` по
[руководству разработки](DEVELOPMENT.md#производительность).
