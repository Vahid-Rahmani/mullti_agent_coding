"""Settings modal — dedicated settings UI and logic for the retro terminal.

Encapsulates everything the settings window needs: the modal state machine
(open / agent-toggles submenu / theme-customizer submenu), the editable
draft, the committed ``terminal_settings``, persistence through the core
state tracker, and the prompt_toolkit styled-fragment rendering.

Clean-architecture note:
  * core/  — persistence (``state_tracker.STATE``), dispatch config model
  * ui/    — this module (settings state + rendering) and ``terminal_app``
             (app wiring: key bindings, floats, delegation)
No core logic lives here; ``RetroTerminalApp`` only wires the modal in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .palette import (
    BLACK, GREY, WHITE, ORANGE,
    DIFF_ADD, DIFF_REMOVE, DIFF_HEADER, DIFF_HUNK,
)
from .theme import THEMES

from ..core.agents import (
    AGENTS, AGENT_SPECS, AGENT_SPEC_BY_TAG, AUTO_MODEL, AUTO_MODE,
    MASTER_SPEC, MODEL_OPTIONS, MODE_OPTIONS_BY_MODEL, mode_options_for,
)

if TYPE_CHECKING:
    from .terminal_app import RetroTerminalApp


# ══════════════════════════════════════════════════════════════════════
#  Theme-customizer catalog (module-level so the shim can re-export it)
# ══════════════════════════════════════════════════════════════════════

# (key, human label, category) — rendered as rows in the COLOR customizer.
COLOR_COMPONENTS: list[tuple[str, str, str]] = [
    ("execution_logs", "Execution Logs", "CODE & TEXT STREAMS"),
    ("thinking_logs", "Thinking Logs", "CODE & TEXT STREAMS"),
    ("todo_logs", "Todo Logs", "CODE & TEXT STREAMS"),
    ("diff_add", "Diff Additions", "CODE & TEXT STREAMS"),
    ("diff_remove", "Diff Removals", "CODE & TEXT STREAMS"),
    ("diff_header", "Diff Headers", "CODE & TEXT STREAMS"),
    ("diff_hunk", "Diff Hunks", "CODE & TEXT STREAMS"),
    ("active_tabs", "Active Tabs", "HEADERS & TABS"),
    ("inactive_tabs", "Inactive Tabs", "HEADERS & TABS"),
    ("banner", "Banner", "HEADERS & TABS"),
    ("dir_line", "Directory Line", "HEADERS & TABS"),
    ("model_bar", "Model Bar", "HEADERS & TABS"),
    ("panel_borders", "Panel Borders", "WINDOWS & PANEL BORDERS"),
    ("console_bg", "Console Background", "WINDOWS & PANEL BORDERS"),
    ("input_box", "Input Box", "INPUT & ACTION BOXES"),
    ("menu_items", "Menu Items", "INPUT & ACTION BOXES"),
]

# Default component colors for the "zova" palette (the base look & feel).
_DEFAULT_COMPONENT_COLORS: dict[str, dict[str, str]] = {
    "zova": {
        "execution_logs": GREY,
        "thinking_logs": GREY,
        "todo_logs": WHITE,
        "diff_add": DIFF_ADD,
        "diff_remove": DIFF_REMOVE,
        "diff_header": DIFF_HEADER,
        "diff_hunk": DIFF_HUNK,
        "active_tabs": ORANGE,
        "inactive_tabs": ORANGE,
        "banner": WHITE,
        "dir_line": GREY,
        "model_bar": WHITE,
        "panel_borders": WHITE,
        "console_bg": BLACK,
        "input_box": WHITE,
        "menu_items": WHITE,
    },
}

# Maps a component key to (style class, style builder(color, theme)).
# The builder receives the cycled color and the active Theme so the class
# always keeps the correct background/bold attributes.
_COMPONENT_RULES: dict[str, tuple[str, object]] = {
    "execution_logs": ("retro.panel.execution", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "thinking_logs": ("retro.panel.thinking", lambda c, t: f"bg:{t.bg} fg:{c} italic"),
    "todo_logs": ("retro.panel.todo", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "diff_add": ("retro.diff.add", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "diff_remove": ("retro.diff.remove", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "diff_header": ("retro.diff.header", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "diff_hunk": ("retro.diff.hunk", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "active_tabs": ("retro.tab.active", lambda c, t: f"bold bg:{t.bg_input} fg:{c}"),
    "inactive_tabs": ("retro.tab.inactive", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "banner": ("retro.banner", lambda c, t: f"bold bg:{t.bg} fg:{c}"),
    "dir_line": ("retro.dir", lambda c, t: f"bold bg:{t.bg} fg:{c}"),
    "model_bar": ("retro.model", lambda c, t: f"bold bg:{t.bg} fg:{c}"),
    "panel_borders": ("retro.panel.content", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "console_bg": ("retro.console", lambda c, t: f"bg:{t.bg} fg:{c}"),
    "input_box": ("retro.input", lambda c, t: f"bg:{t.bg_input} fg:{c} bold"),
    "menu_items": ("retro.menu.item", lambda c, t: f"bg:{t.bg} fg:{c}"),
}

# Colors the customizer cycles through (never equals the zova defaults).
_COLOR_CYCLE: list[str] = [
    "#f85149", "#f0883e", "#3fb950", "#58a6ff",
    "#79c0ff", "#e6edf3", "#c9d1d9", "#6e7681",
]

# Main settings screen row groups. GENERAL holds the global execution mode
# defaults (master-level model/mode + layout); each registry agent gets its
# own row under AGENTS — INDIVIDUAL; the two action rows are always pinned.
_SETTINGS_GROUPS: dict[str, str] = {
    "general_model": "GENERAL — GLOBAL EXECUTION MODE",
    "general_mode": "GENERAL — GLOBAL EXECUTION MODE",
    "theme": "GENERAL — GLOBAL EXECUTION MODE",
    "density": "GENERAL — GLOBAL EXECUTION MODE",
    "agent_toggles": "GENERAL — GLOBAL EXECUTION MODE",
}

_AGENTS_GROUP = "AGENTS — INDIVIDUAL"


def _is_agent_row(key: str) -> bool:
    """True for per-agent rows (``agent_<tag>``); ``agent_toggles`` is a
    GENERAL action row, not an agent row."""
    return key.startswith("agent_") and key != "agent_toggles"


def _agent_row_key(spec) -> str:
    """Stable settings row key for one registry agent."""
    return f"agent_{spec.tag}"


def _settings_fields() -> list[str]:
    """Main settings rows, derived live from the agent registry.

    GENERAL (global execution mode) + one row per agent in the registry
    (M1..M7, in roster order) + the pinned SAVE/CANCEL actions. Nothing is
    hardcoded to a fixed seven-agent roster: adding or removing an agent from
    ``scripts/core/agents/`` propagates here automatically.
    """
    fields = ["general_model", "general_mode", "theme", "density", "agent_toggles"]
    fields += [_agent_row_key(spec) for spec in AGENT_SPECS]
    fields += ["save", "cancel"]
    return fields


def _settings_label(key: str) -> str:
    """Human label for a main-screen field key."""
    if key == "general_model":
        return "AI MODEL (GLOBAL DEFAULT)"
    if key == "general_mode":
        return "OPERATING MODE (GLOBAL)"
    if key == "theme":
        return "COLOR THEME"
    if key == "density":
        return "LAYOUT DENSITY"
    if key == "agent_toggles":
        return "AGENT TOGGLES"
    if key == "save":
        return "SAVE & APPLY"
    if key == "cancel":
        return "CANCEL"
    if _is_agent_row(key):
        spec = AGENT_SPEC_BY_TAG.get(key[len("agent_"):])
        if spec is not None:
            slot = next(
                (i for i, s in enumerate(AGENT_SPECS) if s.tag == spec.tag), -1
            ) + 1
            return f"{slot}. {spec.name.upper()} · {spec.role.upper()}"
    return key


def _settings_group(key: str) -> str | None:
    """Section header for a main-screen field key (None for the actions)."""
    if _is_agent_row(key):
        return _AGENTS_GROUP
    return _SETTINGS_GROUPS.get(key)


def _compact_model(model: str) -> str:
    """Short display label for a model on the per-agent rows."""
    if not model or model == AUTO_MODEL:
        return "auto"
    if model.startswith("opencode/"):
        return model[len("opencode/"):]
    if model.startswith("ollama/"):
        return model[len("ollama/"):]
    if model.startswith("mulerouter/"):
        return model[len("mulerouter/"):]
    return model


def _compact_mode(mode: str) -> str:
    """Short display label for a mode on the per-agent rows."""
    if not mode or mode == AUTO_MODE:
        return "auto"
    return mode

_DEFAULT_TERMINAL_SETTINGS: dict = {
    "theme": "classic",
    "font_size": "medium",
    "density": "comfortable",
    "panel_borders": True,
    "theme_colors": {},
}

# 1 border + 16 components + 4 category headers + RESET + SAVE + BACK + 1 border.
_DEFAULT_SETTINGS_HEIGHT = 25


class SettingsModal:
    """State machine + rendering + persistence for the settings window.

    The modal is fully decoupled from key handling: the host app calls
    ``toggle_settings`` / ``close_settings`` / ``handle_escape`` from its key
    bindings and forwards any settings attribute/method through delegation.
    """

    def __init__(self, app: "RetroTerminalApp") -> None:
        self.app = app
        self.settings_open = False
        self.agent_menu_open = False
        self.theme_menu_open = False
        # Per-agent / global model-mode submenu (opened from a GENERAL or
        # AGENTS row on the main screen).
        self.submenu_open = False
        self.submenu_target: str = "master"
        self.submenu_focus = 0
        self.settings_focus = 0
        self.agent_focus = 0
        self.theme_focus = 0
        self.settings_height = _DEFAULT_SETTINGS_HEIGHT
        self.terminal_settings: dict = dict(_DEFAULT_TERMINAL_SETTINGS)
        self.settings_draft: dict = self._empty_draft()
        # Undo history for the theme customizer: (field, previous_draft_value).
        self._theme_history: list[tuple[str, str | None]] = []

    # ------------------------------------------------------------------ draft

    def _empty_draft(self) -> dict:
        return {
            "enabled_agents": set(self.app.enabled_agents),
            "target": "master",
            "theme": self.terminal_settings.get("theme", "classic"),
            "font_size": self.terminal_settings.get("font_size", "medium"),
            "density": self.terminal_settings.get("density", "comfortable"),
            "panel_borders": self.terminal_settings.get("panel_borders", True),
            "overrides": {},
            "theme_colors": {},
        }

    def _init_draft(self) -> None:
        self.settings_draft = self._empty_draft()
        self.settings_focus = 0
        self.agent_focus = 0
        self.theme_focus = 0
        self.submenu_open = False
        self.submenu_target = "master"
        self.submenu_focus = 0
        self._theme_history.clear()

    def _invalidate(self) -> None:
        self.app._invalidate_ui()

    def _modal_width(self) -> int:
        try:
            columns = self.app._screen_size()[0]
        except Exception:  # noqa: BLE001
            columns = 100
        return max(30, min(70, columns - 4))

    # ------------------------------------------------------------- open/close

    def toggle_settings(self) -> None:
        if self.settings_open:
            self.close_settings(save=False)
        else:
            self.open_settings()

    def open_settings(self) -> None:
        self.settings_open = True
        self.agent_menu_open = False
        self.theme_menu_open = False
        self.submenu_open = False
        self._init_draft()
        # Drop any dropdown menu so the modal renders cleanly on top.
        try:
            self.app.close_menu()
        except Exception:  # noqa: BLE001
            pass
        self._invalidate()

    def close_settings(self, save: bool = True) -> None:
        if not self.settings_open:
            return
        self.settings_open = False
        self.agent_menu_open = False
        self.theme_menu_open = False
        self.submenu_open = False
        self.submenu_target = "master"
        self.submenu_focus = 0
        if save:
            self._apply_draft()
            self._persist()
        else:
            # Revert any live theme preview back to committed settings.
            self.settings_draft["theme_colors"] = {}
            self._rebuild_app_style()
        self._invalidate()

    def handle_escape(self) -> None:
        """Esc walks up: theme customizer -> agent toggles -> agent/global
        model-mode submenu -> main -> close."""
        if self.theme_menu_open:
            self.close_theme_menu()
        elif self.agent_menu_open:
            self.close_agent_menu()
        elif self.submenu_open:
            self.close_agent_submenu()
        elif self.settings_open:
            self.close_settings(save=False)

    # ---------------------------------------------------------- main settings

    def _settings_fields(self) -> list[str]:
        return _settings_fields()

    def _resolve_target_value(self, target: str, key: str) -> str:
        """Effective value for a target: draft override > committed > auto."""
        over = self.settings_draft.get("overrides", {}).get(target, {})
        if key == "model":
            value = over.get("model")
            if value:
                return value
            model, _mode = self.app.hub.resolve(target, self.app.overrides)
            return model or AUTO_MODEL
        if key == "mode":
            value = over.get("mode")
            if value:
                return value
            _model, mode = self.app.hub.resolve(target, self.app.overrides)
            return mode or AUTO_MODE
        return ""

    def _settings_value(self, key: str) -> str:
        """Value for the currently selected mapping target (master by default)."""
        return self._resolve_target_value(
            self.settings_draft.get("target", "master"), key
        )

    def _settings_set_mapping_for(self, target: str, key: str, value: str) -> None:
        self.settings_draft.setdefault("overrides", {}).setdefault(target, {})[key] = value
        self._invalidate()

    def _settings_set_mapping(self, key: str, value: str) -> None:
        """Write a model/mode override into the draft for the selected target.

        Every agent (M1..M7) plus the master default is individually
        configurable — there are no locked targets anymore. Kept alongside
        ``_settings_value`` as the legacy ``target``-based mapping surface
        (the submenu uses ``_settings_set_mapping_for`` directly).
        """
        self._settings_set_mapping_for(self.settings_draft.get("target", "master"), key, value)

    def _effective_model(self, target: str) -> str:
        """Model whose mode options should be offered (draft override wins)."""
        over = self.settings_draft.get("overrides", {}).get(target, {})
        model = over.get("model")
        if model and model != AUTO_MODEL:
            return model
        resolved, _mode = self.app.hub.resolve(target, self.app.overrides)
        return resolved or AUTO_MODEL

    def _field_value(self, key: str) -> str:
        draft = self.settings_draft
        if key == "general_model":
            return self._resolve_target_value("master", "model")
        if key == "general_mode":
            return self._resolve_target_value("master", "mode")
        if _is_agent_row(key):
            tag = key[len("agent_"):]
            return f"{_compact_model(self._resolve_target_value(tag, 'model'))} · {_compact_mode(self._resolve_target_value(tag, 'mode'))}"
        if key == "theme":
            return str(draft.get("theme", ""))
        if key == "density":
            return str(draft.get("density", ""))
        if key == "agent_toggles":
            return f"{len(draft.get('enabled_agents', set()))} ON"
        return ""

    def _activate_settings_field(self, key: str) -> None:
        if key == "theme":
            self.open_theme_menu()
        elif key == "agent_toggles":
            self.open_agent_menu()
        elif key == "save":
            self.close_settings(save=True)
        elif key == "cancel":
            self.close_settings(save=False)
        elif key == "general_model":
            self.open_agent_submenu("master", 0)
        elif key == "general_mode":
            self.open_agent_submenu("master", 1)
        elif _is_agent_row(key):
            self.open_agent_submenu(key[len("agent_"):], 0)
        else:
            fields = self._settings_fields()
            if key in fields:
                self.settings_focus = fields.index(key)

    def _settings_cycle(self, delta: int = 1) -> None:
        # Inside a submenu, Enter acts on that submenu's focused row.
        if self.theme_menu_open:
            self._theme_cycle(delta)
            return
        if self.agent_menu_open:
            self._agent_cycle(delta)
            return
        if self.submenu_open:
            self._submenu_cycle(delta)
            return
        fields = self._settings_fields()
        focus = min(max(0, self.settings_focus), len(fields) - 1)
        key = fields[focus]
        if _is_agent_row(key) or key in (
            "general_model", "general_mode",
            "theme", "agent_toggles", "save", "cancel",
        ):
            self._activate_settings_field(key)
        else:
            self.settings_focus = (focus + delta) % len(fields)

    # ------------------------------------------------------- agent toggles

    def _agent_toggle_fields(self) -> list[str]:
        return [f"agent_toggle_{tag}" for tag, _name, _agent in AGENTS] + ["back"]

    def _agent_value(self, tag: str) -> str:
        enabled = self.settings_draft.get("enabled_agents", set())
        return "[ ON ]" if tag in enabled else "[ OFF ]"

    def open_agent_menu(self) -> None:
        self.agent_menu_open = True
        self.agent_focus = 0
        self._invalidate()

    def close_agent_menu(self) -> None:
        self.agent_menu_open = False
        self._invalidate()

    def _agent_cycle(self, delta: int = 1) -> None:  # noqa: ARG002 — delta = activation
        fields = self._agent_toggle_fields()
        if not fields:
            return
        focus = min(max(0, self.agent_focus), len(fields) - 1)
        field = fields[focus]
        if field.startswith("agent_toggle_"):
            tag = field[len("agent_toggle_"):]
            enabled = self.settings_draft.setdefault("enabled_agents", set(self.app.enabled_agents))
            if tag in enabled:
                enabled.discard(tag)
            else:
                enabled.add(tag)
            self._invalidate()
        elif field == "back":
            self.close_agent_menu()

    # -------------------------------------------------- agent/global submenu

    def _submenu_fields(self) -> list[str]:
        return ["model", "mode", "back"]

    def open_agent_submenu(self, tag: str, focus: int = 0) -> None:
        """Open the model/mode submenu for one target (an agent tag or master).

        ``master`` is the GENERAL execution-mode section: its model/mode act
        as the global defaults every agent inherits unless they have their own
        override. Every other target is a specific registry agent (M1..M7).
        """
        self.submenu_open = True
        self.submenu_target = tag
        self.submenu_focus = focus
        self._invalidate()

    def close_agent_submenu(self) -> None:
        self.submenu_open = False
        self.submenu_target = "master"
        self.submenu_focus = 0
        self._invalidate()

    def _submenu_title(self) -> str:
        spec = AGENT_SPEC_BY_TAG.get(self.submenu_target) or MASTER_SPEC
        return f" {spec.name.upper()} · {spec.role.upper()} SETTINGS "

    def _submenu_cycle(self, delta: int = 1) -> None:
        fields = self._submenu_fields()
        if not fields:
            return
        focus = min(max(0, self.submenu_focus), len(fields) - 1)
        field = fields[focus]
        if field == "model":
            self._cycle_target_value(self.submenu_target, "model", delta)
        elif field == "mode":
            self._cycle_target_value(self.submenu_target, "mode", delta)
        elif field == "back":
            self.close_agent_submenu()

    def _cycle_target_value(self, target: str, key: str, delta: int = 1) -> None:
        """Advance the draft value of a target's model/mode by ``delta``."""
        if key == "model":
            options = list(MODEL_OPTIONS)
            current = self._resolve_target_value(target, "model")
            index = options.index(current) if current in options else -1
            next_value = options[(index + delta) % len(options)]
            self._settings_set_mapping_for(target, "model", next_value)
            return
        if key == "mode":
            model = self._effective_model(target)
            # The target agent's own modes stay available regardless of the
            # chosen model, so unlocking a model never hides native modes.
            options = mode_options_for(model, target)
            current = self._resolve_target_value(target, "mode")
            index = options.index(current) if current in options else -1
            next_value = options[(index + delta) % len(options)]
            self._settings_set_mapping_for(target, "mode", next_value)

    # -------------------------------------------------------- theme customizer

    def _theme_fields(self) -> list[str]:
        return [key for key, _label, _category in COLOR_COMPONENTS] + ["reset", "save", "back"]

    def _theme_value(self, key: str) -> str:
        draft = self.settings_draft.get("theme_colors", {}).get("zova", {})
        if key in draft:
            return draft[key]
        committed = self.terminal_settings.get("theme_colors", {}).get("zova", {})
        if key in committed:
            return committed[key]
        return _DEFAULT_COMPONENT_COLORS.get("zova", {}).get(key, GREY)

    def _theme_cycle(self, delta: int = 1) -> None:
        fields = self._theme_fields()
        if not fields:
            return
        focus = min(max(0, self.theme_focus), len(fields) - 1)
        field = fields[focus]
        if field == "reset":
            self._theme_reset()
            return
        if field == "save":
            self.close_settings(save=True)
            return
        if field == "back":
            self.close_theme_menu()
            return
        if field not in _COMPONENT_RULES:
            return
        current = self._theme_value(field)
        # Record the previous draft value for undo (None = not in the draft yet).
        draft_zova = self.settings_draft.get("theme_colors", {}).get("zova", {})
        self._theme_history.append((field, draft_zova.get(field)))
        self._theme_history = self._theme_history[-64:]
        if current in _COLOR_CYCLE:
            index = _COLOR_CYCLE.index(current)
            next_color = _COLOR_CYCLE[(index + delta) % len(_COLOR_CYCLE)]
            if next_color == current:
                next_color = _COLOR_CYCLE[(index + 1) % len(_COLOR_CYCLE)]
        else:
            next_color = _COLOR_CYCLE[0]
        colors = self.settings_draft.setdefault("theme_colors", {})
        colors.setdefault("zova", {})[field] = next_color
        self._rebuild_app_style()

    def _theme_undo(self) -> None:
        """Revert the most recent customizer change (live preview included)."""
        if not self._theme_history:
            return
        field, previous = self._theme_history.pop()
        zova = self.settings_draft.setdefault("theme_colors", {}).setdefault("zova", {})
        if previous is None:
            zova.pop(field, None)
        else:
            zova[field] = previous
        self._rebuild_app_style()
        self._invalidate()

    def _theme_reset(self) -> None:
        """Clear every customizer draft change back to the zova defaults."""
        self.settings_draft["theme_colors"] = {}
        self._theme_history.clear()
        self._rebuild_app_style()
        self._invalidate()

    def _theme_visible_indices(self, fields: list[str]) -> list[int]:
        """Indices of theme fields that fit in ``settings_height`` rows.

        The last three action fields (reset, save, back) are always pinned to
        the bottom; the component rows scroll above them and always include
        the focus.
        """
        count = len(fields)
        height = max(5, int(self.settings_height))
        body_budget = max(1, height - 5)  # top border + reset/save/back + bottom
        action_start = max(0, count - 3)
        focus = min(max(0, self.theme_focus), count - 1)
        if focus >= action_start:
            start = max(0, action_start - body_budget)
        else:
            start = min(focus, max(0, action_start - body_budget))
        start = min(start, action_start)
        indices = list(range(start, min(start + body_budget, action_start)))
        indices += list(range(action_start, count))
        return indices

    def open_theme_menu(self) -> None:
        self.theme_menu_open = True
        self.theme_focus = 0
        self._invalidate()

    def close_theme_menu(self) -> None:
        self.theme_menu_open = False
        self._invalidate()

    # ------------------------------------------------------------- rendering

    def _settings_fragments(self) -> list[tuple]:
        if not self.settings_open:
            return []
        if self.theme_menu_open:
            return self._theme_fragments()
        if self.agent_menu_open:
            return self._agent_fragments()
        if self.submenu_open:
            return self._submenu_fragments()
        return self._main_fragments()

    def _row(self, text: str, width: int) -> str:
        inner = max(1, width - 2)
        return "│" + text[:inner].ljust(inner) + "│"

    def _main_visible_fields(self, fields: list[str]) -> list[str]:
        """Slice the main-screen rows to fit ``settings_height`` rows.

        The last two action rows (save, cancel) are always pinned to the
        bottom; the section headers and the rows above them scroll and always
        include the focus (mirrors the theme customizer's behavior).

        Fixed chrome per render: title + 2 spacer rows + hint + bottom border
        (5 rows) plus the 2 pinned action rows, so the scrollable budget is
        ``height - 7`` minus the section headers that can appear.
        """
        count = len(fields)
        height = max(6, int(self.settings_height))
        header_count = len({_settings_group(key) for key in fields if _settings_group(key)})
        body_budget = max(1, height - 7 - header_count)
        action_start = max(0, count - 2)
        focus = min(max(0, self.settings_focus), count - 1)
        if focus >= action_start:
            start = max(0, action_start - body_budget)
        else:
            start = min(focus, max(0, action_start - body_budget))
        start = min(start, action_start)
        indices = list(range(start, min(start + body_budget, action_start)))
        indices += list(range(action_start, count))
        return [fields[i] for i in indices]

    def _main_fragments(self) -> list[tuple]:
        width = self._modal_width()
        height = max(6, int(self.settings_height))
        border = "class:retro.menu.border"
        frags: list[tuple] = []
        title = " ZOVA SETTINGS "
        inner = max(2, width - 4)
        frags.append((border, "╭─" + title[:inner].ljust(inner, "─") + "╮\n"))
        frags.append((border, self._row("", width) + "\n"))
        frags.append((border, self._row("", width) + "\n"))
        all_fields = self._settings_fields()
        fields = self._main_visible_fields(all_fields)
        prev_group: str | None = None
        for index, key in enumerate(fields):
            global_index = all_fields.index(key)
            group = _settings_group(key)
            if group and group != prev_group:
                frags.append((
                    "class:retro.muted",
                    self._row("  ── " + group + " ──", width) + "\n",
                ))
                prev_group = group
            label = _settings_label(key)
            text = f" [{global_index + 1}] {label}"
            value = self._field_value(key)
            if value:
                text += f"   {value}"
            def click(_event=None, _key=key) -> None:
                self._activate_settings_field(_key)
            style = (
                "class:retro.tab.active" if global_index == self.settings_focus
                else "class:retro.menu.item"
            )
            frags.append((style, self._row(text, width) + "\n", click))
        hint = " ENTER TO CUSTOMIZE  •  [↑/↓] navigate  •  Esc close "
        frags.append(("class:retro.muted", self._row(hint, width) + "\n"))
        frags.append((border, "╰" + "─" * max(0, width - 2) + "╯\n"))
        return frags

    def _submenu_fragments(self) -> list[tuple]:
        width = self._modal_width()
        height = max(6, int(self.settings_height))
        border = "class:retro.menu.border"
        frags: list[tuple] = []
        title = self._submenu_title()
        inner = max(2, width - 4)
        frags.append((border, "╭─" + title[:inner].ljust(inner, "─") + "╮\n"))
        target = self.submenu_target
        rows: list[tuple[str, str]] = [
            ("model", f"AI MODEL   {self._resolve_target_value(target, 'model')}"),
            ("mode", f"OPERATING MODE   {self._resolve_target_value(target, 'mode')}"),
            ("back", "BACK TO SETTINGS"),
        ]
        max_rows = max(0, height - 3)
        if 0 < max_rows < len(rows):
            rows = rows[:max_rows]
        for index, (field, label) in enumerate(rows):
            def click(_event=None, _field=field) -> None:
                self.submenu_focus = self._submenu_fields().index(_field)
                self._submenu_cycle(1)
            style = (
                "class:retro.tab.active" if index == min(self.submenu_focus, len(rows) - 1)
                else "class:retro.menu.item"
            )
            frags.append((style, self._row(" " + label, width) + "\n", click))
        hint = " ENTER CYCLES  •  [↑/↓] navigate  •  Esc back "
        frags.append(("class:retro.muted", self._row(hint, width) + "\n"))
        frags.append((border, "╰" + "─" * max(0, width - 2) + "╯\n"))
        return frags

    def _agent_fragments(self) -> list[tuple]:
        width = self._modal_width()
        height = max(6, int(self.settings_height))
        border = "class:retro.menu.border"
        frags: list[tuple] = []
        title = " AGENT TOGGLES "
        inner = max(2, width - 4)
        frags.append((border, "╭─" + title[:inner].ljust(inner, "─") + "╮\n"))
        enabled = self.settings_draft.get("enabled_agents", set())
        rows: list[tuple[str, str]] = []
        for index, (tag, name, _agent) in enumerate(AGENTS):
            rows.append((f"agent_toggle_{tag}", f"M{index + 1}: {name}   {self._agent_value(tag)}"))
        rows.append(("back", "BACK TO SETTINGS"))
        max_rows = max(0, height - 2)
        if 0 < max_rows < len(rows):
            rows = rows[:max_rows]
        for index, (field, label) in enumerate(rows):
            def click(_event=None, _field=field) -> None:
                if _field == "back":
                    self.close_agent_menu()
                else:
                    self.agent_focus = self._agent_toggle_fields().index(_field)
                    self._agent_cycle(1)
            style = (
                "class:retro.tab.active" if index == min(self.agent_focus, len(rows) - 1)
                else "class:retro.menu.item"
            )
            frags.append((style, self._row(" " + label, width) + "\n", click))
        frags.append((border, "╰" + "─" * max(0, width - 2) + "╯\n"))
        return frags

    def _theme_fragments(self) -> list[tuple]:
        width = self._modal_width()
        border = "class:retro.menu.border"
        frags: list[tuple] = []
        title = " COLOR CUSTOMIZER "
        inner = max(2, width - 4)
        frags.append((border, "╭─" + title[:inner].ljust(inner, "─") + "╮\n"))
        fields = self._theme_fields()
        # Category headers only fit when every row (headers included) fits in
        # the modal height; otherwise fall back to the scrolling slice.
        category_count = len({category for _key, _label, category in COLOR_COMPONENTS})
        full_lines = 1 + len(COLOR_COMPONENTS) + category_count + 3 + 1
        full_mode = full_lines <= max(5, int(self.settings_height))
        visible = (
            list(range(len(fields)))
            if full_mode
            else self._theme_visible_indices(fields)
        )
        prev_category: str | None = None
        for index in visible:
            field = fields[index]
            if field == "reset":
                label = "RESET TO DEFAULTS"
                action = "reset"
            elif field == "save":
                label = "SAVE & APPLY"
                action = "save"
            elif field == "back":
                label = "BACK TO SETTINGS"
                action = "back"
            else:
                component = next((c for c in COLOR_COMPONENTS if c[0] == field), None)
                label = component[1] if component else field
                category = component[2] if component else ""
                if full_mode and category and category != prev_category:
                    frags.append((
                        "class:retro.muted",
                        self._row("  ── " + category + " ──", width) + "\n",
                    ))
                    prev_category = category
                label += f"   [{self._theme_value(field)}]"
                action = "component"
            def click(_event=None, _action=action, _index=index) -> None:
                self.theme_focus = _index
                if _action == "reset":
                    self._theme_reset()
                elif _action == "save":
                    self.close_settings(save=True)
                elif _action == "back":
                    self.close_theme_menu()
                else:
                    self._theme_cycle(1)
            style = (
                "class:retro.tab.active" if index == min(self.theme_focus, len(fields) - 1)
                else "class:retro.menu.item"
            )
            frags.append((style, self._row(" " + label, width) + "\n", click))
        frags.append((border, "╰" + "─" * max(0, width - 2) + "╯\n"))
        return frags

    # -------------------------------------------------------------- applying

    def _apply_draft(self) -> None:
        draft = self.settings_draft
        app = self.app
        app.enabled_agents = set(draft.get("enabled_agents", app.enabled_agents))
        for target, over in draft.get("overrides", {}).items():
            app.overrides.setdefault(target, {}).update(over)
        terminal = self.terminal_settings
        terminal["theme"] = draft.get("theme", terminal.get("theme", "classic"))
        terminal["font_size"] = draft.get("font_size", terminal.get("font_size", "medium"))
        terminal["density"] = draft.get("density", terminal.get("density", "comfortable"))
        terminal["panel_borders"] = draft.get("panel_borders", terminal.get("panel_borders", True))
        terminal["theme_colors"] = {
            theme_name: dict(colors)
            for theme_name, colors in draft.get("theme_colors", {}).items()
        }
        self._apply_terminal_settings()

    def _apply_terminal_settings(self) -> None:
        """Apply theme/density/font_size to the live layout.

        A registered ``theme`` name wins; otherwise the layout ``density``
        picks the matching theme (spacious -> classic, compact -> opencode).
        ``font_size`` scales the typography dimensions of the active theme.
        """
        density = str(self.terminal_settings.get("density", "comfortable"))
        if density in ("spacious", "compact"):
            # An explicit layout preference wins: it maps 1:1 to the two
            # registered layout bundles (spacious -> classic, compact -> opencode).
            self.app.theme = "opencode" if density == "compact" else "classic"
        else:
            # Density untouched: honor a registered color theme if chosen.
            name = self.terminal_settings.get("theme")
            self.app.theme = name if name and name in THEMES else "classic"
        self._apply_font_scale()
        self.app._rebuild_layout()
        self._rebuild_app_style()

    def _apply_font_scale(self) -> None:
        """Scale console/input dimensions on the active theme for font_size."""
        from dataclasses import replace

        from .theme import get_active, set_active_theme

        size = str(self.terminal_settings.get("font_size", "medium"))
        scale = {"small": 0.8, "standard": 1.0, "medium": 1.0, "large": 1.3}.get(size, 1.0)
        base = get_active()
        if abs(scale - 1.0) < 0.01:
            set_active_theme(base)
            return
        adjusted = replace(
            base,
            console_min_lines=max(2, int(round(base.console_min_lines * scale))),
            console_pref_lines=max(3, int(round(base.console_pref_lines * scale))),
            input_min_lines=max(1, int(round(base.input_min_lines * scale))),
            input_max_lines=max(3, int(round(base.input_max_lines * scale))),
        )
        set_active_theme(adjusted)

    def _rebuild_app_style(self) -> None:
        """Reset the app style to the active theme, then merge custom colors.

        Live preview colors (draft) take precedence over committed colors so
        the customizer shows its effect before the user hits SAVE.
        """
        app = self.app
        app._rebuild_style()
        merged: dict[str, dict[str, str]] = {}
        for source in (
            self.terminal_settings.get("theme_colors", {}),
            self.settings_draft.get("theme_colors", {}),
        ):
            for theme_name, colors in source.items():
                merged.setdefault(theme_name, {}).update(colors)
        for _theme_name, colors in merged.items():
            for key, color in colors.items():
                rule = _COMPONENT_RULES.get(key)
                if not rule:
                    continue
                class_name, builder = rule
                app._style_dict[class_name] = builder(color, app.theme)

    # ----------------------------------------------------------- persistence

    def _state(self):
        from ..core import state_tracker as _state_tracker

        return _state_tracker.STATE

    def _persist(self) -> None:
        try:
            data = self._state().load() or {}
            settings = dict(data.get("settings") or {})
            settings["enabled_agents"] = sorted(self.app.enabled_agents)
            settings["overrides"] = dict(self.app.overrides)
            settings["terminal"] = dict(self.terminal_settings)
            self._state().update(settings=settings)
        except Exception:  # noqa: BLE001 — persistence is best-effort
            pass

    def load_persisted(self) -> None:
        """Restore persisted settings into the app (called once at startup).

        Only known tags / override keys / terminal keys are applied, so stale
        or corrupt data from older sessions can never hide agents or inject
        junk overrides.
        """
        try:
            data = self._state().load()
        except Exception:  # noqa: BLE001
            return
        if not data:
            return
        settings = data.get("settings")
        if not isinstance(settings, dict):
            return

        valid_tags = {tag for tag, _name, _agent in AGENTS}
        enabled = settings.get("enabled_agents")
        if isinstance(enabled, (list, set, tuple)) and enabled:
            enabled_set = {str(tag) for tag in enabled} & valid_tags
            if enabled_set:
                self.app.enabled_agents = enabled_set

        overrides = settings.get("overrides")
        if isinstance(overrides, dict):
            for target, over in overrides.items():
                if target not in valid_tags and target != "master":
                    continue
                if not isinstance(over, dict):
                    continue
                clean = {
                    key: str(value)
                    for key, value in over.items()
                    if key in ("model", "mode") and isinstance(value, str)
                }
                if clean:
                    self.app.overrides.setdefault(str(target), {}).update(clean)

        terminal = settings.get("terminal")
        had_terminal = isinstance(terminal, dict) and bool(terminal)
        if had_terminal:
            self.terminal_settings.update(
                {key: value for key, value in terminal.items() if key in _DEFAULT_TERMINAL_SETTINGS}
            )
            # Only touch the live theme/layout/style when terminal settings
            # were actually persisted (avoids rebuild churn on every launch).
            self._apply_terminal_settings()

    # ------------------------------------------------------------ slash command

    def model_bar_settings(self) -> dict:
        """Snapshot of terminal settings with the *effective* theme name.

        The stored ``theme`` key can be overridden by an explicit ``density``
        (compact -> opencode); the status bar should reflect what the user
        actually sees.
        """
        data = dict(self.terminal_settings)
        data["theme"] = self.app.theme.name
        return data

    def navigate(self, delta: int) -> None:
        """Move focus by ``delta`` within the active modal view."""
        if self.theme_menu_open:
            fields = self._theme_fields()
            self.theme_focus = (self.theme_focus + delta) % max(1, len(fields))
        elif self.agent_menu_open:
            fields = self._agent_toggle_fields()
            self.agent_focus = (self.agent_focus + delta) % max(1, len(fields))
        elif self.submenu_open:
            fields = self._submenu_fields()
            self.submenu_focus = (self.submenu_focus + delta) % max(1, len(fields))
        elif self.settings_open:
            fields = self._settings_fields()
            self.settings_focus = (self.settings_focus + delta) % max(1, len(fields))
        self._invalidate()

    def _cmd_settings(self, _arg: str = "") -> str:
        arg = _arg.strip().lower()
        if arg in ("info", "text", "print", "show", "dump"):
            return self.settings_text()
        self.open_settings()
        return "settings modal opened"

    def settings_text(self) -> str:
        """Human-readable dump of the current settings for '/settings info'.

        Shows the effective theme (density-aware), density, font size, panel
        borders, enabled agents, and a per-tab model/mode override table.
        """
        from ..core.run_hub import build_overrides_table

        ts = self.terminal_settings
        theme = self.app.theme.name
        density = str(ts.get("density", "comfortable"))
        font = str(ts.get("font_size", "medium"))
        borders = "on" if ts.get("panel_borders", True) else "off"
        enabled = sorted(self.app.enabled_agents)
        enabled_list = ", ".join(enabled) if enabled else "none"
        lines = [
            f"THEME: {theme}",
            f"DENSITY: {density}",
            f"FONT: {font}",
            f"BORDERS: {borders}",
            f"AGENTS ({len(enabled)}/{len(AGENTS)}): {enabled_list}",
            "OVERRIDES:",
        ]
        lines.extend(
            "  " + line for line in build_overrides_table(self.app.overrides).splitlines()
        )
        return "\n".join(lines)
