import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from f1_strategy_optimizer.terminal import TEXT, BackToMenu, Terminal


def interface(answers, language="zh"):
    iterator = iter(answers)
    output = []
    ui = Terminal(language, reader=lambda _: next(iterator), writer=output.append)
    return ui, output


def test_translation_keys_match():
    assert TEXT["zh"].keys() == TEXT["en"].keys()


def test_invalid_numbers_reprompt_and_q_cancels():
    ui, output = interface(["nan", "inf", "-1", "2.5", "3", "q"])
    assert ui.number("laps", 57, 1, 500) == 3
    assert sum("不符合要求" in line for line in output) == 4
    assert any("1–500" in line for line in output)
    with pytest.raises(BackToMenu):
        ui.ask("track", "Bahrain")


def test_driver_plan_preserves_arguments_and_offline():
    ui, _ = interface(["", "", "Charles Leclerc", "", "", "", "", "", "", "", ""])
    module, args, output = ui.plan("3")
    assert module == "driver"
    assert args[args.index("--driver") + 1] == "Charles Leclerc"
    assert args[args.index("--mode") + 1] == "review"
    assert "--offline" in args and "--laps" not in args
    assert str(output).startswith("output")


def test_year_range_validation():
    ui, output = interface(["", "2023", "2022", "2025", "2023", "2025", "", ""])
    module, args, _ = ui.plan("4")
    assert module == "core"
    assert args[args.index("--holdout-year") + 1] == "2025"
    assert "2024–2100" in "\n".join(output)


def test_switch_language_and_exit():
    ui, output = interface(["7", "0"])
    assert ui.loop() == 0
    assert ui.language == "en"
    assert output[-1] == "Goodbye."


def test_failed_engine_returns_control(tmp_path):
    ui, output = interface([])
    with patch("f1_strategy_optimizer.cli.main", side_effect=SystemExit(2)):
        ui.execute("core", ["demo"], tmp_path)
    assert TEXT["zh"]["failed"] in output


def test_missing_results_and_corrupt_json(tmp_path):
    ui, output = interface([])
    ui.output_root = tmp_path
    ui.browse()
    assert output[-1] == TEXT["zh"]["empty"]
    (tmp_path / "strategy.json").write_text("broken", encoding="utf-8")
    ui.summary(tmp_path)
    assert TEXT["zh"]["readerror"] in output[-1]


def test_offline_demo_through_menu_and_browse(tmp_path):
    # demo -> five default parameters -> run -> browse newest result -> exit
    ui, output = interface(["1", "12", "", "", "", "", "", "5", "1", "0"])
    ui.output_root = tmp_path / "中文输出"
    with patch("f1_strategy_optimizer.cli.fetch_cycle_data", side_effect=AssertionError("network")):
        assert ui.loop() == 0
    runs = list(ui.output_root.iterdir())
    assert len(runs) == 1
    result = json.loads((runs[0] / "strategy.json").read_text(encoding="utf-8"))
    assert sum(result["stint_lengths"]) == 12
    assert any(TEXT["zh"]["summary"] in text for text in output)


@pytest.mark.parametrize(
    "language,title", [("1", TEXT["zh"]["main_title"]), ("2", TEXT["en"]["main_title"])]
)
def test_language_selection_in_real_process(tmp_path, language, title):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "f1_strategy_optimizer", "menu"],
        input=f"{language}\n0\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert title in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_eof_exits_cleanly():
    ui = Terminal("en", reader=Mock(side_effect=EOFError), writer=Mock())
    assert ui.loop() == 0


def test_cancel_settings_does_not_partially_apply():
    ui, _ = interface(["6", "changed-output", "q", "0"])
    ui.loop()
    assert ui.output_root == Path("output")


def test_driver_offline_provider(tmp_path):
    from f1_strategy_optimizer.driver_analysis import FastF1Provider

    api = Mock()
    with patch.dict(sys.modules, {"fastf1": api}):
        FastF1Provider(tmp_path / "new-cache", offline=True)
    api.Cache.offline_mode.assert_called_once_with(True)
    assert (tmp_path / "new-cache").is_dir()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_history_shows_actual_years_and_custom_start(language):
    ui, output = interface(["3", "2022 2024", "2022"], language)
    assert ui.history(2025, True) == 4
    transcript = "\n".join(output)
    assert "2023–2024" in transcript
    assert "2022–2024" in transcript
    assert "2018–2024" in transcript
    assert "2022 2024" in transcript  # specific rejected input is explained


def test_back_edits_previous_answer_and_keeps_earlier_answers():
    # Move back from fallback to the custom starting year, then change it.
    ui, output = interface(
        [
            "Bahrain",
            "Ferrari",
            "LEC",
            "2025",
            "2",
            "3",
            "2022",
            "b",
            "2021",
            "1",
            "57",
            "24",
            "50",
            "1",
            "1",
        ]
    )
    module, args, _ = ui.wizard(lambda: ui.plan("3"))
    assert module == "driver"
    assert args[args.index("--history-years") + 1] == "5"
    assert args[args.index("--driver") + 1] == "LEC"
    assert sum(TEXT["zh"]["back"] == line for line in output) == 1
    assert ui._answers is None


def test_back_across_mode_change_discards_dependent_fields():
    ui, _ = interface(["", "", "", "2025", "2", "b", "1", "2", "1", "24", "50", "1", "1"])
    _, args, _ = ui.wizard(lambda: ui.plan("3"))
    assert args[args.index("--mode") + 1] == "review"
    assert args[args.index("--history-years") + 1] == "3"
    assert "--laps" not in args


def test_back_from_first_step_and_quit_resets_wizard():
    ui, output = interface(["b", "q"])
    with pytest.raises(BackToMenu):
        ui.wizard(lambda: ui.plan("2"))
    assert TEXT["zh"]["first_step"] in output
    assert ui._answers is None


def test_settings_previous_step():
    ui, _ = interface(["first-output", "b", "second-output", "new-cache"])
    ui.wizard(ui.settings)
    assert ui.output_root == Path("second-output")
    assert ui.cache_root == Path("new-cache")


def test_main_menu_b_does_not_crash():
    ui, output = interface(["b", "0"])
    assert ui.loop() == 0
    assert output[-1] == TEXT["zh"]["bye"]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_interactive_help_and_error_replace_current_screen(language):
    from f1_strategy_optimizer.terminal import HELP

    screen, frames = [], []
    answers = iter(["?", "2022 2024", "2025"])

    def read(_):
        frames.append("\n".join(screen))
        return next(answers)

    ui = Terminal(
        language, reader=read, writer=screen.append, interactive=True, clearer=screen.clear
    )
    assert ui.wizard(lambda: ui.number("year", 2025, 2018, 2100)) == 2025
    assert HELP[language]["year"] not in frames[0]
    assert HELP[language]["year"] in frames[1]
    assert "2022 2024" in frames[2]
    assert all(frame.count(TEXT[language]["main_title"]) == 1 for frame in frames)
    assert all(TEXT[language]["step"].format(step=1) in frame for frame in frames)


def test_interactive_back_replaces_question_and_preserves_context():
    screen, frames = [], []
    answers = iter(["Monza", "b", "Bahrain", "LEC"])

    def read(_):
        frames.append("\n".join(screen))
        return next(answers)

    ui = Terminal(reader=read, writer=screen.append, interactive=True, clearer=screen.clear)
    assert ui.wizard(lambda: (ui.ask("track"), ui.ask("driver"))) == ("Bahrain", "LEC")
    assert "Monza" in frames[1]
    assert "Monza" not in frames[2]
    assert "Bahrain" in frames[3]
    assert TEXT["zh"]["driver"] not in frames[2]


def test_interactive_results_wait_before_returning_to_menu(tmp_path):
    answers = iter(["5", "", "0"])
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        return next(answers)

    ui = Terminal(reader=read, writer=Mock(), interactive=True, clearer=Mock())
    ui.output_root = tmp_path
    assert ui.loop() == 0
    assert TEXT["zh"]["pause"] in prompts[1]


def test_wrap_terminal_respects_chinese_cell_width():
    from f1_strategy_optimizer.terminal import wrap_terminal

    assert wrap_terminal("中文AB中文", 6) == ["中文AB", "中文"]
