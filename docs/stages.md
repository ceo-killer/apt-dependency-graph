# Проверка отдельных этапов

Перед переключением версии рабочая папка должна быть без несохранённых
изменений. После проверки можно вернуться командой `git switch main`.

## Этап 1

```sh
git switch --detach origin/stage-1
make test
make check
make run CONFIG=examples/demo.json
```

В выводе шесть настроек. Файл конфигурации разбирает `config.load_config`.
Нужно уметь объяснить проверку типов, относительные пути и код завершения
при ошибке. Набор неправильных значений проверяется в `test_config.py`.

## Этап 2

```sh
git switch --detach origin/stage-2
make test
make run CONFIG=examples/demo.json
```

Прямые зависимости A — B и C. `Repository` читает индекс самостоятельно;
вызовов apt в приложении нет. Версия корня ищется точно, а ограничения
версий зависимостей сравниваются по правилам Debian, включая эпоху и `~`.
Примеры настоящего индекса моделируются в `test_repository.py` без сети.

## Этап 3

```sh
git switch --detach origin/stage-3
make test
make run CONFIG=examples/demo.json
make run CONFIG=examples/cycle.json
make run CONFIG=examples/short-path.json
```

В примере demo обе ветви ведут к D. В cycle обход заканчивается и сохраняет
замкнутые связи. В short-path узел X сначала достигается длинным путём,
а затем коротким: это позволяет раскрыть Y. Состояние `best_depth`
решает эту задачу; один глобальный набор посещённых узлов недостаточен.
Обход использует стек. Глубина корня — 0.

## Этап 4

```sh
git switch --detach origin/stage-4
make test
make run CONFIG=examples/demo.json
make run CONFIG=examples/cycle.json
PYTHONPATH=src python3 tools/compare_apt.py --depth 3
```

В demo D предшествует B и C, а A идёт последним. Между независимыми B и C
допустимы разные порядки. В cycle ожидается ошибка с кодом 1: строгой
сортировки зависимостей нет. Порядок получается при завершении DFS;
временный активный путь позволяет отличить цикл от общей зависимости.
Результаты сравнения описаны в `docs/comparison.md`.

## Этап 5

```sh
git switch --detach origin/stage-5
make test
make check
make run CONFIG=examples/demo.json
make run CONFIG=examples/ubuntu-hello.json
make run CONFIG=examples/ubuntu-make.json
make run CONFIG=examples/ubuntu-gzip.json
```

Нужен D2 в PATH. Полученные SVG открываются в браузере, исходные D2 лежат
рядом с ними в `output/`. Все узлы и связи формируются из собственного
графа; D2 выполняет только отрисовку. Граничные узлы подписаны depth limit.
При неудачной отрисовке старое изображение не заменяется.
