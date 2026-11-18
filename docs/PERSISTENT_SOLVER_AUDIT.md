# Независимый аудит solver / persistent gameplay path

Дата измерений: 12 ноября 2026. Проверяемый public HEAD:
`112257aa610b91b81ac6f2cae9bf4b664732714e` (`optimize/solver`),
база: `a892f588955edc88f9377df655ed39c651ba52d8`.

## Границы вывода

Этот PR исправляет доказательную базу, benchmark и regression oracle. Он не
меняет production Java/Lua solver, сопротивление машины, сходимость, число
итераций, поиск с 28 пробами, rendering, item/save/network формат.
Предложение заменить поиск бисекцией не включено.

Установленная игра фактически **42.22.2, build `3d39148846`**, а не запрошенная
42.21. Это установлено по console сегодняшнего изолированного запуска. Поэтому
проверка native зависимостей текущей установки не означает проверку B42.21.
Компилятор: `javac 25.0.4.1`; игровой runtime: Zulu `25.0.5+8-LTS`.
ZombieBuddy: `2.3.4`; Viewpoint: `0.1.6.2` (build 2026-11-09).

## Подтверждённые проблемы прежних доказательств

1. Старый benchmark вызывал `solve()`, тогда как
   [CVP_LinkSimulation.lua](../CorpseProxyLab/42/media/lua/shared/CVP_LinkSimulation.lua)
   вызывает `solvePersistent()`. Переносить прежнее ускорение на gameplay было нельзя.
2. Доказательство по minimum нескольких коротких runs не характеризовало ни
   per-tick tail latency, ни независимость JVM/JIT, ни чувствительность к AB/BA.
3. Исходный native oracle не давал полноценной old/new Java проверки обеих API;
   Java/Lua сравнение покрывало legacy path. Геометрия была слишком однообразной;
   rollback проверял ранний отказ, но не отказ после успешно выполненных подшагов.
4. Фиксированные raw CRLF-хэши frozen fixtures не переносились на LF checkout.
   Теперь проверяется pinned canonical UTF-8/LF содержимое; raw SHA256 также
   сохраняется для provenance. Исходные fixtures не менялись.
5. Primary checksum и hash-guard недостаточны как отрицательный контроль физики:
   семантически изменённый solver должен компилироваться и падать именно на
   numerical oracle, а не только на file-integrity guard.

## Проверка кэшей и состояния

В production diff не найдено подтверждённой новой ошибки физики.

- Java original-angle и candidate-angle trig хранятся раздельно; candidate trig
  перепроверяет сам angle. Перемещение родителя/ребёнка не сохраняется как
  геометрия между constraint evaluations.
- `measure()` перечитывает текущие candidate endpoints. Только две неизменяющие
  pose residual-ветви soft/hard используют общее измерение; correction измеряет
  геометрию заново. Scratch entries ниже порога distance не читаются как валидные.
- Old-foot geometry, weight/inertia, alpha/gamma и anchor velocity вычисляются
  заново на каждом подшаге. Они постоянны только внутри его iterative solve.
- Lua сохраняет только substep-инварианты; source родителя и candidate endpoints
  вычисляются при каждом evaluation. Нет общего Lua geometry cache между solve.
- Persistent state сохраняет историю, а mutable pose/mass/length/push/spread inputs
  перечитываются. Reset commands, release/backend switch, rebuild topology и
  rollback рассматриваются отдельно от обычного успешного solve.
- Rollback — это восстановление native motion/constraint history при world-read
  ошибке, включая ошибку после завершённого подшага. Это **не атомарная транзакция
  всех Kahlua `rawset` и фактических игровых тел**. OOM/custom-table failure
  непосредственно при publication не проверен. Следующий `Sim:restore()` и
  журналирование apply failures — отдельный, уже существовавший контракт.
- Lifecycle release/build уже существовал до оптимизации. Проверка не является
  доказательством корректности произвольного стороннего изменения supposedly
  immutable footprint/attachment без rebuild; реальные lifecycle контракты
  [CVP_LinkSimulation.lua](../CorpseProxyLab/42/media/lua/shared/CVP_LinkSimulation.lua)
  остаются обязательными.

Уровень уверенности ограничен представленными сценариями и версией зависимостей,
а не формальным доказательством всех возможных Lua records.

## Методика benchmark v2

[Java harness](../tests/BenchmarkTowingSolver.java),
[Python runner](../tools/solver_bench.py),
[unit tests статистики и схемы](../tests/test_solver_bench.py).

- Frozen old и current компилируются из исходников в одном окружении; baseline
  переименован, исходные fixtures pinned и совпадают с base после EOL normalization.
- Обе API; `prepare` один раз на группу, `release` в `finally`. Четыре группы по
  32 — это 128 тел в сумме, не неподдерживаемая одна группа из 128 тел.
- Свежие JVM forks; AB/BA чередуется по pair и fork. Одна pair не считается новой
  независимой JVM. Полные raw tick sequences сохраняются отдельно по fork.
- API time включает native sync/read + physics/world queries + publication/write.
  Input-table updates, anchor seed reads, checksum/diagnostics, fixture creation,
  prepare и release измеряются отдельно. Нельзя называть API time «чистым ядром».
- Отдельный bridge microbenchmark выполняется **после всех основных измерений**
  на cloned initialized fixtures. Он измеряет `Body.read(mode)` и
  `Body.write(mode)`, исключает group publication и не моделирует всю Lua-работу
  игрового тика. Это не аддитивная декомпозиция: вычитать эти числа из API нельзя.
- Median/p95/p99/max вычисляются из raw tick timings внутри каждой pair.
  Затем показывается междуforkовый разброс. Nearest-rank quantile; median для
  чётного числа samples — среднее двух центральных. Нельзя смешивать миллион
  ticks и объявлять их миллионом независимых performance replicas.
- No-call idle — только timer/loop control, без solver speedup. Timer overhead
  не вычитается. Max включает выбросы ОС/GC; это не обещание real-time deadline.
- Checksum накапливается по return/published state каждого tick; сохраняется
  итоговый digest sequence и полный digest history после release. Проверяется
  воспроизводимость между pairs/forks, не публикуется отдельный digest каждого tick.
- Published workload diagnostics не включают production `solverCounters`.
  Straight-chain может быть mostly slack; gap/failure сцены не используются как
  throughput proxy. Ненулевая нагрузка/iterations/error flags доступны в raw report.

## Воспроизведение

Нужны законно установленная игра и Java dependencies; они не распространяются
в evidence. Настройте `local/settings.json` по ключам `Game`, `Jdk`,
`ZombieBuddy`, `Viewpoint`. Windows classpath и игровые natives обязательны.
Изолированный benchmark не запускает обычные saves и не требует GUI.

```powershell
python -B tools/ci_tests.py
$env:CVP_REQUIRE_NATIVE='1'
python -B -m unittest discover -s tests -p test_solver_equivalence.py -v
python -B tools/solver_bench.py --forks 4 --repeats 4 --warmup 2 --warmup-ticks 3000 --ticks 6000 --output local/runs/solver-bench-reproduction
```

Если dependency отсутствует, native-проверка должна завершиться ошибкой в
mandatory mode, а не маскироваться как успешный skip. Evidence текущей машины
не заменяет повтор на целевом B42.21.

### Java build и проверяемый артефакт

Публичный source snapshot не распространяет game JAR/dependencies и не включает
локальный build orchestration. Полную production-компиляцию можно воспроизвести
из PowerShell, отдельно от native validators:

```powershell
$s = Get-Content local/settings.json -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Force local/audit-rebuild/classes | Out-Null
$sources = @(Get-ChildItem CorpseProxyLab/source -Recurse -Filter '*.java' -File | ForEach-Object FullName)
& "$($s.Jdk)/bin/javac.exe" -encoding UTF-8 -cp "$($s.Game)/projectzomboid.jar;$($s.Game)/*;$($s.ZombieBuddy);$($s.Viewpoint)" -d local/audit-rebuild/classes @sources
if ($LASTEXITCODE) { throw 'javac failed' }
& "$($s.Jdk)/bin/jar.exe" --create --date=2026-01-01T00:00:00Z --file local/audit-rebuild/CorpseProxyWorld.jar -C local/audit-rebuild/classes cvpworld -C local/audit-rebuild/classes cvprender
if ($LASTEXITCODE) { throw 'jar failed' }
```

Для проверки **реально распространяемого** артефакта положите именно его в
`CorpseProxyLab/42/media/java/CorpseProxyWorld.jar` перед mandatory oracle.
Нельзя подменить его только что скомпилированным JAR и заявить, что проверена
другая опубликованная сборка. На текущей машине JAR уже существовал; проверка
сравнивает не только top-level class, но **все `TowingSolver*.class`**, включая
`Body`, `State`, `Pose`. Negative control меняет только вложенный class при
неизменном top-level и обязан отвергаться.

Хэш ZIP/JAR зависит от packaging timestamps; равенство source/bytecode и хэш
фактически проверенного архива фиксируются отдельно. Не обещается идентичный
архив после запуска другого build recipe.

Дополнительная проверка **всех** production classes после приведённой полной
компиляции (Python; для локального audit использован output официального build):

```python
from pathlib import Path
from zipfile import ZipFile
classes = Path('local/audit-rebuild/classes')
jar = Path('CorpseProxyLab/42/media/java/CorpseProxyWorld.jar')
expected = {p.relative_to(classes).as_posix(): p for p in classes.rglob('*.class')
            if p.relative_to(classes).parts[0] in ('cvpworld', 'cvprender')}
with ZipFile(jar) as z:
    assert set(expected) == {n for n in z.namelist() if n.endswith('.class')}
    for name, p in expected.items():
        assert p.read_bytes() == z.read(name), name
print('PASS class inventory/bytes:', len(expected))
```

## Correctness и build

- Финальный portable CI: **247 tests PASS**, 17.258 s в execution checkout и
  16.527 s в изолированном public worktree от reviewed commit. Это отдельный
  набор, не замена mandatory native oracle или live gameplay.

- Полная сборка production Java: **18 запусков native validators PASS** (включая
  shader/GPU feedback; optional Viewpoint absent/present и DynamicCorpses
  disabled/absent/present). Это число запусков validator, не unit-test assertions.
- Финальный `CVP_REQUIRE_NATIVE=1` oracle после окончания сборки: **2 теста PASS,
  61,846 с; 30 сценариев; 2 112 346 сравнений; максимальная числовая ошибка 0**.
  Есть old/new для обеих Java API, old/new Lua и Java/Lua, off-axis geometry,
  изменяемые mass/length/height/z/elasticity, switch/recovery и delayed rollback.
- Delayed rollback: 49 обращений к миру завершаются, ошибка инъецируется на 50-м
  после законченного движущего подшага; следующие пять ticks сравниваются с
  отдельным нетронутым состоянием. Это проверка истории, не atomic world commit.
- Три настоящих semantic mutants (**Java oldDistance +0,01; Java stale candidate
  trig; Lua oldDistance +0,01**) компилируются/инициализируются и отвергаются
  numerical oracle после успешного `nativeSmoke`, а не одним source hash guard.
- Все **4 `TowingSolver*.class`** совпадают с пересобранными source. Отдельный
  nested-only mutant повреждает только `Body.class`: он отвергнут даже при
  одинаковом хэше top-level class.
- Дополнительная inventory/byte проверка всей сборки: **74 production class
  entries** в JAR точно совпали с output полной компиляции, без missing/extra
  `.class`. **82 Java/shared-Lua source** совпали с public worktree после только
  CRLF→LF нормализации. Отдельный JSON сохраняет хэши каждого class/source.
- Проверенный после build архив SHA256:
  `D18A09978B13EB9EB1724AEBDAC499CD517E5AAF528B1C5CC281E20A0DEDE18E`.
  В public snapshot JAR не отслеживается: это provenance локально проверенного
  архива, не заявление о каждом когда-либо скачанном релизе.

## Реальные SP/MP: попытки, не PASS

| Проверка | Фактический результат |
|---|---|
| SP, изолированный профиль | `TimeoutError: World API not ready`; ни одной завершённой сцены |
| MP, первая попытка | Не найдена default standalone assets directory; ошибка конфигурации до запуска |
| MP, matching standalone assets | Сервер 42.22.2 остановился перед world startup: ZombieBuddy `pendingEntries=2`, требуется интерактивное одобрение Java-модов |
| 2 клиента, idle/4–8/32/4×32, манёвры/препятствия | **Не проверено** в игре |
| Reconnect, chunks, save/load | **Не выполнялось** |
| FPS / frame-time | **Не измерено** |
| B42.21 | **Не проверено**: установлена другая версия |

Причина SP failure не установлена; это не доказательство cache-регрессии.
ZombieBuddy approval не обходился. Штатный MP stop отказался работать без
loopback RCON (сервер ещё не стартовал). Затем завершены только точный audit
server PID с проверкой cache/времени создания и связанный approval subprocess,
до загрузки мира. Обычные saves и посторонние процессы не затрагивались.

## Условия измерений и ограничения

Intel Core i7-12700KF, 12 cores / 20 logical processors, около 31,85 GiB RAM,
Windows 11 Pro Insider 10.0.26340, RTX 4070; power plan «Максимальная
производительность». Affinity не фиксировался, thermals не измерялись.

Перед финальной серией нет иных Java/PZ процессов или тяжёлых audit tests, но
наблюдалась заметная нагрузка **посторонних интерактивных/системных приложений**
(preflight total CPU 45%). Они не останавливались. Это **не тихий стенд**.
AB/BA и независимые JVM уменьшают некоторые order/JIT эффекты, но не устраняют
background-load confound. Warmup задан, а steady state JIT не доказан.
Проверка native equivalence и build не является измерением performance.

**Граница workload:** bounded ±3 м root motion и начальная spacing 0,8 м при
length 1,4 м оставляют значительную часть длинной цепи slack. В основной серии
`chain8` и `chain32-weave` имеют одинаковые 7782 iterations и 2992 load ticks,
но разное число body read/write/geometry operations. Это не fully-taut stress
всех 32 звеньев. Полностью натянутая длинная цепь под sustained нагрузкой и
реальная сцена с препятствиями остаются отдельным непокрытым acceptance-case;
по числу records нельзя делать вывод о числе одновременно напряжённых звеньев.

Первый незавершённый long run исключён: gap-fixture сочетал 200 м teleport с
`maxGapSquared=10000`, разрешая дорогое частичное протягивание до gap rejection.
Только в benchmark-сцене `chain32-jump-gap` cutoff исправлен до 4 м
(`maxGapSquared=16`), чтобы даже минимальный интерполированный скачок отвергался
до sweeps. Production не изменён. Проверяется повторный полный прогон с новым
хэшем harness; error/gap controls не служат proxy throughput обычного движения.

## Итоговые измерения

**Две серии PASS**, без повторного использования JVM:

1. 18 сцен (17 с обеими API + idle): **4 forks × 4 AB/BA-пары × 6000 ticks**,
   warmup 2 × 3000 ticks на сторону.
2. Независимый stability-repeat для chain4/8/32-weave/4×32: **4 новых forks ×
   2 пары × 9000 ticks**, warmup 3 × 6000 ticks на сторону. Перед этой серией
   total CPU snapshot 23%; стенд всё ещё не quiet.

Все полные raw серии валидированы повторно: checksum/released-history checksum
совпадают old/new и между pairs/forks; published diagnostics old/new равны.
Summary и bridge diagnostics **точно регенерированы из raw JSON**, hashes
harness/runner соответствуют финальным опубликованным исходникам.

### Основная серия: API включает read/sync + physics/world + publication

Median/p95/p99 ниже — медиана **4 fork-level медиан** соответствующего per-run
stat; per-run p95/p99 используют nearest rank. Max — худший tick всей серии.
Ratio — медиана 4 fork-level медиан парных **sum(old API ns)/sum(new API ns)**;
это не отношение показанных median. Диапазон в скобках — min/max этих 4 fork
ratios, не confidence interval. Внутри-fork pairs коррелированы. Значение ratio
>1 означает быстрее, <1 — медленнее.

| Workload / API | Median µs old → new | p95 µs | p99 µs | Max ms | Old/new total [fork min,max] | AB / BA ratio median | Fork-median CV old/new |
|---|---:|---:|---:|---:|---:|---:|---:|
| chain4 / `solve` | 3.000 → 2.700 | 13.750 → 11.900 | 21.675 → 18.775 | 0.843 → 0.983 | 1.136 [1.102,1.168] | 1.129 / 1.128 | 0.4% / 1.8% |
| chain4 / `solvePersistent` | 2.700 → 2.450 | 13.525 → 11.375 | 20.850 → 17.600 | 0.832 → 0.989 | 1.167 [1.104,1.190] | 1.172 / 1.168 | 0.9% / 2.4% |
| chain8 / `solve` | 7.600 → 6.050 | 43.375 → 31.775 | 78.375 → 54.875 | 1.317 → 1.317 | 1.323 [1.311,1.348] | 1.333 / 1.334 | 1.9% / 2.0% |
| chain8 / `solvePersistent` | 7.062 → 5.625 | 42.800 → 31.525 | 78.050 → 52.475 | 1.320 → 1.191 | 1.352 [1.326,1.374] | 1.359 / 1.347 | 2.5% / 4.1% |
| chain32-weave / `solve` | 23.262 → 20.650 | 119.000 → 102.450 | 207.100 → 172.875 | 3.966 → 1.948 | 1.151 [1.115,1.210] | 1.150 / 1.155 | 10.7% / 4.6% |
| chain32-weave / `solvePersistent` | 21.025 → 19.075 | 115.500 → 101.075 | 204.275 → 171.150 | 1.456 → 1.395 | 1.154 [1.103,1.180] | 1.148 / 1.163 | 9.7% / 10.8% |
| 4×chain32 / `solve` | 93.888 → 86.400 | 478.950 → 420.750 | 852.150 → 699.775 | 8.285 → 5.605 | 1.141 [1.110,1.237] | 1.132 / 1.145 | 8.7% / 2.6% |
| 4×chain32 / `solvePersistent` | 85.188 → 77.375 | 464.350 → 408.300 | 844.650 → 697.100 | 5.315 → 4.437 | 1.144 [1.119,1.153] | 1.155 / 1.133 | 2.5% / 2.6% |

`4×32` — сумма четырёх независимых вызовов валидных групп по 32, **не** группа
из 128 и не game frame time. CV — descriptive spread при n=4, не оценка FPS.
Сырые данные всех остальных сцен доступны, не только выбранные строки.

### Более длинный warmup/sequence: gameplay API повторился, но max не гарантирован

| Workload | Median µs old → new | p95 µs | p99 µs | Max ms | Old/new total [fork min,max] |
|---|---:|---:|---:|---:|---:|
| chain4 | 2.700 → 2.425 | 12.425 → 10.650 | 18.075 → 15.625 | 0.827 → 1.056 | 1.151 [1.137,1.176] |
| chain8 | 6.750 → 5.200 | 41.375 → 29.425 | 77.525 → 49.650 | 1.200 → 0.897 | 1.364 [1.271,1.391] |
| chain32-weave | 20.188 → 17.900 | 113.500 → 95.800 | 204.900 → 165.675 | 2.277 → 1.564 | 1.161 [1.146,1.175] |
| 4×chain32 | 83.100 → 74.175 | 453.950 → 385.975 | 834.525 → 668.075 | 6.232 → 6.135 | 1.157 [1.099,1.178] |

Для legacy `solve()` в этом repeat total ratios: 1.157 / 1.340 / 1.116 / 1.158
соответственно. Полные tails/order/spread обеих API находятся в report/CSV.
**Не универсальный speedup:** в основной серии single-rope legacy ratio 0.837,
gameplay 0.996; single-rope-wall gameplay 0.979. Одиночные сцены не получили
убедительного полезного gain. Max chain4 стал хуже в обеих сериях; нельзя
обещать улучшение каждого tail или отсутствие GC/scheduling spikes.

### External и bridge diagnostics — отдельно, без вычитания

Основная серия, `solvePersistent`; µs, old → new. External tick stats — median
по per-run medians; prepare/release — разовая сумма групп за sequence, не tick.

| Workload | Input update | Seed read | Checksum/diagnostic reads | Prepare | Release |
|---|---:|---:|---:|---:|---:|
| chain32-weave | 1.000 → 1.000 | 0.000 → 0.000 | 3.600 → 3.600 | 32.350 → 31.100 | 3.150 → 3.100 |
| 4×chain32 | 4.000 → 4.000 | 0.100 → 0.100 | 14.950 → 14.900 | 117.550 → 114.250 | 10.100 → 9.800 |

Bridge **clone** microdiagnostics после primary timings: Body.read для 32 —
3.300 → 3.300 µs; Body.write — 1.700 → 1.700 µs. Для 4×32 — 13.500 → 13.250 и
7.050 → 6.850 µs. Они исключают group publication, не являются разложением
реального API. Изолированный solver-core time **не установлен**; вычитать
clone timings из API неправомерно. Lifecycle чувствителен к шуму: в repeat
prepare/release 32 выросли до 69.000/13.550 µs у new против 33.000/3.500 old;
эти одноразовые значения нельзя спрятать в steady-state delta.

Нулевой seed-read отсчёт — timer quantization, не бесплатная операция.
Idle/no-call измеряет timer/пустой loop: нулевые отдельные/медианные отсчёты
обусловлены quantization, не нулевой latency solver. API calls/solver work равны
нулю, ratio не вычисляется.

Для основной серии у chain32-weave: 7782 iterations, 2992/6000 load ticks,
max residual 8.32999546e-6; gap/obstruction/unconverged/fallback = 0.
У 4×32: 31128 iterations, те же 2992 load ticks. У gap-control 2495/6000 gap
ticks; это корректный early-out, не throughput результат. Все diagnostics
совпадают old/new во всех pairs обеих серий.

### Опубликованный corpus

- [Manifest: SHA256/размер каждого разрешённого payload](performance/solver-audit-20261112/manifest.json).
- Основная серия: [JSON](performance/solver-audit-20261112/benchmark-1/report.json),
  [CSV](performance/solver-audit-20261112/benchmark-1/results.csv), raw
  [fork 0](performance/solver-audit-20261112/benchmark-1/fork-00.json.gz),
  [1](performance/solver-audit-20261112/benchmark-1/fork-01.json.gz),
  [2](performance/solver-audit-20261112/benchmark-1/fork-02.json.gz),
  [3](performance/solver-audit-20261112/benchmark-1/fork-03.json.gz).
- Stability: [JSON](performance/solver-audit-20261112/benchmark-2/report.json),
  [CSV](performance/solver-audit-20261112/benchmark-2/results.csv), raw
  [fork 0](performance/solver-audit-20261112/benchmark-2/fork-00.json.gz),
  [1](performance/solver-audit-20261112/benchmark-2/fork-01.json.gz),
  [2](performance/solver-audit-20261112/benchmark-2/fork-02.json.gz),
  [3](performance/solver-audit-20261112/benchmark-2/fork-03.json.gz).
- [Native oracle report](performance/solver-audit-20261112/oracle/report.json),
  [oracle console](performance/solver-audit-20261112/oracle/oracle.log);
  negative-controls и build logs находятся в соседних каталогах corpus.
- [Environment/live coverage](performance/solver-audit-20261112/tests/audit-measurement-context.json),
  [74-class/source proof](performance/solver-audit-20261112/tests/audit-jar-correspondence.json),
  [raw regeneration checks](performance/solver-audit-20261112/tests/audit-raw-validation.log).

Gzip deterministic/lossless для samples. Redaction затрагивает только private
path strings; game/dependency binaries, credentials, private settings и сырые
SP/MP server logs не публикуются. JSON raw filename references сохраняют `.json`;
для replay сначала распакуйте `.json.gz` в scratch directory. Никакие значения
timings/checksums/diagnostics при экспорте не округляются. Финальная проверка
всех **50 payloads** подтвердила manifest SHA/размер, UTF-8/JSON, privacy scan;
все 8 распакованных raw JSON объектов совпали с оригиналами, оба report/CSV —
побайтово. Не нужно верить только округлённой таблице:

```python
import gzip, hashlib, json
from pathlib import Path
from tools import solver_bench as b
base = Path('docs/performance/solver-audit-20261112')
manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
for name, meta in manifest['files'].items():
    data = (base / name).read_bytes()
    assert len(data) == meta['bytes']
    assert hashlib.sha256(data).hexdigest() == meta['sha256'], name
for prefix in ('benchmark-1', 'benchmark-2'):
    folder = base / prefix
    report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    forks = [json.loads(gzip.decompress((folder / (n + '.gz')).read_bytes()))
             for n in report['raw_forks']]
    assert all(b.validate_fork(f) for f in forks)
    assert b.checksums_reproducible(forks)
    assert b.aggregate(forks) == report['summaries']
    assert b.aggregate_bridges(forks) == report['bridge_diagnostics']
print('PASS manifest and raw regeneration')
```

```powershell
python -B tools/solver_bench.py --scenarios 8,12,14,16 --forks 4 --repeats 2 --warmup 3 --warmup-ticks 6000 --ticks 9000 --output local/runs/solver-bench-stability-reproduction
```

## Решение

В проверенных source/контрактах гипотеза новой cache-регрессии **не
подтвердилась**; это не доказательство корректности всех входов и live мира.
Прежний legacy-only benchmark не доказывал ускорение gameplay API, тем более FPS.
Benchmark записывает честный HEAD execution checkout, который отличается от
public reviewed commit из-за локальной archival истории и audit edits.
Provenance устанавливается не одним HEAD: 82 production Java/shared-Lua файла
побайтово совпали с public snapshot после CRLF→LF; исходники harness/runner и
зависимости хэшированы отдельно. Локальная история в PR не переносилась.

Нельзя объявлять release PASS: отсутствует целевая B42.21 и live SP/MP acceptance.
Если тихий повтор на целевой версии не воспроизведёт полезный gameplay API gain
вне шума, рекомендуется **откатить оптимизацию**, а не менять механику ради цифр.
