"""Bilingual, dependency-free terminal wizard over the existing command-line APIs."""

import json
import os
import shutil
import sys
import unicodedata
from datetime import datetime
from math import isfinite
from pathlib import Path

TEXT = {
    "zh": {
        "title": "F1 策略实验室 · 终端操作界面",
        "scope": "结果是给定模型下的策略；不等同真实比赛预测。",
        "menu": "1  离线演示（合成数据）\n2  历史赛事策略分析\n3  车队 / 车手分析\n"
        "4  年份留出验证\n5  查看已有结果\n6  设置输出与缓存目录\n"
        "7  Switch to English\n0  退出",
        "choose": "请选择",
        "invalid": "输入无效，请重新输入。",
        "hint": "回车=默认值；b=返回上一步修改；q=返回主菜单（取消本次填写）。",
        "track": "赛道英文名称",
        "start": "训练数据起始年份",
        "end": "数据结束年份",
        "year": "目标赛事年份",
        "holdout": "验证年份（只用更早年份训练）",
        "laps": "比赛总圈数",
        "pit": "进站损失（秒）",
        "temp": "赛道温度（°C）",
        "age": "最大胎龄（圈）",
        "compare": "生成参数敏感性对比",
        "yesno": "1=是 / 2=否",
        "source": "数据来源：1=已有缓存（不联网） / 2=联网获取",
        "team": "车队英文名称",
        "driver": "车手缩写、姓名或车号",
        "mode": "模式：1=历史复盘 / 2=赛前预测（排除目标赛事数据）",
        "history": "选择用于分析的年份范围",
        "history_custom": "自定义：输入起始年份",
        "history_option": "{start}–{end} 年（共 {count} 年）",
        "history_selected": "将使用 {start}–{end} 年数据；目标赛事年份为 {target}。",
        "prediction_year": "预测需要至少一个更早年份，请选择 2019 年或之后的目标赛事。",
        "first_step": "已经是第一步；输入 q 可返回主菜单。",
        "back": "已返回上一步，之前填写的内容已保留。",
        "default": "回车默认：{value}",
        "integer": "填写一个整数",
        "decimal": "填写一个数字，可带小数",
        "number_help": "{kind}；范围 {bounds}；例如 {example}。",
        "choice_help": "只填选项编号：{choices}（不要填写年份或选项文字）。",
        "number_error": "“{value}”不符合要求：{help}",
        "text_error": "内容不能为空，请按上方示例填写，或按回车使用默认值。",
        "fallback": "样本不足时：1=报错 / 2=允许同队数据 / 3=允许全场数据",
        "out": "结果保存目录",
        "cache": "数据缓存目录",
        "saved": "设置已更新。",
        "running": "正在分析，请稍候。下方为引擎日志（可能包含英文）。",
        "done": "分析完成",
        "failed": "运行失败；可修改参数后重试。",
        "cancelled": "已取消；如生成了部分结果，将保留以便检查。",
        "bye": "已退出。",
        "empty": "暂无可查看的结果。",
        "pickrun": "输入结果编号查看摘要",
        "summary": "结果摘要",
        "time": "模型总耗时（秒）",
        "pits": "进站圈（该圈结束后）",
        "stint": "赛段",
        "lapunit": "圈",
        "none": "无",
        "files": "结果文件",
        "training": "训练年份",
        "test": "验证年份",
        "missing": "该配方无历史验证模型",
        "readerror": "无法读取结果",
        "range": "结束年份必须不小于起始年份。",
        "holdrange": "验证年份必须晚于起始年份，且不超过结束年份。",
        "predict": "预测模式需要目标赛事 FP1 名单，且必须指定预计比赛圈数。",
        "review": "历史复盘允许拟合目标年数据；不能当作赛前预测。",
        "preview": "即将运行",
        "go": "1=开始运行 / 2=返回主菜单",
        "config": "当前目录",
        "unavailable": "本次没有可用的验证指标。",
        "SOFT": "软胎",
        "MEDIUM": "中胎",
        "HARD": "硬胎",
        "controls": "回车 默认  ·  b 上一步  ·  q 主菜单  ·  ? 帮助",
        "menu_controls": "输入编号  ·  0 退出  ·  ? 帮助",
        "step": "第 {step} 步",
        "enter": "输入",
        "pause": "按回车返回主菜单…",
        "selected": "已选",
        "default_short": "默认：{value}",
        "help_empty": "按提示输入；回车使用默认值。",
        "mode_title": "分析模式",
        "fallback_title": "数据不足时怎么办？",
        "source_title": "数据来源",
        "go_title": "开始分析？",
        "main_title": "F1 策略实验室",
    },
    "en": {
        "title": "F1 Strategy Lab · Terminal interface",
        "scope": "Strategies are optimal within the model, not predictions of real race outcomes.",
        "menu": "1  Offline demo (synthetic data)\n2  Historical race strategy\n"
        "3  Team / driver analysis\n4  Year-held-out validation\n5  Browse results\n"
        "6  Output and cache settings\n7  切换到中文\n0  Exit",
        "choose": "Select",
        "invalid": "Invalid input. Please try again.",
        "hint": "Enter=default; b=previous step; q=main menu (discard this form).",
        "track": "Track name in English",
        "start": "First data year",
        "end": "Last data year",
        "year": "Target race year",
        "holdout": "Holdout year (train on earlier years only)",
        "laps": "Race distance (laps)",
        "pit": "Pit loss (seconds)",
        "temp": "Track temperature (C)",
        "age": "Maximum tyre age (laps)",
        "compare": "Generate sensitivity comparison",
        "yesno": "1=yes / 2=no",
        "source": "Data source: 1=existing cache (offline) / 2=online fetch",
        "team": "Team name in English",
        "driver": "Driver abbreviation, name or car number",
        "mode": "Mode: 1=historical review / 2=prediction (exclude target race)",
        "history": "Choose the data year range",
        "history_custom": "Custom: enter the first year",
        "history_option": "{start}–{end} ({count} years)",
        "history_selected": "Use data from {start}–{end}; target event year: {target}.",
        "prediction_year": "Prediction needs prior data. Choose a target year of 2019 or later.",
        "first_step": "This is the first step. Enter q to return to the main menu.",
        "back": "Returned to the previous step. Earlier answers have been preserved.",
        "default": "Enter for default: {value}",
        "integer": "Enter one integer",
        "decimal": "Enter one number; decimals are allowed",
        "number_help": "{kind}; range {bounds}; example: {example}.",
        "choice_help": "Enter an option number only: {choices} (not a year or option text).",
        "number_error": "'{value}' is not valid: {help}",
        "text_error": "Cannot be empty. Follow the example or press Enter for a default.",
        "fallback": "Insufficient samples: 1=fail / 2=allow team data / 3=allow field data",
        "out": "Output directory",
        "cache": "Data cache directory",
        "saved": "Settings updated.",
        "running": "Running analysis. Engine logs follow; please wait.",
        "done": "Analysis completed",
        "failed": "Run failed. Adjust the inputs and try again.",
        "cancelled": "Cancelled. Any partial output is preserved for inspection.",
        "bye": "Goodbye.",
        "empty": "No results available yet.",
        "pickrun": "Choose a result number to view its summary",
        "summary": "Result summary",
        "time": "Model time (seconds)",
        "pits": "Pit after laps",
        "stint": "Stint",
        "lapunit": "laps",
        "none": "none",
        "files": "Result files",
        "training": "Training years",
        "test": "Held-out year",
        "missing": "No historical validation model for this compound",
        "readerror": "Cannot read result",
        "range": "Last year must not precede first year.",
        "holdrange": "Holdout year must be after first year and no later than last year.",
        "predict": "Prediction needs the target event FP1 roster and a planned lap count.",
        "review": "Historical review may fit target-year data; it is not a pre-race prediction.",
        "preview": "Ready to run",
        "go": "1=run / 2=return to menu",
        "config": "Current directories",
        "unavailable": "No validation metrics are available.",
        "SOFT": "SOFT",
        "MEDIUM": "MEDIUM",
        "HARD": "HARD",
        "controls": "Enter default  ·  b back  ·  q menu  ·  ? help",
        "menu_controls": "Enter a number  ·  0 exit  ·  ? help",
        "step": "Step {step}",
        "enter": "Input",
        "pause": "Press Enter to return to the menu…",
        "selected": "Selected",
        "default_short": "Default: {value}",
        "help_empty": "Enter the requested value, or press Enter for the default.",
        "mode_title": "Analysis mode",
        "fallback_title": "If driver data is insufficient",
        "source_title": "Data source",
        "go_title": "Start analysis?",
        "main_title": "F1 Strategy Lab",
    },
}


class BackToMenu(Exception):
    pass


class PreviousStep(Exception):
    pass


HELP = {
    "zh": {
        "track": "例如 Bahrain（巴林）、Monza（蒙扎）。请输入赛事英文名称，不是编号。",
        "team": "例如 Ferrari。车队必须与所选年份的车手名单一致。",
        "driver": "例如 LEC、Charles Leclerc 或 16；三种写法选一种即可。",
        "year": "填写一个四位年份，例如 2025；不是年份范围。",
        "start": "填写最早使用的年份，例如 2022；结束年份在下一步填写。",
        "end": "填写最后使用的年份，例如 2025；不要一次填写两个年份。",
        "holdout": "选哪一年检验模型？例如 2025；训练只使用此前的年份。",
        "history_custom": "只填最早年份，例如 2022；结束年份已由模式确定，无需再填。",
        "laps": "例如 57 表示比赛跑 57 圈。其他赛道请按对应赛事填写。",
        "pit": "例如 24 表示一次进站损失 24 秒。不确定可回车，使用演示假设。",
        "temp": "例如 35 或 35.5，单位 °C。不确定可回车，使用参考温度。",
        "age": "同一套胎最多跑多少圈，例如 50。不确定可回车；这不是官方安全上限。",
        "mode": "复盘：可使用目标赛事数据。预测：只用更早年份数据，要求目标赛事 FP1 名单可用。",
        "fallback": "默认只用该车手数据；选 2 或 3 会扩大数据来源，报告会注明。",
        "source": "没有下载过该赛事时请选择 2；选 1 不联网，缓存不足会报错。",
        "out": "例如 output 或 results；可以包含空格，不需要加引号。",
        "cache": "例如 cache 或 data-cache；可以包含空格，不需要加引号。",
    },
    "en": {
        "track": "Examples: Bahrain or Monza. Enter an English event name, not a number.",
        "team": "Example: Ferrari. The team must match the driver roster for the selected season.",
        "driver": "Examples: LEC, Charles Leclerc or 16. Use any one of these formats.",
        "year": "Enter one four-digit year, e.g. 2025, not a year range.",
        "start": "Enter the earliest data year, e.g. 2022. The ending year is asked next.",
        "end": "Enter the last data year, e.g. 2025. Do not enter two years together.",
        "holdout": "Which year should test the model? E.g. 2025; training uses earlier years only.",
        "history_custom": "Enter the first year only, e.g. 2022. The ending year is already fixed.",
        "laps": "Example: 57 means 57 race laps. Set the distance for your chosen event.",
        "pit": "Example: 24 means 24 seconds per stop. Enter accepts the demonstration prior.",
        "temp": "Example: 35 or 35.5 degrees C. Enter accepts the reference temperature.",
        "age": "Maximum laps on one tyre set, e.g. 50. This is not an official safety limit.",
        "mode": "Review may use target-race data. Prediction needs prior data and FP1 entries.",
        "fallback": "Default: this driver only. Options 2/3 widen the pool; sources are disclosed.",
        "source": "Choose 2 if this event is not cached. Option 1 never downloads missing data.",
        "out": "Example: output or results. Spaces are allowed; quotes are unnecessary.",
        "cache": "Example: cache or data-cache. Spaces are allowed; quotes are unnecessary.",
    },
}

OPTIONS = {
    "zh": {
        "mode": ["1  历史复盘", "2  赛前预测"],
        "fallback": ["1  停止并提示", "2  使用同队数据", "3  允许使用全场数据"],
        "source": ["1  本地缓存（不联网）", "2  联网获取"],
        "yesno": ["1  是", "2  否"],
        "go": ["1  开始", "2  返回主菜单"],
    },
    "en": {
        "mode": ["1  Historical review", "2  Pre-race prediction"],
        "fallback": ["1  Stop and report", "2  Use team data", "3  Allow field data"],
        "source": ["1  Local cache (offline)", "2  Fetch online"],
        "yesno": ["1  Yes", "2  No"],
        "go": ["1  Start", "2  Return to menu"],
    },
}


def wrap_terminal(text, width):
    """Wrap by terminal cells rather than code points, including Chinese full-width text."""
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line, used = "", 0
        for char in paragraph:
            size = (
                0
                if unicodedata.combining(char)
                else (2 if unicodedata.east_asian_width(char) in ("W", "F") else 1)
            )
            if used + size > width and line:
                lines.append(line)
                line, used = "", 0
            line += char
            used += size
        lines.append(line)
    return lines


class Terminal:
    def __init__(self, language="zh", reader=None, writer=None, *, interactive=None, clearer=None):
        self.language = language
        self.read = reader or input
        self.write = writer or print
        self.output_root = Path("output")
        self.cache_root = Path("cache")
        self._answers = None
        self._cursor = 0
        self.interactive = (
            (reader is None and writer is None and sys.stdin.isatty() and sys.stdout.isatty())
            if interactive is None
            else interactive
        )
        self.clearer = clearer or self.clear_screen
        self._labels = []

    def clear_screen(self):
        if os.name == "nt":
            os.system("cls")  # Fixed command; never interpolates user input.
        else:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    def page(self, title, *, content=(), default=None, error="", help_text="", menu=False):
        if self.interactive:
            self.clearer()
        width = max(24, min(72, shutil.get_terminal_size((80, 24)).columns - 4))

        def line(text=""):
            for part in wrap_terminal(text, width):
                self.write(f"  {part}")

        self.write("")
        line(self.t("main_title"))
        line("─" * width)
        if self._answers is not None:
            context = [
                str(value)
                for key, value in self._labels
                if key in ("track", "team", "driver", "year")
            ][-4:]
            if context:
                line(f"{self.t('selected')}: " + " · ".join(context))
            line(self.t("step").format(step=self._cursor + 1))
        line()
        line(title)
        line()
        for item in content:
            line(item)
        if content:
            line()
        if default is not None:
            line(self.t("default_short").format(value=default))
        if help_text:
            line()
            line(help_text)
        if error:
            line()
            line(error)
        line()
        line("─" * width)
        line(self.t("menu_controls" if menu else "controls"))
        line()

    def pause(self):
        if self.interactive:
            self.read(f"\n  {self.t('pause')}")

    def t(self, key):
        return TEXT[self.language][key]

    def ask(
        self,
        key,
        default=None,
        *,
        choices=None,
        number=None,
        minimum=None,
        maximum=None,
        title=None,
        content=None,
        menu=False,
    ):
        if self._answers is not None and self._cursor < len(self._answers):
            answer = self._answers[self._cursor]
            self._cursor += 1
            return answer
        title = title or (
            self.t(f"{key}_title")
            if key in ("mode", "fallback", "source", "go")
            else self.t("compare" if key == "yesno" else key)
        )
        content = OPTIONS[self.language].get(key, []) if content is None else content
        guidance = ""
        if choices is not None:
            guidance = self.t("choice_help").format(choices=" / ".join(choices))
        elif number is not None:
            bounds = f"{minimum}–{maximum}" if maximum is not None else f">= {minimum}"
            guidance = self.t("number_help").format(
                kind=self.t("integer" if number is int else "decimal"),
                bounds=bounds,
                example=default if default is not None else minimum,
            )
        error, show_help = "", False
        while True:
            self.page(
                title,
                content=content,
                default=default,
                error=error,
                help_text=(
                    HELP[self.language].get(key, guidance or self.t("help_empty"))
                    if show_help
                    else ""
                ),
                menu=menu,
            )
            value = self.read(f"  {self.t('enter')} > ").strip()
            if value == "?":
                show_help = not show_help
                continue
            if value.lower() == "q":
                raise BackToMenu
            if value.lower() == "b":
                if self._answers is not None:
                    raise PreviousStep
                raise BackToMenu
            value = str(default) if not value and default is not None else value
            raw = value
            try:
                if not value:
                    raise ValueError
                if choices is not None and value not in choices:
                    raise ValueError
                if number is not None:
                    value = number(value)
                    if not isfinite(value):
                        raise ValueError
                    if minimum is not None and value < minimum:
                        raise ValueError
                    if maximum is not None and value > maximum:
                        raise ValueError
                if self._answers is not None:
                    self._answers.append(value)
                    self._labels.append((key, value))
                    self._cursor += 1
                return value
            except (ValueError, OverflowError):
                error = (
                    self.t("number_error").format(value=raw, help=guidance)
                    if guidance
                    else self.t("text_error")
                )

    def number(self, key, default, minimum=1, maximum=None, kind=int):
        return self.ask(key, default, number=kind, minimum=minimum, maximum=maximum)

    def new_output(self, prefix):
        return self.output_root / f"{prefix}-{datetime.now():%Y%m%d-%H%M%S-%f}"

    def wizard(self, callback):
        """Replay validated earlier answers when backing up, without repeating their prompts."""
        original_write = self.write
        self._answers = []
        self._labels = []

        def visible(message):
            if self._cursor >= len(self._answers):
                original_write(message)

        self.write = visible
        try:
            while True:
                self._cursor = 0
                try:
                    return callback()
                except PreviousStep:
                    if self._answers:
                        self._answers.pop()
                        self._labels.pop()
                        original_write(self.t("back"))
                    else:
                        original_write(self.t("first_step"))
        finally:
            self.write = original_write
            self._answers = None
            self._cursor = 0
            self._labels = []

    def history(self, target, prediction):
        last = target - 1 if prediction else target
        first_allowed = max(2018, target - 19)
        ranges = {"1": max(first_allowed, last - 1), "2": max(first_allowed, last - 2)}
        options = []
        for option, first in ranges.items():
            options.append(
                f"  {option}. "
                + self.t("history_option").format(start=first, end=last, count=last - first + 1)
            )
        options.append(f"  3. {self.t('history_custom')}")
        choice = self.ask(
            "history", "1" if prediction else "2", choices=("1", "2", "3"), content=options
        )
        first = (
            self.number("history_custom", max(first_allowed, last - 2), first_allowed, last)
            if choice == "3"
            else ranges[choice]
        )
        # Included on the final confirmation page rather than appended between questions.
        return target - first + 1

    def plan(self, choice):
        """Build plain argv lists, never shell commands; no I/O until execution."""
        args = []
        if choice == "3":
            module = "driver"
            for flag, key, default in (
                ("--track", "track", "Bahrain"),
                ("--team", "team", "Ferrari"),
                ("--driver", "driver", "LEC"),
            ):
                args += [flag, self.ask(key, default)]
            target = self.number("year", 2025, 2018, 2100)
            mode = self.ask("mode", "1", choices=("1", "2"))
            if mode == "2" and target < 2019:
                self.write(self.t("prediction_year"))
                target = self.number("year", 2019, 2019, 2100)
            args += ["--year", str(target)]
            args += ["--mode", "review" if mode == "1" else "predict"]
            args += ["--history-years", str(self.history(target, mode == "2"))]
            fallback = self.ask("fallback", "1", choices=("1", "2", "3"))
            args += ["--fallback", {"1": "none", "2": "team", "3": "field"}[fallback]]
            if mode == "2":
                args += ["--laps", str(self.number("laps", 57, 2, 500))]
            args += ["--pit-loss", str(self.number("pit", 24, 0, kind=float))]
            args += ["--max-tyre-age", str(self.number("age", 50, 1, 500))]
        else:
            module = "core"
            args = [{"1": "demo", "2": "optimize", "4": "backtest"}[choice]]
            if choice != "1":
                args += ["--track", self.ask("track", "Bahrain")]
                start = self.number("start", 2022, 2018, 2099 if choice == "4" else 2100)
                end_minimum = start + 1 if choice == "4" else start
                end = self.number("end", max(2025, end_minimum), end_minimum, 2100)
                args += ["--start", str(start), "--end", str(end)]
                if choice == "4":
                    holdout = self.number("holdout", end, start + 1, end)
                    args += ["--holdout-year", str(holdout)]
            if choice != "4":
                args += ["--laps", str(self.number("laps", 57, 2, 500))]
                args += ["--pit-loss", str(self.number("pit", 24, 0, kind=float))]
                args += ["--temp", str(self.number("temp", 35, -50, 100, float))]
                args += ["--max-tyre-age", str(self.number("age", 50, 1, 500))]
                if self.ask("yesno", "1", choices=("1", "2")) == "1":
                    args += ["--compare"]
            if choice == "1":
                args += ["--holdout-year", "2025"]
        if choice != "1":
            if self.ask("source", "1", choices=("1", "2")) == "1":
                args += ["--offline"]
            args += ["--cache-dir", str(self.cache_root)]
        output = self.new_output({"1": "demo", "2": "race", "3": "driver", "4": "backtest"}[choice])
        args += ["--output-dir", str(output)]
        confirmation = list(OPTIONS[self.language]["go"])
        if module == "driver":
            history_count = int(args[args.index("--history-years") + 1])
            confirmation += [
                "",
                self.t("history_selected").format(
                    start=target - history_count + 1,
                    end=target - 1 if mode == "2" else target,
                    target=target,
                ),
            ]
        confirmation += ["", f"{self.t('out')}: {output.resolve()}"]
        if self.ask("go", "1", choices=("1", "2"), content=confirmation) != "1":
            raise BackToMenu
        return module, args, output

    def execute(self, module, args, output):
        self.write(f"\n{self.t('running')}\n")
        try:
            if module == "driver":
                from .driver_analysis import main as run
            else:
                from .cli import main as run
            code = run(args)
        except SystemExit as exc:
            code = exc.code
        except (ValueError, RuntimeError, OSError) as exc:
            self.write(str(exc))
            code = 1
        if code == 0:
            self.write(f"\n{self.t('done')}\n{output.resolve()}")
            self.summary(output)
        else:
            self.write(self.t("failed"))

    def summary(self, output):
        try:
            self.write(f"\n--- {self.t('summary')} ---")
            strategy, validation = None, None
            driver = output / "driver-analysis.json"
            if driver.is_file():
                report = json.loads(driver.read_text(encoding="utf-8"))
                identity = report["identity"]
                self.write(f"{identity['FullName']} | {identity['TeamName']}")
                strategy, validation = report["strategy"], report.get("validation")
            else:
                for filename, kind in (
                    ("strategy.json", "strategy"),
                    ("backtest.json", "validation"),
                ):
                    if (output / filename).is_file():
                        data = json.loads((output / filename).read_text(encoding="utf-8"))
                        if kind == "strategy":
                            strategy = data
                        else:
                            validation = data
            if strategy:
                self.write(f"{self.t('time')}: {strategy['total_time']:.3f}")
                for i, (compound, length) in enumerate(
                    zip(strategy["compounds_used"], strategy["stint_lengths"]), 1
                ):
                    self.write(
                        f"  {self.t('stint')} {i}: "
                        f"{self.t(compound)} × {length} {self.t('lapunit')}"
                    )
                self.write(f"{self.t('pits')}: {strategy['pit_laps'] or self.t('none')}")
            if validation:
                self.write(f"{self.t('training')}: {validation.get('training_years', [])}")
                self.write(f"{self.t('test')}: {validation.get('holdout_year', self.t('none'))}")
                for compound, metric in validation.get("compounds", {}).items():
                    if "mae_seconds" in metric:
                        self.write(
                            f"  {compound}: MAE={metric['mae_seconds']:.3f} s; "
                            f"RMSE={metric['rmse_seconds']:.3f} s"
                        )
                    else:
                        self.write(f"  {compound}: {self.t('missing')}")
                if not validation.get("compounds"):
                    self.write(self.t("unavailable"))
            self.write(f"{self.t('files')}: {output.resolve()}")
            for path in sorted(output.iterdir()):
                if path.is_file():
                    self.write(f"  {path.name}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.write(f"{self.t('readerror')}: {exc}")

    def browse(self):
        names = ("strategy.json", "backtest.json", "driver-analysis.json")
        runs = (
            []
            if not self.output_root.is_dir()
            else [
                path
                for path in self.output_root.iterdir()
                if path.is_dir() and any((path / name).is_file() for name in names)
            ]
        )
        runs = sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        if not runs:
            self.write(self.t("empty"))
            return
        index = self.ask(
            "pickrun",
            1,
            number=int,
            minimum=1,
            maximum=len(runs),
            content=[f"{i}. {path.name}" for i, path in enumerate(runs, 1)],
        )
        self.summary(runs[index - 1])

    def settings(self):
        output = Path(self.ask("out", str(self.output_root)).strip('"')).expanduser()
        cache = Path(self.ask("cache", str(self.cache_root)).strip('"')).expanduser()
        if any(p.exists() and not p.is_dir() for p in (output, cache)):
            self.write(self.t("invalid"))
        else:
            self.output_root, self.cache_root = output, cache
            self.write(self.t("saved"))

    def loop(self):
        while True:
            try:
                choice = self.ask(
                    "choose",
                    choices=tuple("01234567"),
                    content=self.t("menu").splitlines(),
                    menu=True,
                )
                if choice == "0":
                    break
                if choice == "7":
                    self.language = "en" if self.language == "zh" else "zh"
                elif choice == "5":
                    self.browse()
                elif choice == "6":
                    self.wizard(self.settings)
                else:
                    self.execute(*self.wizard(lambda: self.plan(choice)))
                if choice != "7":
                    self.pause()
            except (BackToMenu, KeyboardInterrupt):
                self.write(f"\n{self.t('cancelled')}")
            except EOFError:
                break
            except OSError as exc:
                self.write(f"{self.t('failed')} {exc}")
                self.pause()
        self.write(self.t("bye"))
        return 0


def main():
    # Windows pipes and older console code pages should not garble UTF-8 logs.
    import sys

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        print("\n请选择语言 / Choose language\n1  中文\n2  English")
        while True:
            choice = input("[1/2] (default: 1): ").strip() or "1"
            if choice in ("1", "2"):
                return Terminal("zh" if choice == "1" else "en").loop()
            print("请输入 1 或 2 / Enter 1 or 2")
    except (EOFError, KeyboardInterrupt):
        print("\n已退出 / Goodbye")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
