"""Очередь задач: запуск ffmpeg, разбор прогресса, отмена, отчёты."""

from __future__ import annotations

import copy
import json
import random
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import ffmpeg_builder
from . import probe as probe_mod
from .probe import MediaInfo, probe

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Job:
    source: str
    out_path: str
    copy_index: int
    seed: int
    info: MediaInfo | None = None
    status: str = "ожидает"       # ожидает | работает | готово | ошибка | отменено
    progress: float = 0.0
    error: str = ""
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return f"{Path(self.source).name} → {Path(self.out_path).name}"


def safe_name(text: str) -> str:
    cleaned = _INVALID.sub("_", text).strip(" .")
    return cleaned or "video"


def sources_inside(sources: list[str], out_dir: str) -> list[str]:
    """Исходники, которые лежат в папке вывода.

    Если складывать результат туда же, откуда берём, то на следующем запуске
    программа подхватит собственные копии и начнёт уникализировать их — партия
    растёт лавиной, а качество падает с каждым кругом.
    """
    try:
        out = Path(out_dir).resolve()
    except OSError:
        return []
    inside = []
    for item in sources:
        try:
            parent = Path(item).resolve().parent
        except OSError:
            continue
        if parent == out or out in parent.parents:
            inside.append(item)
    return inside


def plan_jobs(
    sources: list[str],
    out_dir: str,
    params: dict,
    base_seed: int | None = None,
) -> tuple[list[Job], list[str]]:
    """Строит список задач. Возвращает (задачи, сообщения о пропущенных файлах)."""
    output = params.get("output", {})
    copies = max(1, int(output.get("copies_per_file", 1)))
    pattern = output.get("pattern") or "{name}_uniq{i}"
    container = (output.get("container") or "mp4").lstrip(".")

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    rnd = random.Random(base_seed) if base_seed is not None else random.Random()
    jobs: list[Job] = []
    problems: list[str] = []
    taken: set[str] = set()

    for source in sources:
        try:
            info = probe(source)
        except Exception as exc:
            problems.append(f"{Path(source).name}: {exc}")
            continue
        if info.duration <= 0:
            problems.append(f"{Path(source).name}: не удалось определить длительность")
            continue

        stem = Path(source).stem
        for index in range(1, copies + 1):
            seed = rnd.randrange(1, 2**31 - 1)
            # Шаблон правит человек, и в нём легко ошибиться: {nam}, {0},
            # незакрытая скобка. Это не повод ронять всю партию — молча
            # откатываемся на стандартное имя.
            try:
                rendered = pattern.format(name=stem, i=index, seed=seed)
            except (KeyError, IndexError, ValueError):
                rendered = f"{stem}_uniq{index}"
            name = safe_name(rendered)
            candidate = out_root / f"{name}.{container}"
            # Не перетираем ни чужие файлы, ни свои же из этой же партии.
            counter = 2
            while candidate.exists() or str(candidate).lower() in taken:
                candidate = out_root / f"{name}_{counter}.{container}"
                counter += 1
            taken.add(str(candidate).lower())

            jobs.append(Job(
                source=source,
                out_path=str(candidate),
                copy_index=index,
                seed=seed,
                info=info,
            ))
    return jobs, problems


class Runner:
    """Выполняет список задач в несколько потоков и сообщает о прогрессе."""

    def __init__(
        self,
        on_job: Callable[[Job], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        on_finish: Callable[[list[Job]], None] | None = None,
    ) -> None:
        self.on_job = on_job or (lambda job: None)
        self.on_log = on_log or (lambda text: None)
        self.on_finish = on_finish or (lambda jobs: None)
        self._cancel = threading.Event()
        self._procs: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ запуск

    def start(self, jobs: list[Job], params: dict) -> bool:
        """Запускает партию. Возвращает False, если предыдущая ещё идёт.

        Без этой проверки повторный вызов просто затирал ссылку на поток:
        старая партия продолжала работать незамеченной, а две задачи могли
        писать в один и тот же файл и портить его.
        """
        if self.running:
            return False
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run_all, args=(jobs, params), daemon=True
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Просит остановиться. Возвращается сразу.

        Каждый ffmpeg гасится через terminate с ожиданием до трёх секунд, и на
        десятке параллельных задач это застопорило бы окно на полминуты. Поэтому
        само убийство уходит в отдельный поток: галочка «отменено» ставится
        мгновенно, а окно продолжает откликаться.
        """
        self._cancel.set()
        with self._lock:
            procs = list(self._procs.values())
        if not procs:
            return
        threading.Thread(
            target=lambda: [self._kill(p) for p in procs], daemon=True
        ).start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run_all(self, jobs: list[Job], params: dict) -> None:
        workers = max(1, min(4, int(params.get("output", {}).get("parallel_jobs", 2))))

        # Прогреваем опросы ffmpeg до старта потоков. Кэш у них есть, но он не
        # держит замок: четыре работника входят одновременно, промахиваются все
        # и запускают ffmpeg вчетверо чаще, чем нужно.
        try:
            probe_mod.nvenc_available()
            probe_mod.filter_available("rubberband")
        except Exception:                             # noqa: BLE001
            pass

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(lambda job: self._guarded(job, params), jobs))
        finally:
            self._safe(self.on_finish, jobs)

    def _guarded(self, job: Job, params: dict) -> None:
        """Одна задача не должна утаскивать за собой всю партию.

        pool.map прерывает обход на первом же исключении, а обработчики
        интерфейса вызываются из рабочих потоков и тоже могут бросить —
        например если окно уже закрывают. Ловим всё здесь.
        """
        try:
            self._run_one(job, params)
        except Exception as exc:                      # noqa: BLE001
            job.status = "ошибка"
            job.error = str(exc)
            self._safe(self.on_log, f"[ОШИБКА] {job.title}: {exc}")
            self._safe(self.on_job, job)

    @staticmethod
    def _safe(callback, *args) -> None:
        """Вызов обработчика, который не имеет права уронить обработку."""
        try:
            callback(*args)
        except Exception:                             # noqa: BLE001
            pass

    # ------------------------------------------------------------ одна задача

    def _run_one(self, job: Job, params: dict) -> None:
        if self._cancel.is_set():
            job.status = "отменено"
            self.on_job(job)
            return

        job.status = "работает"
        job.progress = 0.0
        self.on_job(job)

        try:
            info = job.info or probe(job.source)
            built = ffmpeg_builder.build(info, job.out_path, params, job.seed)
            job.report = built.report
            total = built.out_duration or 1.0
            self._execute(job, built.args, total)

            # Проба NVENC при запуске says «работает», но на конкретном ролике
            # он всё равно может отказать: слишком мелкий кадр, занятые сессии
            # кодировщика, свежий драйвер. Тогда молча переснимаем на процессоре,
            # вместо того чтобы отдать человеку пустое место в партии.
            if job.status == "ошибка" and self._looks_like_nvenc_failure(job.error)                     and params.get("encode", {}).get("encoder", "auto") != "cpu"                     and not self._cancel.is_set():
                self.on_log(f"[!] Видеокарта не справилась, повторяю на процессоре: "
                            f"{Path(job.source).name}")
                cpu_params = copy.deepcopy(params)
                cpu_params.setdefault("encode", {})["encoder"] = "cpu"
                job.status = "работает"
                job.progress = 0.0
                job.error = ""
                self.on_job(job)
                built = ffmpeg_builder.build(info, job.out_path, cpu_params, job.seed)
                job.report = built.report
                self._execute(job, built.args, built.out_duration or 1.0)
        except Exception as exc:
            job.status = "ошибка"
            job.error = str(exc)
            self.on_log(f"[ОШИБКА] {job.title}: {exc}")
            self.on_job(job)
            return

        if job.status == "готово" and params.get("output", {}).get("write_report", True):
            try:
                Path(job.out_path).with_suffix(".json").write_text(
                    json.dumps(job.report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                self.on_log(f"[!] Не удалось записать отчёт: {exc}")

    def _execute(self, job: Job, args: list[str], total: float) -> None:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_NO_WINDOW,
        )
        with self._lock:
            self._procs[id(job)] = proc

        errors: list[str] = []
        reader = threading.Thread(
            target=lambda: errors.extend(proc.stderr.read().splitlines()), daemon=True
        )
        reader.start()

        try:
            for line in proc.stdout:
                if self._cancel.is_set():
                    self._kill(proc)
                    break
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit():
                    seconds = int(value) / 1_000_000
                    job.progress = max(0.0, min(1.0, seconds / total))
                    self.on_job(job)
                elif key == "progress" and value == "end":
                    job.progress = 1.0
        finally:
            proc.wait()
            reader.join(timeout=2)
            with self._lock:
                self._procs.pop(id(job), None)

        if self._cancel.is_set():
            job.status = "отменено"
            Path(job.out_path).unlink(missing_ok=True)
        elif proc.returncode == 0:
            job.status = "готово"
            job.progress = 1.0
        else:
            job.status = "ошибка"
            # Настоящая причина обычно в ПЕРВОЙ строке (какой фильтр не собрался),
            # а дальше идёт каскад «поток не открылся». Показываем оба конца.
            head = errors[:4]
            tail = [line for line in errors[4:][-6:] if line not in head]
            job.error = "\n".join(head + tail) or \
                f"ffmpeg завершился с кодом {proc.returncode}"
            Path(job.out_path).unlink(missing_ok=True)
            self.on_log(f"[ОШИБКА] {job.title}\n{job.error}")
        self.on_job(job)

    @staticmethod
    def _looks_like_nvenc_failure(error: str) -> bool:
        """Похоже ли, что упал именно аппаратный кодировщик, а не сам ролик."""
        if not error:
            return False
        low = error.lower()
        markers = ("nvenc", "openencodesessionex", "cuda", "no capable devices",
                   "frame dimension", "driver does not support")
        return any(m in low for m in markers)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
