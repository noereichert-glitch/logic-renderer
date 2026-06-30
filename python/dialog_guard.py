"""
dialog_guard.py — DialogGuard decision engine (Step 6a).

PURE, TESTABLE LOGIC. No AppleScript, no System Events, no AX, no Logic launch,
nothing wired into export_stems/quit_logic yet. Given a dialog already read by some
detector — {title, body, buttons[]} — plus the active locale and the render context,
it decides ONE action:

    • CLICK <button>   — click this exact (localized) button label
    • PAUSE            — pause-notify: do not touch the dialog, surface it
    • IGNORE           — nothing to act on (no body and no buttons)

Policy (see docs/2026-06-28/logic_dialog_catalog.md, Step 1b):
  • Rules are anchored on Logic's `.strings` KEY; localized strings live in
    dialog_rules.yaml (all 7 shipped locales). Bodies are matched with the runtime
    tokens (^P ^C %@ %ld %1$s …) treated as WILDCARDS.
  • A `never_click` button is NEVER clicked, even if a matching rule lists it.
  • Evaluate higher-risk actions first: pause_notify / fail_job / dismiss_gated
    before dismiss_safe.
  • The gated Replace (C2) is clicked ONLY when G1 ∧ G2 ∧ G3 all hold; else PAUSE.
  • FAIL-SAFE: any dialog that matches no rule in the active locale → PAUSE. The
    engine never guesses.

`fail_job` rules still return CLICK <OK> (to clear the modal) but flag the Decision
as terminal=True so the orchestrator can fail/relaunch the job afterwards.
"""
import os
import re

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is available in this env
    yaml = None

_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'dialog_rules.yaml')

# Runtime-substituted placeholders in Logic's strings → treated as wildcards when
# matching a live dialog body against an anchor.  %@  %ld  %d  %1$s  %2$s  ^P  ^C ...
_TOKEN_RE = re.compile(r'%\d*\$?[@a-zA-Z]|\^[A-Za-z]')

# Priority order for evaluating rule actions (higher risk first).
_ACTION_PRIORITY = {
    'pause_notify': 0,
    'fail_job': 1,
    'dismiss_gated': 2,
    'dismiss_safe': 3,
    'ignore': 4,
}


def _normalize(s):
    """Fold curly quotes/apostrophes to straight and collapse all whitespace
    (incl. the literal \\n in anchors and the newlines AX returns) to single
    spaces, so matching is robust to typography and line-wrapping."""
    if not s:
        return ''
    for a, b in (('“', '"'), ('”', '"'), ('„', '"'), ('‘', "'"), ('’', "'"),
                 (' ', ' ')):
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s).strip()


def _anchor_segments(anchor):
    """Split an anchor on its runtime tokens → the ordered list of literal text
    segments that must all appear, in order, in a matching body."""
    return [seg for seg in (_normalize(p) for p in _TOKEN_RE.split(anchor)) if seg]


def _body_matches(anchor, body_norm):
    """True if every literal segment of `anchor` appears in order within the
    already-normalized `body_norm` (tokens are wildcards)."""
    segs = _anchor_segments(anchor)
    if not segs:
        return False
    pos = 0
    for seg in segs:
        idx = body_norm.find(seg, pos)
        if idx < 0:
            return False
        pos = idx + len(seg)
    return True


class Decision:
    CLICK = 'click'
    PAUSE = 'pause-notify'
    IGNORE = 'ignore'

    def __init__(self, action, button=None, rule_id=None, reason='', terminal=False,
                 user_message=''):
        self.action = action
        self.button = button          # localized label to click (CLICK only)
        self.rule_id = rule_id
        self.reason = reason
        self.terminal = terminal      # fail_job: clear the modal, then fail the job
        # Plain-language, actionable sentence for the client (rule's `user_message`,
        # or the generic fallback when no rule matched). Surfaced by the notification
        # layer; empty for IGNORE/auto-handled paths that never reach the user.
        self.user_message = user_message

    def __repr__(self):
        b = f' button={self.button!r}' if self.button else ''
        t = ' terminal' if self.terminal else ''
        return (f'<Decision {self.action}{b} rule={self.rule_id} '
                f'reason={self.reason!r}{t}>')

    def __eq__(self, other):
        return (isinstance(other, Decision) and self.action == other.action
                and self.button == other.button)


class DialogGuard:
    def __init__(self, rules=None, rules_path=_RULES_PATH):
        self.rules = rules if rules is not None else self._load(rules_path)
        self.loc = self.rules.get('localizations', {})
        self.never_click_keys = self.rules.get('never_click_keys', [])
        self.never_click_literals = self.rules.get('never_click_literals', [])
        # Friendly, actionable message attached when a dialog matches NO rule.
        self.generic_user_message = self.rules.get('generic_user_message', '')

    @staticmethod
    def _load(path):
        if yaml is None:
            raise RuntimeError('PyYAML required to load dialog_rules.yaml')
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f)

    # — localization helpers —
    def _loc(self, key, locale):
        """Localized string for a .strings key; falls back to English, then the
        key literal."""
        row = self.loc.get(key, {})
        return row.get(locale) or row.get('en') or key

    def _never_click_set(self):
        """All button labels we must never click — resolved across ALL locales
        (defense-in-depth: a never-click button is blocked regardless of which
        language the live UI happens to be in)."""
        out = set()
        for key in self.never_click_keys:
            row = self.loc.get(key, {})
            for v in row.values():
                out.add(_normalize(v))
        for lit in self.never_click_literals:
            out.add(_normalize(lit))
        return out

    def _resolve_click(self, rule, locale, buttons_norm, never_norm):
        """Pick the first click_key whose localized label is present in the
        dialog's buttons and is not a never-click. Returns the ORIGINAL (un-
        normalized) button label to click, or None."""
        for key in rule.get('click_keys', []):
            label = self._loc(key, locale)
            label_norm = _normalize(label)
            if label_norm in never_norm:
                continue
            if label_norm in buttons_norm:
                return buttons_norm[label_norm]
        return None

    # — gate for the C2 Replace rule —
    @staticmethod
    def _gate_replace(context):
        """G1 ∧ G2 ∧ G3 — the only conditions under which the destructive Replace
        may be auto-clicked (catalog §C2). All three must hold."""
        ctx = context or {}
        expected = ctx.get('expected_dest_root')
        actual = ctx.get('actual_dest_root')
        collider = ctx.get('colliding_filename') or ''
        g1 = bool(expected) and bool(actual) and \
            os.path.normpath(actual) == os.path.normpath(expected)
        g2 = collider.lower().endswith('.wav')
        g3 = ctx.get('pass_number') == 1
        return g1 and g2 and g3, {'G1': g1, 'G2': g2, 'G3': g3}

    # — the decision —
    def decide(self, dialog, locale='en', context=None):
        """dialog = {'title':str, 'body':str, 'buttons':[str,...]} as read live.
        Returns a Decision."""
        body = (dialog or {}).get('body', '') or ''
        title = (dialog or {}).get('title', '') or ''
        buttons = list((dialog or {}).get('buttons', []) or [])

        # Truly empty (no body, no buttons) → nothing to act on.
        if not _normalize(body) and not _normalize(title) and not buttons:
            return Decision(Decision.IGNORE, reason='no body/title/buttons')

        haystack = _normalize(f'{title} {body}')
        buttons_norm = {_normalize(b): b for b in buttons}
        never_norm = self._never_click_set()

        # Evaluate rules in risk-priority order (pause/fail/gated before safe).
        ordered = sorted(self.rules.get('rules', []),
                         key=lambda r: _ACTION_PRIORITY.get(r.get('action'), 99))
        for rule in ordered:
            anchors = [self._loc(k, locale) for k in rule.get('body_keys', [])]
            # Also try the English anchor as a fallback (locale-detection safety).
            anchors += [self._loc(k, 'en') for k in rule.get('body_keys', [])]
            if not any(_body_matches(a, haystack) for a in anchors):
                continue

            action = rule.get('action')
            rid = rule.get('id')
            # Resolved friendly message for this rule (fall back to the generic one).
            umsg = rule.get('user_message') or self.generic_user_message

            if action == 'pause_notify':
                return Decision(Decision.PAUSE, rule_id=rid,
                                reason='rule=pause_notify', user_message=umsg)

            if action == 'fail_job':
                btn = self._resolve_click(rule, locale, buttons_norm, never_norm)
                if btn is None:
                    return Decision(Decision.PAUSE, rule_id=rid,
                                    reason='fail_job but no safe OK button present',
                                    user_message=umsg)
                return Decision(Decision.CLICK, button=btn, rule_id=rid,
                                reason='fail_job → dismiss then fail', terminal=True,
                                user_message=umsg)

            if action == 'dismiss_gated':
                ok, detail = self._gate_replace(context)
                if not ok:
                    return Decision(Decision.PAUSE, rule_id=rid,
                                    reason=f'gate failed {detail}', user_message=umsg)
                btn = self._resolve_click(rule, locale, buttons_norm, never_norm)
                if btn is None:
                    return Decision(Decision.PAUSE, rule_id=rid,
                                    reason='gate passed but Replace not clickable',
                                    user_message=umsg)
                return Decision(Decision.CLICK, button=btn, rule_id=rid,
                                reason=f'gated Replace {detail}', user_message=umsg)

            if action == 'dismiss_safe':
                btn = self._resolve_click(rule, locale, buttons_norm, never_norm)
                if btn is None:
                    return Decision(Decision.PAUSE, rule_id=rid,
                                    reason='no safe clickable button present',
                                    user_message=umsg)
                return Decision(Decision.CLICK, button=btn, rule_id=rid,
                                reason='dismiss_safe', user_message=umsg)

            if action == 'ignore':
                return Decision(Decision.IGNORE, rule_id=rid, reason='rule=ignore',
                                user_message=umsg)

        # FAIL-SAFE: recognized as a dialog, but no rule matched → pause + generic msg.
        return Decision(Decision.PAUSE, reason='no rule matched (fail-safe)',
                        user_message=self.generic_user_message)


def load_guard(rules_path=_RULES_PATH):
    return DialogGuard(rules_path=rules_path)
