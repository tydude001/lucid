"""A channel preset pack: one external JSON file, loaded and snapshotted.

PLAN.md § The completion queue, item 8. The design this module exists to
correct: lucid had no loader at all for this. `captions.PRESETS` and
`graphics.TEMPLATES`/`PALETTE`/`FONTS` are closed literal dicts, and platform
safe zones had no code anywhere — "what is left is the pack itself, which is
goodsometimes' side" (PLAN.md) was false the moment it was written.

**A pack is applied once, and what gets kept is not the file.** `load_pack`
resolves every declared variant — a shallow `extends`-style merge of each
named variant onto a required `default` — and the *fully resolved* payload is
what `ops.pack_apply` snapshots into the manifest and hashes. Every later op
(`pack_activate`, `card_new`'s style pre-merge, `card_safe_zones`) reads that
snapshot, never the file again, so no op ever depends on an external path
staying reachable or unchanged after the moment it was applied. This is why
the module is pure: no filesystem write, no project, no subprocess — those
live in `ops.py`, which is the only caller that touches a `Project`.

Two token forms, `$palette.<slot>` and `$fonts.<role>`, may appear as a whole
string value anywhere inside a variant's resolved sections (a caption
preset's `outline_colour`, say). They are substituted from that *same*
variant's own resolved `palette`/`fonts`, after the extends-merge — which is
what makes the October variant's caption presets follow its pumpkin amber
without restating the hex code a second time.

Refuses loudly rather than guessing, on every one of: an unrecognised format
version; an unknown top-level or per-variant key; a missing or malformed
`palette`/`fonts`/`mark` section; a palette entry that is not a hex colour; a
font role whose stack does not end in a CSS generic (`serif`, `sans-serif`,
…) — a stack with nowhere to fall back to is the exact failure this repo has
already shipped once, silently, per `fonts.py`'s own docstring; a caption
preset naming an unknown base preset or an unknown `caption_style` field; and
a `$palette.`/`$fonts.` token naming a slot the variant does not resolve.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from lucid import captions, graphics

#: The only format version this build understands. Bumped only if the shape
#: below changes in a way an older loader could not read safely — additive
#: sections do not need it, the same discipline `project.SCHEMA_VERSION`
#: reserves for a real break rather than for growth.
FORMAT_VERSION = 1

_ROOT_KEYS = frozenset({"name", "format", "variants", "fonts_dir"})
_VARIANT_SECTIONS = frozenset(
    {"palette", "fonts", "weights", "mark", "safe_zones", "caption_presets"}
)
_REQUIRED_DEFAULT_SECTIONS = frozenset({"palette", "fonts", "mark"})
_MARK_KEYS = frozenset({"wordmark", "compact", "footnote"})
_HEX = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_TOKEN = re.compile(r"^\$(palette|fonts)\.([A-Za-z0-9_]+)$")

#: The `caption_style` kwargs a caption preset entry may set — exactly the
#: fields `captions.normalise` already knows, so a typo is refused here
#: rather than accepted and then ignored by `ops.caption_style`.
CAPTION_STYLE_FIELDS = frozenset(captions.STYLE_FIELDS)


class PackError(RuntimeError):
    """A pack file does not resolve to something lucid can apply."""


def _require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PackError(f"{where} must be a JSON object, not {type(value).__name__}")
    return value


def _validate_palette(palette: dict[str, Any], where: str) -> dict[str, str]:
    unknown = sorted(set(palette) - set(graphics.PALETTE))
    if unknown:
        raise PackError(
            f"{where} names palette slot(s) lucid has no card slot for: {unknown} "
            f"— known slots: {sorted(graphics.PALETTE)}"
        )
    out: dict[str, str] = {}
    for slot, value in palette.items():
        if not isinstance(value, str) or not _HEX.match(value):
            raise PackError(
                f"{where}.palette.{slot} is {value!r}, not a #rrggbb (or #rrggbbaa) colour"
            )
        out[slot] = value
    return out


def _validate_fonts(fonts: dict[str, Any], where: str) -> dict[str, str]:
    unknown = sorted(set(fonts) - set(graphics.FONTS))
    if unknown:
        raise PackError(
            f"{where} names font role(s) lucid has no card slot for: {unknown} "
            f"— known roles: {sorted(graphics.FONTS)}"
        )
    out: dict[str, str] = {}
    for role, stack in fonts.items():
        if not isinstance(stack, str) or not stack.strip():
            raise PackError(f"{where}.fonts.{role} must be a non-empty CSS font-family stack")
        families = [p.strip().strip("'\"") for p in stack.split(",") if p.strip()]
        if len(families) < 2 or families[-1].lower() not in graphics.GENERIC_FAMILIES:
            raise PackError(
                f"{where}.fonts.{role} = {stack!r} has no fallback stack — it must "
                "end in a CSS generic (serif, sans-serif, …) the way lucid's own "
                f"{graphics.FONTS['title_font']!r} does, or a face this box lacks "
                "renders pixel-identically to one it has and nothing says so"
            )
        out[role] = stack
    return out


def _validate_weights(weights: dict[str, Any], where: str) -> dict[str, int]:
    unknown = sorted(set(weights) - set(graphics.WEIGHTS))
    if unknown:
        raise PackError(
            f"{where} names weight role(s) lucid has no card slot for: {unknown} "
            f"— known roles: {sorted(graphics.WEIGHTS)}"
        )
    out: dict[str, int] = {}
    for role, value in weights.items():
        try:
            out[role] = int(value)
        except (TypeError, ValueError):
            raise PackError(f"{where}.weights.{role} must be an integer weight") from None
    return out


def _validate_mark(mark: dict[str, Any], where: str) -> dict[str, str]:
    unknown = sorted(set(mark) - _MARK_KEYS)
    if unknown:
        raise PackError(f"{where}.mark names unknown key(s) {unknown} — has: {sorted(_MARK_KEYS)}")
    out: dict[str, str] = {}
    for key, value in mark.items():
        if not isinstance(value, str) or not value.strip():
            raise PackError(f"{where}.mark.{key} must be a non-empty string")
        out[key] = value
    return out


def _validate_safe_zones(zones: dict[str, Any], where: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for platform, zone in zones.items():
        zone = _require_dict(zone, f"{where}.safe_zones.{platform}")
        try:
            bottom_px = float(zone["bottom_px"])
        except (KeyError, TypeError, ValueError):
            raise PackError(
                f"{where}.safe_zones.{platform} needs a numeric 'bottom_px'"
            ) from None
        rail = zone.get("action_rail")
        rail_out = None
        if rail is not None:
            rail = _require_dict(rail, f"{where}.safe_zones.{platform}.action_rail")
            try:
                rail_out = {
                    "width": float(rail["width"]),
                    "side": str(rail.get("side", "right")),
                    "rail_below_ratio": float(rail.get("rail_below_ratio", 0.5)),
                }
            except (KeyError, TypeError, ValueError):
                raise PackError(
                    f"{where}.safe_zones.{platform}.action_rail needs a numeric 'width'"
                ) from None
        out[platform] = {"bottom_px": bottom_px, **({"action_rail": rail_out} if rail_out else {})}
    return out


def _validate_caption_presets(presets: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, fields in presets.items():
        fields = _require_dict(fields, f"{where}.caption_presets.{name}")
        unknown = sorted(set(fields) - CAPTION_STYLE_FIELDS)
        if unknown:
            raise PackError(
                f"{where}.caption_presets.{name} names unknown caption_style field(s) "
                f"{unknown} — settable: {sorted(CAPTION_STYLE_FIELDS)}"
            )
        if "preset" in fields:
            try:
                captions.preset(str(fields["preset"]))
            except captions.CaptionError as exc:
                raise PackError(
                    f"{where}.caption_presets.{name} names an unknown base preset "
                    f"{fields['preset']!r}: {exc}"
                ) from None
        out[name] = dict(fields)
    return out


_VALIDATORS = {
    "palette": _validate_palette,
    "fonts": _validate_fonts,
    "weights": _validate_weights,
    "mark": _validate_mark,
    "safe_zones": _validate_safe_zones,
    "caption_presets": _validate_caption_presets,
}


def _merge_section(section: str, base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`base` with `over` folded on top, one level deep.

    `caption_presets` merges per preset *name* rather than replacing the whole
    section, so a variant can restate one field of one preset without having
    to copy every other field or every other preset along with it — the same
    "only the fields overridden" discipline `ops.caption_style` itself keeps.
    """
    if section != "caption_presets":
        return {**base, **over}
    merged = {name: dict(fields) for name, fields in base.items()}
    for name, fields in over.items():
        merged[name] = {**merged.get(name, {}), **fields}
    return merged


def _resolve_tokens(value: Any, palette: dict[str, str], fonts: dict[str, str], where: str) -> Any:
    if isinstance(value, str):
        match = _TOKEN.match(value)
        if not match:
            return value
        kind, key = match.groups()
        table = palette if kind == "palette" else fonts
        if key not in table:
            raise PackError(
                f"{where} names ${kind}.{key}, which this variant does not resolve "
                f"(has: {sorted(table)})"
            )
        return table[key]
    if isinstance(value, dict):
        return {k: _resolve_tokens(v, palette, fonts, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_tokens(v, palette, fonts, where) for v in value]
    return value


def load_pack(pack_path: Path | str) -> dict[str, Any]:
    """Read, validate and fully resolve every variant `pack_path` declares.

    Returns `{"name", "format", "variants": {variant: resolved_payload}}`,
    where a resolved payload is `{"palette", "fonts", "weights", "mark",
    "safe_zones", "caption_presets"}` with every `$palette.`/`$fonts.` token
    substituted and nothing left to look up later. `ops.pack_apply` is the
    only thing that persists this; a second call here re-derives it fresh.
    """
    source = Path(pack_path)
    try:
        raw_text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackError(f"could not read pack file {source}: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PackError(f"{source} is not valid JSON: {exc}") from exc
    raw = _require_dict(raw, str(source))

    unknown_root = sorted(set(raw) - _ROOT_KEYS)
    if unknown_root:
        raise PackError(f"{source} has unknown top-level key(s) {unknown_root} — has: {sorted(_ROOT_KEYS)}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PackError(f"{source} needs a non-empty 'name'")

    fmt = raw.get("format")
    if fmt != FORMAT_VERSION:
        raise PackError(
            f"{source} declares format {fmt!r}, and this lucid understands "
            f"only {FORMAT_VERSION} — a pack from a newer lucid needs a newer one to load it"
        )

    variants = _require_dict(raw.get("variants"), f"{source}.variants")
    if "default" not in variants:
        raise PackError(f"{source}.variants has no 'default' — every other variant merges onto it")

    raw_variants: dict[str, dict[str, Any]] = {}
    for vname, vbody in variants.items():
        vbody = _require_dict(vbody, f"{source}.variants.{vname}")
        unknown = sorted(set(vbody) - _VARIANT_SECTIONS)
        if unknown:
            raise PackError(
                f"{source}.variants.{vname} has unknown key(s) {unknown} — has: "
                f"{sorted(_VARIANT_SECTIONS)}"
            )
        raw_variants[vname] = vbody

    default_raw = raw_variants["default"]
    missing = sorted(_REQUIRED_DEFAULT_SECTIONS - set(default_raw))
    if missing:
        raise PackError(f"{source}.variants.default is missing {missing}")

    resolved: dict[str, dict[str, Any]] = {}
    for vname, vbody in raw_variants.items():
        where = f"{source}.variants.{vname}"
        merged_raw = {
            section: vbody.get(section, {})
            if vname == "default"
            else _merge_section(section, default_raw.get(section, {}), vbody.get(section, {}))
            for section in _VARIANT_SECTIONS
        }
        payload = {
            section: _VALIDATORS[section](merged_raw[section], where) for section in _VARIANT_SECTIONS
        }
        palette, fonts = payload["palette"], payload["fonts"]
        payload = {
            section: _resolve_tokens(value, palette, fonts, f"{where}.{section}")
            for section, value in payload.items()
        }
        resolved[vname] = payload

    return {"name": name, "format": fmt, "variants": resolved}


def pack_hash(resolved_variant: dict[str, Any]) -> str:
    """sha256 of a resolved variant's own content, never the file's bytes.

    Hashing `json.dumps(sort_keys=True)` of the *resolved* payload rather
    than the raw file means a whitespace reformat, a key reorder, or an
    unrelated variant changing upstream cannot trigger a spurious
    `pack_status` staleness report for a card that would render identically.
    """
    encoded = json.dumps(resolved_variant, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
