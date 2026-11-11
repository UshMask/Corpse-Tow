# Контракты данных, сохранения и сетевых результатов

Краткая карта ответственности для участков, где ошибка приводит к потере или
дублированию исходного предмета. Полное поведение мода — в
[README мода](../CorpseProxyLab/README.md), проверки и команды — в
[docs/DEVELOPMENT.md](DEVELOPMENT.md).

## Проверенные версии

| Компонент | Версия / условие |
|---|---|
| Project Zomboid | Build 42.21 (`versionMin=42.21`) |
| ZombieBuddy | 2.0.0+, Java-агент на сервере и клиентах; JAR мода собран JDK 25 |
| Схема графа | `version=1` |
| Журнал оборудования | store `version=2` (старый) и `version=3`; файл `CVPEquipment.bin`, формат `CVPEQ1` |
| Сетевой протокол | 13 (`CVP_LinkWire.version`); сервер и клиенты обновляются одновременно |
| Lua | Kahlua B42.21; автономные тесты — Lupa/Lua 5.1 |

Смена схемы журнала или протокола требует отдельного обновления обеих сторон.
Совпадение номера протокола не доказывает совместимость разных альфа-сборок:
Lua и JAR должны быть из одного комплекта, Lua checksum включён.

## Кто владеет исходным предметом

Исходная верёвка/цепь существует в единственном экземпляре; «секции» общей
верёвки — это резервирования одного и того же предмета, а не его копии.

| Этап | Где предмет | Кто/что подтверждает |
|---|---|---|
| В инвентаре | Контейнер игрока | Обычная проверка `owned()` |
| Изъятие начато (`taking`) | Намерение записано; предмет ещё у владельца | Подтверждённая запись журнала, затем нативный `checkpoint` владельца |
| `held` / скрытый запас | Скрытый контейнер `CVPEquipment` | Запись журнала + подтверждение владельца; граф хранит `equipmentKey` |
| `returning` | Намерение возврата записано; предмет ещё в скрытом контейнере | Подтверждение получателя (`checkpointPlayer`/`checkpointSquare`) |
| `unresolved` | Исход операции неизвестен | Только сверка владельца и оригинала; повторная выдача запрещена |
| `released` | Предмет у получателя или на земле | Запись завершения; временный tombstone до очистки старого тела |

Правило: пока участок графа ссылается на `equipmentKey`, исходный предмет не
возвращается в инвентарь. Для общей верёвки возврат выполняется только после
удаления последнего участка (или полного отсоединения по `GroundRope`).

## Когда операция считается сохранённой

1. Намерение (`taking`/`returning`) записывается в журнал **до** переноса предмета.
2. `CVPEquipmentPersistence.write`/`writeEnvelope` подтверждает запись только после
   `force` и атомарной замены файла. Lua принимает только явный `true`
   (`status=confirmed`); `nil`, `false`, исключение и неизвестный результат —
   ошибка записи, а не успех.
3. `taking` завершается только после подтверждения сохранения владельца и точной
   сверки предмета; `returning` — после подтверждения получателя.
4. Сбой между записью намерения и переносом оставляет восстановимую запись.
   Сбой переноса возвращает исходный предмет или помечает `unresolved`; второй
   экземпляр не создаётся.
5. Перезапуск читает журнал заново и продолжает только однозначные операции.

Контракт чтения (`CVP_Equipment.readStore` → `CVPEquipmentPersistence.readEnvelope`):

| Исход | Поведение |
|---|---|
| `ok` + известная схема 2/3 | Загрузить и провалидировать |
| `missing` | Пустой store `version=2` (обычный первый запуск) |
| `unsupported` | Ошибка «unsupported equipment store version»; файл не трогать |
| `read-error` | Ошибка чтения; файл не считать пустым, `resetInvalidStore` не вызывать |
| повреждение известной схемы | Штатная процедура: backup + reset, только после доказанного повреждения |

Старый JAR без `readEnvelope` поддерживается через `read()`, но не различает
проглоченное исключение и отсутствие файла. Это известное ограничение
совместимости; поставляемый JAR содержит явный конверт.

## Согласование графа и учёта оборудования

- Единственный писатель — authority (`CVP_LinkService`/`CVP_Equipment`). Клиент
  присылает команды, но не позиции и не предметы.
- `CVP_LinkGraph` — чистые правила. Любая транзакция изменения топологии идёт через
  `G.edit(graph, mutate)`: он освобождает бывшие промежуточные `joint`-узлы,
  оставшиеся с одним ребром, превращая их в свободные концы `ground`, ровно один
  раз увеличивает `graph.revision` и валидирует итоговый индекс.
- Удаление связи в транзакции учёта выполняет `CVP_Equipment.finish` /
  `E.releaseLink` тем же `G.edit`, в той же записи журнала, что и возврат предмета.
  Поэтому после сбоя не возникает «граф без связи, но предмет ещё спрятан» или
  «предмет возвращён, а связь осталась».
- `E.editLinks` принимает граф только с ожидаемой ревизией (`CAS`) и проверяет,
  что оборудование каждого участка доступно; правки другого клиента отклоняются.
- Инварианты: нет циклов, у тела/узла не больше двух рёбер, в компоненте не больше
  одного тягача, сумма `allocation` общей верёвки ≤ 12, у `joint` после коммита
  ровно два ребра.

## Повторная сетевая команда и её результат

- `CVP_MPServer` ограничивает принятые операции бюджетом (8 токенов, пополнение
  0.02/мс); неверные команды и повторы не расходуют токен и не запускают
  authority-операцию.
- Завершённый запрос сохраняется по `request id` (последние 64). Повтор
  возвращает тот же сохранённый результат без повторного выполнения и без нового
  полного снимка; повтор не создаёт второй предмет и не сбрасывает
  `heartbeat`/`visiblePages` (потерянное состояние восстанавливает клиентский
  ограниченный `sync`).
- Ответы на повторы и отказы ограничены отдельным бюджетом `REPLY_MAX=8`
  (пополнение 8/с); при исчерпании ответ отбрасывается, клиент повторяет запрос
  после пополнения. Успешные подтверждения операций бюджет не расходуют: число
  операций уже ограничено токенами. Это не даёт спаму превращаться в
  неограниченный поток `result`-пакетов.
- Успешная операция, меняющая граф, публикует ровно одно состояние с
  `sequence = result.sequence`. Клиентский `drain()` отдаёт результат только после
  `C.sequence >= result.sequence`; при потере состояния клиент делает ограниченный
  `sync`, а плановая рассылка восстанавливает его без зависания.
- Отказ (неверная команда, превышение частоты, недоступная authority) использует
  последнюю фактически опубликованную для этого клиента `sequence` и не требует
  нового полного снимка. Частичные изменения, если они были, доезжают следующей
  плановой рассылкой (≤ 100 мс), а не отдельным снимком на каждый отказ.
- `sync`, запрос отсутствующего тела и подтверждения внешнего вида имеют
  ограниченную частоту/размер; поток одного клиента не останавливает обновление
  буксировки у остальных.

## Java-мост: проверяемые возможности

`CVPEquipmentPersistence.capabilities()` — единственная точка проверки
совместимости установленного JAR. Метод не бросает исключений и не выполняет
сохранение: он только разрешает объявленные классы/поля/конструкторы/методы,
которые используют нативные барьеры сохранения, и собирает **все** отсутствующие
элементы. `CVP_Equipment.prepare()` вызывает его один раз и кэширует результат в
`CVPEquipmentRuntime.bridge`.

```lua
-- совместимо
{ok=true, status='ok', ledgerFormat='CVPEQ1', worldVersion=251,
 features={bridge=true, ledger=true, playerCheckpointMp=true,
           playerCheckpointSp=true, squareCheckpointMp=true,
           squareCheckpointSp=true, skeletonLifetime=true, worldVersion=true}}

-- несовместимо
{ok=false, status='incompatible',
 reason='squareCheckpointMp: missing field zombie.network.ServerChunkLoader.threadSave (NoSuchFieldException ...)',
 missing={'squareCheckpointMp: ...', '...'}, -- все найденные пропуски
 ledgerFormat='CVPEQ1', worldVersion=251, features={...=false для сбойных групп}}
```

| Группа `features` | Что именно проверяется |
|---|---|
| `bridge` | `read()`, `write(KahluaTable)`, `readEnvelope()`, `writeEnvelope(KahluaTable)`, `resetInvalidStore()`, `playerKey`/`playerKeyAsync(IsoPlayer)`, `checkpointPlayer`/`checkpointPlayerAsync(IsoPlayer)`, `checkpointSquare`/`checkpointSquareAsync(IsoGridSquare)` |
| `ledger` | `EquipmentPersistence.MAGIC`, `readFile(Path)`, `writeFile(Path,KahluaTable,Replace)`; формат `CVPEQ1` |
| `playerCheckpointMp` | `zombie.network.ServerPlayersVehicles.instance` + `.thread`; `ServerPlayerDB.getInstance()`/`isAvailable()`/`charactersToSave`; `ServerPlayerDB$NetworkCharacterData(IsoPlayer,int,UdpConnection)` + поля `buffer`/`username`/`steamid` |
| `playerCheckpointSp` | `PlayerDB.getInstance()`/`isAvailable()`/`toThread`/`fromThread`; `PlayerDB$PlayerData()` + `set(IsoPlayer)` + `byteBuffer`; `WorldStreamer.instance`/`worldStreamer` |
| `squareCheckpointMp` | `ServerMap$ServerCell.chunkLoader.threadSave` (+ `toThread`/`fromThread`); `ServerChunkLoader$SaveLoadedTask(ServerChunkLoader,ClientChunkRequest,ClientChunkRequest$Chunk)`; `ClientChunkRequest()`/`getChunk()`/`getByteBuffer(Chunk)`; `ClientChunkRequest$Chunk.wx/wy/bb` |
| `squareCheckpointSp` | `ChunkSaveWorker$QueuedSave(IsoChunk,boolean)` + `allocBuffer()`/`crc`/`byteBuffer`/`chunk`; `ChunkSaveWorker.instance`/`toSaveQueue` |
| `skeletonLifetime` | `SkeletonLifetime.install(KahluaTable)`, `installClocks(Map)`, `readClocks(KahluaTable)` |
| `worldVersion` | `IsoWorld.getWorldVersion()` вызывается; значение только для диагностики (несовпадение версии самого журнала — отдельный исход чтения `unsupported`, файл не сбрасывается) |

Поведение при несовместимости:

- `prepare()` возвращает `nil,'equipment bridge incompatible: <reason>'` **до**
  чтения, записи или `resetInvalidStore`: существующий журнал не меняется.
- Причина печатается ровно один раз за runtime
  (`[CVP equipment] equipment bridge incompatible: ...`); повторные вызовы
  дешёвые и молчаливые, отказ остаётся fail-closed до перезапуска/перезагрузки
  JAR и Lua.
- Физика и отрисовка связей не вызывают этот шлюз и продолжают работать;
  останавливаются только операции учёта оборудования.
- Старый JAR без `capabilities()`: проверка пропускается, `bridge.legacy=true`,
  действует прежний контракт чтения (`readEnvelope`, иначе `read()`).
  Поставляемый JAR всегда содержит `capabilities()`.

Проверено на фактически установленном `projectzomboid.jar` + ZombieBuddy:
`capabilities()` → `status=ok`, все восемь групп `true`, `worldVersion=251`,
`missing={}`. Недоступный элемент возвращается как
`<группа>: missing field <класс>.<поле> (<исключение>)` — первая причина
конкретна, полный список — в `missing`.

## Где это проверено

| Контракт | Тесты |
|---|---|
| Свободный конец после удаления, порядок удаления, take/drop/bind, reload | `test_graph_deletion.py` |
| Граф, индексы, лимиты, два тягача, циклы | `test_link_graph.py` |
| Учёт оборудования, состояния, отказ записи и восстановление | `test_equipment.py`, `test_save_jobs.py` |
| MP: дубли, отказы, sequence, потеря состояния, два клиента | `test_mp_budget.py`, `test_link_multiplayer.py` |
| Java-мост: `readEnvelope`/`writeEnvelope`/`capabilities`, все группы возможностей | `ValidateEquipmentBridge.java` (native), `test_equipment.py`, `test_save_jobs.py` |
| Совместимость старых сохранений/фикстур | `test_upgrade_recovery.py`, `test_transfer_compatibility.py`, `test_save_queue.py` |

Автономные тесты не заменяют живую игру, настоящий MP-сервер и проверку
фактического JAR в ZombieBuddy. Для изменений Java/сохранений/сети перед выпуском
нужны отдельные SP/MP-проверки, перезапуск и сверка исходных предметов.
