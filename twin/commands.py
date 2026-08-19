"""Editing, as commands rather than mutations.

WHY COMMANDS. Three requirements in the brief converge on this shape:
undo/redo with named versions, an AI assistant that must produce
"deterministic editable actions" rather than pictures, and a rule that
the assistant "never directly modifies database records without
validation". All three are satisfied by making every change a small
validated object that can be applied, listed, replayed and reversed.

So "drag the rear wall out 4 metres" becomes ExtendCommand(block=…,
edge="rear", depth=4.0, storeys=1) whether it came from a mouse, a
typed number or a sentence. The geometry engine has exactly one door.

UNDO IS BY REPLAY, NOT BY INVERSE. Every command is deterministic and
the history is the record, so undo rebuilds from the base model and
re-applies n-1 commands. Inverse operations are where undo bugs live —
a wall moved then deleted has no inverse that restores it correctly —
and replay has none of that at the cost of a few milliseconds.

REFUSALS ARE PART OF THE CONTRACT. A command that would make an
impossible building (an extension wider than the house it hangs off, a
negative depth, a storey on top of nothing) is refused with a reason a
person can act on, and the model is untouched.
"""
from __future__ import annotations

import copy
import math
import uuid
from typing import List, Optional

from .model import (Block, Building, Opening, CLASS_USER, MIN_WALL_M,
                    rect_ring)


class CommandError(ValueError):
    """Refused. The message goes to the user, so it must be actionable."""


# ------------------------------------------------------------ commands
class Command:
    kind = "abstract"
    #: commands that create something need a STABLE identifier
    mints_id = None

    def __init__(self, **kw):
        self.params = kw
        self.label = kw.pop("label", None) or self.kind
        # IDS ARE MINTED ONCE, HERE — not inside apply(). Undo replays the
        # history from the base model, so an id generated per-apply came
        # back different after every undo/redo round trip: the same
        # geometry with a new name, which breaks any selection or opening
        # that referenced it. Determinism is a requirement, not a nicety.
        if self.mints_id and not self.params.get("id"):
            self.params["id"] = f"{self.mints_id}-{uuid.uuid4().hex[:6]}"

    def apply(self, bld: Building):
        raise NotImplementedError

    def as_dict(self):
        return {"kind": self.kind, "label": self.label, "params": self.params}


class Extend(Command):
    """Push a wall outward and make the new volume a block.

    The flagship edit. `edge` is which wall of which block moves, `depth`
    is how far in metres, `storeys` how many floors the new part has.
    """
    kind = "extend"
    mints_id = "ext"

    def apply(self, bld):
        p = self.params
        blk = bld.block(p.get("block_id") or "existing")
        if blk is None:
            raise CommandError(f"no block {p.get('block_id')!r} to extend")
        edge = p.get("edge", "rear")
        if edge not in ("front", "rear", "left", "right"):
            raise CommandError("edge must be front, rear, left or right")
        depth = float(p.get("depth_m", 0))
        if depth <= 0:
            raise CommandError("an extension needs a positive depth")
        if depth > 30:
            raise CommandError(
                f"{depth:g} m is not an extension, it is a second house — "
                f"add it as its own block if that is the intent")
        storeys = int(p.get("storeys", 1))
        if not 1 <= storeys <= blk.storeys + 1:
            raise CommandError(
                f"{storeys} storeys against a {blk.storeys}-storey wall: an "
                f"extension can rise at most one storey above what it "
                f"attaches to")
        # Width along the wall: full by default, or a stated span.
        along = blk.width if edge in ("front", "rear") else blk.depth
        width = float(p.get("width_m") or along)
        if width <= 0 or width > along + 1e-6:
            raise CommandError(
                f"an extension on the {edge} wall can be at most "
                f"{along:.2f} m wide; {width:g} m was asked for")
        offset = float(p.get("offset_m", 0.0))
        if offset < -1e-6 or offset + width > along + 1e-6:
            raise CommandError(
                f"the extension runs off the end of the {edge} wall")

        if edge == "rear":
            x, y, w, d = blk.x + offset, blk.y + blk.depth, width, depth
        elif edge == "front":
            x, y, w, d = blk.x + offset, blk.y - depth, width, depth
        elif edge == "right":
            x, y, w, d = blk.x + blk.width, blk.y + offset, depth, width
        else:
            x, y, w, d = blk.x - depth, blk.y + offset, depth, width

        new = Block(
            id=p.get("id") or f"ext-{uuid.uuid4().hex[:6]}",
            name=p.get("name") or f"{edge.title()} extension",
            x=round(x, 3), y=round(y, 3),
            width=round(w, 3), depth=round(d, 3),
            storeys=storeys, base_level=0,
            storey_height=blk.storey_height,
            classification=CLASS_USER,
            roof=dict(p.get("roof") or (
                {"kind": "monopitch", "pitch_deg": 15.0, "overhang": 0.3,
                 "ridge_along": "x" if edge in ("front", "rear") else "y",
                 "high_side": "max" if edge == "front" else "min"}
                if storeys < blk.storeys else
                {"kind": "gabled", "pitch_deg": 30.0, "overhang": 0.3,
                 "ridge_along": "x" if edge in ("front", "rear") else "y"})),
            note=f"{depth:g} m {storeys}-storey extension on the {edge} wall")
        bld.blocks.append(new)
        return bld


class MoveWall(Command):
    """Drag one wall of a block. The direct-manipulation primitive."""
    kind = "move_wall"

    def apply(self, bld):
        p = self.params
        blk = bld.block(p["block_id"])
        if blk is None:
            raise CommandError(f"no block {p['block_id']!r}")
        edge = p["edge"]
        by = float(p["by_m"])          # positive = outward
        if edge == "rear":
            blk.depth += by
        elif edge == "front":
            blk.y -= by
            blk.depth += by
        elif edge == "right":
            blk.width += by
        elif edge == "left":
            blk.x -= by
            blk.width += by
        else:
            raise CommandError("edge must be front, rear, left or right")
        if blk.width < MIN_WALL_M or blk.depth < MIN_WALL_M:
            raise CommandError(
                f"that would leave the block {blk.width:.2f} x "
                f"{blk.depth:.2f} m — nothing smaller than "
                f"{MIN_WALL_M} m is a room")
        blk.x, blk.y = round(blk.x, 3), round(blk.y, 3)
        blk.width, blk.depth = round(blk.width, 3), round(blk.depth, 3)
        if blk.classification != CLASS_USER:
            blk.note = (blk.note + " " if blk.note else "") + \
                "edited by the user after import"
            blk.classification = CLASS_USER
        return bld


class SetStoreys(Command):
    kind = "set_storeys"

    def apply(self, bld):
        blk = bld.block(self.params["block_id"])
        if blk is None:
            raise CommandError(f"no block {self.params['block_id']!r}")
        n = int(self.params["storeys"])
        if not 1 <= n <= 6:
            raise CommandError("storeys must be between 1 and 6")
        blk.storeys = n
        blk.classification = CLASS_USER
        return bld


class SetRoof(Command):
    kind = "set_roof"

    def apply(self, bld):
        blk = bld.block(self.params["block_id"])
        if blk is None:
            raise CommandError(f"no block {self.params['block_id']!r}")
        kind = self.params.get("kind", "gabled")
        if kind not in ("gabled", "hipped", "monopitch", "flat"):
            raise CommandError(
                "roof must be gabled, hipped, monopitch or flat")
        pitch = float(self.params.get("pitch_deg", 30.0))
        if kind != "flat" and not 5 <= pitch <= 70:
            raise CommandError(
                f"a {pitch:g} degree pitch is outside anything built — "
                f"UK tiled roofs run about 12 to 60 degrees")
        roof = dict(blk.roof or {})
        roof.update(kind=kind, pitch_deg=pitch,
                    classification=CLASS_USER)
        if kind == "monopitch":
            roof.setdefault("high_side", self.params.get("high_side", "min"))
            roof.setdefault("ridge_along", self.params.get("ridge_along", "y"))
        blk.roof = roof
        return bld


class AddOpening(Command):
    kind = "add_opening"
    mints_id = "op"

    def apply(self, bld):
        p = self.params
        blk = bld.block(p["block_id"])
        if blk is None:
            raise CommandError(f"no block {p['block_id']!r}")
        edge = p.get("edge", "rear")
        span = blk.width if edge in ("front", "rear") else blk.depth
        w = float(p.get("width_m", 1.2))
        along = float(p.get("along_m", max(0.0, (span - w) / 2)))
        if w <= 0:
            raise CommandError("an opening needs a positive width")
        if along < 0 or along + w > span + 1e-6:
            raise CommandError(
                f"an opening {w:g} m wide at {along:g} m runs past the end "
                f"of a {span:.2f} m wall")
        lvl = int(p.get("level", 0))
        if not 0 <= lvl < blk.storeys:
            raise CommandError(
                f"level {lvl} does not exist on a {blk.storeys}-storey block")
        bld.openings.append(Opening(
            id=p.get("id") or f"op-{uuid.uuid4().hex[:6]}",
            block_id=blk.id, edge=edge, kind=p.get("kind", "window"),
            along_m=round(along, 3), width=round(w, 3),
            height=float(p.get("height_m", 1.2)),
            sill=float(p.get("sill_m", 0.9)), level=lvl))
        return bld


class RemoveBlock(Command):
    kind = "remove_block"

    def apply(self, bld):
        bid = self.params["block_id"]
        if bid == "existing":
            raise CommandError(
                "the existing building cannot be deleted — this is a twin "
                "of a real house, not a blank canvas")
        n = len(bld.blocks)
        bld.blocks = [b for b in bld.blocks if b.id != bid]
        if len(bld.blocks) == n:
            raise CommandError(f"no block {bid!r} to remove")
        bld.openings = [o for o in bld.openings if o.block_id != bid]
        return bld


REGISTRY = {c.kind: c for c in (Extend, MoveWall, SetStoreys, SetRoof,
                                AddOpening, RemoveBlock)}


def make(command_kind, **params):
    # NOT `kind`: SetRoof takes a `kind` of its own (gabled/hipped/...),
    # and sharing the name made make("set_roof", kind="hipped") raise
    # "multiple values for argument 'kind'" — the command was
    # unreachable from both the API and the language parser.
    cls = REGISTRY.get(command_kind)
    if cls is None:
        raise CommandError(
            f"unknown command {command_kind!r}; "
            f"known: {', '.join(sorted(REGISTRY))}")
    return cls(**params)


# ------------------------------------------------------------- history
class Project:
    """A building plus the edits made to it, undoable and replayable."""

    def __init__(self, base: Building):
        self._base = copy.deepcopy(base)
        self.commands: List[Command] = []
        self.redo_stack: List[Command] = []
        self.checkpoints = []          # (index, name)
        self._cache = None

    @property
    def id(self):
        return self._base.id

    def current(self) -> Building:
        if self._cache is None:
            bld = copy.deepcopy(self._base)
            for c in self.commands:
                bld = c.apply(bld)
            self._cache = bld
        return self._cache

    def apply(self, cmd: Command) -> Building:
        # Validate against a COPY: a command that fails half way must not
        # leave a half-edited building behind.
        trial = copy.deepcopy(self.current())
        cmd.apply(trial)                       # raises CommandError
        self.commands.append(cmd)
        self.redo_stack.clear()
        self._cache = trial
        return trial

    def undo(self):
        if not self.commands:
            raise CommandError("nothing to undo")
        self.redo_stack.append(self.commands.pop())
        self._cache = None
        return self.current()

    def redo(self):
        if not self.redo_stack:
            raise CommandError("nothing to redo")
        self.commands.append(self.redo_stack.pop())
        self._cache = None
        return self.current()

    def checkpoint(self, name):
        self.checkpoints.append({"at": len(self.commands), "name": name})
        return self.checkpoints[-1]

    def restore(self, index):
        """Rewind to a point in the history. Redo still works forward."""
        if not 0 <= index <= len(self.commands):
            raise CommandError(f"no version {index}")
        while len(self.commands) > index:
            self.redo_stack.append(self.commands.pop())
        self._cache = None
        return self.current()

    def history(self):
        return {
            "applied": [c.as_dict() for c in self.commands],
            "can_undo": bool(self.commands),
            "can_redo": bool(self.redo_stack),
            "checkpoints": self.checkpoints,
            "version": len(self.commands),
        }

    def baseline(self) -> Building:
        """The building as found — for before/after comparison."""
        return copy.deepcopy(self._base)


# ------------------------------------------------ natural language
def parse_instruction(text: str, bld: Building):
    """Turn a sentence into a COMMAND, or refuse it. No pictures.

    Deliberately a small deterministic parser rather than a model call:
    the brief requires that an instruction becomes a structured,
    validated, editable action, and a parser that either produces one or
    says it did not understand is auditable in a way a generated blob is
    not. A language model can sit in FRONT of this and emit the same
    command dicts; the geometry engine still has one door.
    """
    t = " ".join((text or "").lower().split())
    if not t:
        raise CommandError("say what you would like to change")

    def number(default=None, after=None):
        import re
        pat = r"(\d+(?:\.\d+)?)\s*(?:m\b|metre|meter)" if after is None else after
        m = re.search(pat, t)
        return float(m.group(1)) if m else default

    edge = ("rear" if any(w in t for w in ("rear", "back", "behind")) else
            "front" if "front" in t else
            "left" if "left" in t else
            "right" if "right" in t else None)

    if any(w in t for w in ("extend", "extension", "add on")):
        depth = number()
        if depth is None:
            raise CommandError(
                "how deep should the extension be? e.g. "
                "'add a 4 m rear extension'")
        storeys = 2 if any(w in t for w in ("two storey", "two-storey",
                                            "double storey", "double-storey")
                           ) else 1
        return make("extend", block_id="existing", edge=edge or "rear",
                    depth_m=depth, storeys=storeys,
                    label=f"{depth:g} m {edge or 'rear'} extension")

    if "storey" in t or "floor" in t:
        import re
        m = re.search(r"(\d+)\s*(?:storey|floor)", t)
        words = {"one": 1, "two": 2, "three": 3, "four": 4}
        n = int(m.group(1)) if m else next(
            (v for k, v in words.items() if k in t), None)
        if n:
            return make("set_storeys", block_id="existing", storeys=n,
                        label=f"{n} storeys")

    if "roof" in t:
        kind = ("hipped" if "hip" in t else "gabled" if "gable" in t
                else "monopitch" if ("mono" in t or "lean" in t)
                else "flat" if "flat" in t else None)
        pitch = number(after=r"(\d+(?:\.\d+)?)\s*(?:deg|degree)")
        if kind or pitch:
            return make("set_roof", block_id="existing",
                        kind=kind or "gabled",
                        pitch_deg=pitch or 30.0,
                        label=f"{kind or 'gabled'} roof"
                              + (f" at {pitch:g}" if pitch else ""))

    if any(w in t for w in ("window", "door", "bifold", "patio")):
        kind = ("bifold" if "bifold" in t else
                "door" if ("door" in t or "patio" in t) else "window")
        return make("add_opening", block_id=(bld.blocks[-1].id
                                             if bld.blocks else "existing"),
                    edge=edge or "rear", kind=kind,
                    width_m=number(default=2.4 if kind != "window" else 1.2),
                    height_m=2.1 if kind != "window" else 1.2,
                    sill_m=0.0 if kind != "window" else 0.9,
                    label=f"add {kind}")

    raise CommandError(
        f"I did not understand {text!r}. Try: 'add a 4 m rear extension', "
        f"'make it two storeys', 'change the roof to a hip roof at 35 "
        f"degrees', or 'add bifold doors to the rear'.")
