"""Консольный режим — удобно для больших партий и запуска по расписанию.

    python -m unicalizer.cli -i C:\\video -o C:\\out -n 5 --preset hard
"""

from __future__ import annotations

import argparse
import copy
import sys
import threading
from pathlib import Path

from . import engine, probe
from .params import DEFAULT_PARAMS, PRESETS, load_preset_file, merge

_PRESET_ALIASES = {
    "light": "Лёгкая (максимум качества)",
    "medium": "Средняя (баланс)",
    "hard": "Жёсткая (максимум уникальности)",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unicalizer",
        description="Массовая уникализация видео (звук, оверлей, скорость, зум).",
    )
    parser.add_argument("-i", "--input", required=True, nargs="+",
                        help="файлы и/или папки с видео")
    parser.add_argument("-o", "--output", required=True, help="папка для результата")
    parser.add_argument("-n", "--copies", type=int, default=1,
                        help="сколько копий делать из каждого файла")
    parser.add_argument("--preset", default="medium",
                        choices=list(_PRESET_ALIASES),
                        help="встроенный пресет уникализации")
    parser.add_argument("--preset-file", help="свой пресет .json (имеет приоритет)")
    parser.add_argument("--overlay", help="картинка для наложения")
    parser.add_argument("--opacity", type=float,
                        help="прозрачность оверлея, например 0.05")
    parser.add_argument("--speed", type=float,
                        help="фиксированное ускорение, например 2.15")
    parser.add_argument("--jobs", type=int, default=2, help="параллельных задач")
    parser.add_argument("--seed", type=int, help="базовый сид для воспроизводимости")
    parser.add_argument("--recursive", action="store_true",
                        help="искать видео и во вложенных папках")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать план, ничего не кодировать")
    return parser


def collect_sources(entries: list[str], recursive: bool) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        path = Path(entry)
        candidates = probe.list_videos(path, recursive) if path.is_dir() else [str(path)]
        for candidate in candidates:
            key = candidate.lower()
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.preset_file:
        params = load_preset_file(args.preset_file)
    else:
        params = copy.deepcopy(PRESETS[_PRESET_ALIASES[args.preset]])

    patch: dict = {"output": {"copies_per_file": max(1, args.copies),
                              "parallel_jobs": max(1, args.jobs)}}
    if args.overlay:
        patch["overlay"] = {"enabled": True, "path": args.overlay}
        if args.opacity is not None:
            patch["overlay"]["opacity"] = [args.opacity, args.opacity]
    if args.speed:
        patch["speed"] = {"enabled": True, "factor": [args.speed, args.speed]}
    params = merge(params, patch)

    sources = collect_sources(args.input, args.recursive)
    if not sources:
        print("Не нашлось ни одного видеофайла.", file=sys.stderr)
        return 2

    clashing = engine.sources_inside(sources, args.output)
    if clashing:
        print(f"[!] {len(clashing)} из {len(sources)} роликов лежат в папке вывода. "
              f"На следующем запуске они попадут в обработку повторно — "
              f"лучше указать отдельную папку через -o.", file=sys.stderr)

    jobs, problems = engine.plan_jobs(sources, args.output, params, base_seed=args.seed)
    for problem in problems:
        print(f"[пропущен] {problem}", file=sys.stderr)
    if not jobs:
        print("Нечего обрабатывать.", file=sys.stderr)
        return 2

    print(f"Файлов: {len(sources)}, задач: {len(jobs)}")
    if args.dry_run:
        for job in jobs:
            print(f"  {job.title}  (сид {job.seed})")
        return 0

    done = threading.Event()
    last_line = {"text": ""}

    def on_job(job: engine.Job) -> None:
        total = sum(j.progress for j in jobs) / len(jobs)
        line = (f"\r[{total * 100:5.1f}%] "
                f"готово {sum(1 for j in jobs if j.status == 'готово')}/{len(jobs)}"
                f"  {job.status}: {Path(job.out_path).name[:48]:<48}")
        if line != last_line["text"]:
            sys.stdout.write(line)
            sys.stdout.flush()
            last_line["text"] = line

    def on_finish(_: list[engine.Job]) -> None:
        done.set()

    runner = engine.Runner(on_job=on_job, on_log=lambda t: print(f"\n{t}"),
                           on_finish=on_finish)
    runner.start(jobs, params)
    try:
        while not done.wait(0.3):
            pass
    except KeyboardInterrupt:
        print("\nОтмена…")
        runner.cancel()
        done.wait(20)

    failed = [j for j in jobs if j.status == "ошибка"]
    print(f"\nГотово: {sum(1 for j in jobs if j.status == 'готово')} из {len(jobs)}")
    for job in failed:
        print(f"  [ошибка] {job.title}: {job.error.splitlines()[-1] if job.error else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
