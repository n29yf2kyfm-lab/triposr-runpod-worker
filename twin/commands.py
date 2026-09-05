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

from .model import (Block, Building, MIN_ROOM_AREA_M2, MIN_ROOM_M,
                    MIN_WALL_M, Opening, ROOM_KINDS, Room, CLASS_USER,
                    auto_layout, rect_ring, room_block_overlap,
                    room_inside_building)


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
            id=p["id"],
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
        if edge not in ("front", "rear", "left", "right"):
            raise CommandError("edge must be front, rear, left or right")

        # THE ROOMS ON THAT WALL MOVE WITH IT. Rooms are absolute
        # rectangles; resizing only the block left the kitchen hanging
        # 2 m outside a shrunk house — while MovePartition's refusal
        # message promised "move the block's wall instead, and the rooms
        # follow". A room whose edge lies ON the old wall line stretches
        # with it; a room the wall would be dragged THROUGH refuses the
        # drag instead of being quietly crushed.
        wall = {"rear": blk.y + blk.depth, "front": blk.y,
                "right": blk.x + blk.width, "left": blk.x}[edge]
        followers = []
        for r in bld.rooms:
            if not any(b.base_level <= r.level < b.base_level + b.storeys
                       and room_block_overlap(r, b) > 1e-9
                       for b in (blk,)):
                continue
            r_edge = {"rear": r.y + r.depth, "front": r.y,
                      "right": r.x + r.width, "left": r.x}[edge]
            if abs(r_edge - wall) < 1e-6:
                followers.append(r)

        if edge == "rear":
            blk.depth += by
        elif edge == "front":
            blk.y -= by
            blk.depth += by
        elif edge == "right":
            blk.width += by
        else:
            blk.x -= by
            blk.width += by
        if blk.width < MIN_WALL_M or blk.depth < MIN_WALL_M:
            raise CommandError(
                f"that would leave the block {blk.width:.2f} x "
                f"{blk.depth:.2f} m — nothing smaller than "
                f"{MIN_WALL_M} m is a room")

        for r in followers:
            if edge == "rear":
                r.depth += by
            elif edge == "front":
                r.y -= by
                r.depth += by
            elif edge == "right":
                r.width += by
            else:
                r.x -= by
                r.width += by
            if (r.width < MIN_ROOM_M - 1e-9 or r.depth < MIN_ROOM_M - 1e-9
                    or r.area() < MIN_ROOM_AREA_M2 - 1e-9):
                raise CommandError(
                    f"that would leave {r.name} at {r.width:.2f} x "
                    f"{r.depth:.2f} m — too small to be a room. Move or "
                    f"remove it first")
            r.x, r.y = round(r.x, 3), round(r.y, 3)
            r.width, r.depth = round(r.width, 3), round(r.depth, 3)

        # An inward drag past a room that does NOT touch the wall would
        # cut through it. Refuse rather than leave a room in the air.
        if by < 0:
            for r in bld.rooms:
                if r in followers:
                    continue
                if (blk.base_level <= r.level
                        < blk.base_level + blk.storeys
                        and not room_inside_building(bld, r)):
                    raise CommandError(
                        f"pulling that wall in would cut through "
                        f"{r.name} — move or remove the room first")

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


class AutoLayout(Command):
    """Lay standard rooms into a block, so the regs gate has something."""
    kind = "auto_layout"
    #: not an id for anything this command creates — a SEED, so that the
    #: rooms it lays out are named the same on every replay. See
    #: model.auto_layout.
    mints_id = "lay"

    def apply(self, bld):
        p = self.params
        seq = 0
        # No block and no level named means the whole building: that is
        # what "lay out the rooms" means to a person, and laying out one
        # level of one block leaves the rest as solid lumps that the
        # regulations gate then reports as inner rooms.
        bids = ([p["block_id"]] if p.get("block_id")
                else [b.id for b in bld.blocks])
        levels = ([int(p["level"])] if p.get("level") is not None
                  else None)
        made_any = False
        for bid in bids:
            blk = bld.block(bid)
            if blk is None:
                raise CommandError(f"no block {bid!r}")
            want = (levels if levels is not None
                    else list(range(blk.base_level,
                                    blk.base_level + blk.storeys)))
            for level in want:
                if not (blk.base_level <= level
                        < blk.base_level + blk.storeys):
                    continue
                try:
                    made = auto_layout(bld, bid, level,
                                       id_seed=p["id"].split("-", 1)[-1],
                                       id_start=seq)
                except ValueError as e:
                    raise CommandError(str(e))
                seq += len(made)
                bld.rooms = [r for r in bld.rooms
                             if not (r.block_id == bid and r.level == level)]
                bld.rooms.extend(made)
                made_any = True
        if not made_any:
            raise CommandError("nothing to lay out on that level")
        return bld


class AddRoom(Command):
    kind = "add_room"
    mints_id = "rm"

    def apply(self, bld):
        p = self.params
        blk = bld.block(p.get("block_id") or "existing")
        if blk is None:
            raise CommandError(f"no block {p.get('block_id')!r}")
        kind = p.get("room_kind", "room")
        if kind not in ROOM_KINDS:
            raise CommandError(
                f"room kind must be one of {', '.join(ROOM_KINDS)}")
        w, d = float(p.get("width_m", 3.0)), float(p.get("depth_m", 3.0))
        if w < MIN_ROOM_M or d < MIN_ROOM_M:
            raise CommandError(
                f"a {w:g} x {d:g} m room is smaller than {MIN_ROOM_M} m "
                f"across — that is a cupboard, not a room")
        x = float(p.get("x", blk.x))
        y = float(p.get("y", blk.y))
        room = Room(
            id=p["id"], block_id=blk.id, level=int(p.get("level", 0)),
            name=p.get("name") or kind.title(), kind=kind,
            x=round(x, 3), y=round(y, 3),
            width=round(w, 3), depth=round(d, 3))
        if not room_inside_building(bld, room):
            raise CommandError(
                "the room does not fit inside the building on that level")
        # NO OVERLAPS. Every consumer — the coverage test, the engine,
        # the plan — assumes rooms tile without stacking; two rooms on
        # the same floor plate would double-count the take-off and let
        # the whole-block fallback vanish silently.
        for other in bld.rooms:
            if other.level != room.level:
                continue
            ox = (min(other.x + other.width, room.x + room.width)
                  - max(other.x, room.x))
            oy = (min(other.y + other.depth, room.y + room.depth)
                  - max(other.y, room.y))
            if ox > 1e-6 and oy > 1e-6:
                raise CommandError(
                    f"that would lie on top of {other.name} — rooms "
                    f"cannot overlap; move or resize {other.name} first")
        bld.rooms.append(room)
        return bld


class MovePartition(Command):
    """Drag an internal wall: the room grows, its neighbour shrinks.

    THE POINT OF DOING IT AS A PAIR. Moving one room's wall and leaving
    the next one alone opens a gap or an overlap, and a plan with a
    150 mm void between two rooms measures wrong in every direction. The
    neighbour on the far side of that wall moves with it, or the command
    is refused.
    """
    kind = "move_partition"

    def apply(self, bld):
        p = self.params
        room = bld.room(p["room_id"])
        if room is None:
            raise CommandError(f"no room {p['room_id']!r}")
        edge, by = p["edge"], float(p["by_m"])

        def bounds(r):
            return r.x, r.y, r.x + r.width, r.y + r.depth

        x0, y0, x1, y1 = bounds(room)
        line = {"front": y0, "rear": y1, "left": x0, "right": x1}[edge]
        axis = 1 if edge in ("front", "rear") else 0
        # Whoever shares that line, on the same level. GEOMETRY, not
        # block_id: a knocked-through room spans two blocks while
        # carrying one block's id, and filtering by id made its genuinely
        # internal walls invisible — the neighbour moved alone and the
        # plan opened the exact overlap this pairing exists to prevent.
        touching = []
        for other in bld.rooms:
            if other is room or other.level != room.level:
                continue
            ox0, oy0, ox1, oy1 = bounds(other)
            far = {"front": oy1, "rear": oy0, "left": ox1, "right": ox0}[edge]
            if abs(far - line) < 1e-6:
                # and they must actually overlap along the wall
                a0, a1 = (x0, x1) if axis == 1 else (y0, y1)
                b0, b1 = (ox0, ox1) if axis == 1 else (oy0, oy1)
                if min(a1, b1) - max(a0, b0) > 1e-6:
                    touching.append(other)

        # A WALL IS DRAGGED WHOLE OR NOT AT ALL. The rooms behind it move
        # bodily, so a neighbour WIDER than the room being dragged swings
        # its far end past a third room: drag a 3.35 m dining room into a
        # 5 m kitchen and the kitchen's front wall leaves the hall behind
        # it, opening exactly the void this pairing exists to close. The
        # far side must tile the moving room's wall exactly, or the drag
        # is refused and names the room to drag instead.
        if touching:
            wall_a0, wall_a1 = (x0, x1) if axis == 1 else (y0, y1)
            spans = []
            for o in touching:
                ox0, oy0, ox1, oy1 = bounds(o)
                spans.append(((ox0, ox1) if axis == 1 else (oy0, oy1), o))
            over = [o for (b0, b1), o in spans
                    if b0 < wall_a0 - 1e-6 or b1 > wall_a1 + 1e-6]
            if over:
                raise CommandError(
                    f"{over[0].name} runs past the end of that wall, so "
                    f"moving it would leave a gap beside {room.name} — "
                    f"drag {over[0].name}'s own wall instead and this "
                    f"room follows")
            reach = wall_a0
            for b0, b1 in sorted(s for s, _ in spans):
                if b0 > reach + 1e-6:
                    break
                reach = max(reach, b1)
            if reach < wall_a1 - 1e-6:
                raise CommandError(
                    f"only part of that wall of {room.name} has a room "
                    f"behind it — the rest is the outside of the "
                    f"building, so the wall cannot move as one")

        def resize(r, e, amount):
            if e == "rear":
                r.depth += amount
            elif e == "front":
                r.y -= amount
                r.depth += amount
            elif e == "right":
                r.width += amount
            else:
                r.x -= amount
                r.width += amount

        opposite = {"front": "rear", "rear": "front",
                    "left": "right", "right": "left"}[edge]
        trial = [(room, edge, by)] + [(o, opposite, -by) for o in touching]
        for r, e, amount in trial:
            resize(r, e, amount)
        bad = [r for r, _, _ in trial
               if r.width < MIN_ROOM_M or r.depth < MIN_ROOM_M
               or r.area() < MIN_ROOM_AREA_M2]
        if bad:
            for r, e, amount in trial:
                resize(r, e, -amount)
            raise CommandError(
                f"that would leave {bad[0].name} at {bad[0].width:.2f} x "
                f"{bad[0].depth:.2f} m — too small to be a room")
        if not touching:
            # No neighbour on that line, so it can only be the outside —
            # and the room may not leave the BUILDING. Not "its block":
            # a knocked-through room legitimately crosses its anchor
            # block's boundary, and testing against the anchor refused
            # a genuinely internal wall of the merged space.
            if not room_inside_building(bld, room):
                resize(room, edge, -by)
                raise CommandError(
                    "that wall is the outside of the building — move the "
                    "block's wall instead, and the rooms follow")
        for r, _, _ in trial:
            r.x, r.y = round(r.x, 3), round(r.y, 3)
            r.width, r.depth = round(r.width, 3), round(r.depth, 3)
        return bld


class SetRoom(Command):
    kind = "set_room"

    def apply(self, bld):
        p = self.params
        room = bld.room(p["room_id"])
        if room is None:
            raise CommandError(f"no room {p['room_id']!r}")
        if p.get("name"):
            room.name = str(p["name"])[:60]
        if p.get("room_kind"):
            if p["room_kind"] not in ROOM_KINDS:
                raise CommandError(
                    f"room kind must be one of {', '.join(ROOM_KINDS)}")
            room.kind = p["room_kind"]
        return bld


class RemoveRoom(Command):
    kind = "remove_room"

    def apply(self, bld):
        n = len(bld.rooms)
        bld.rooms = [r for r in bld.rooms if r.id != self.params["room_id"]]
        if len(bld.rooms) == n:
            raise CommandError(f"no room {self.params['room_id']!r}")
        return bld


class MergeRooms(Command):
    """Knock two rooms into one. The commonest job on a rear extension.

    A kitchen with an extension behind it reads to the regulations gate
    as a room inside a room — correctly, while there is still a wall
    between them. On site that wall comes out and the two become one
    space, and this is that operation: the rooms must be adjacent and
    together form a rectangle, or the result is an L-shape the model
    cannot represent and the command is refused rather than fudged.
    """
    kind = "merge_rooms"

    def apply(self, bld):
        p = self.params
        a, b = bld.room(p["room_id"]), bld.room(p["other_id"])
        if a is None or b is None:
            raise CommandError("both rooms must exist to merge them")
        if a is b:
            raise CommandError("a room cannot be merged with itself")
        if a.level != b.level:
            raise CommandError("rooms on different floors cannot be merged")
        ax0, ay0, ax1, ay1 = a.x, a.y, a.x + a.width, a.y + a.depth
        bx0, by0, bx1, by1 = b.x, b.y, b.x + b.width, b.y + b.depth
        same_x = abs(ax0 - bx0) < 1e-6 and abs(ax1 - bx1) < 1e-6
        same_y = abs(ay0 - by0) < 1e-6 and abs(ay1 - by1) < 1e-6
        touch_y = abs(ay1 - by0) < 1e-6 or abs(by1 - ay0) < 1e-6
        touch_x = abs(ax1 - bx0) < 1e-6 or abs(bx1 - ax0) < 1e-6
        if not ((same_x and touch_y) or (same_y and touch_x)):
            raise CommandError(
                f"{a.name} and {b.name} do not share a full wall, so "
                f"knocking them together would leave an L-shaped room — "
                f"which this model cannot measure. Line the walls up "
                f"first, or keep them separate.")
        a.x, a.y = round(min(ax0, bx0), 3), round(min(ay0, by0), 3)
        a.width = round(max(ax1, bx1) - a.x, 3)
        a.depth = round(max(ay1, by1) - a.y, 3)
        if p.get("name"):
            a.name = str(p["name"])[:60]
        elif a.name != b.name:
            a.name = f"{a.name}/{b.name}".replace("Kitchen/Kitchen", "Kitchen")
        # The merged space takes the more demanding kind: a kitchen that
        # swallows a dining area is still a kitchen for extract and for
        # the fire risk the gate assesses.
        rank = {"store": 0, "circulation": 1, "room": 2, "kitchen": 3,
                "wet": 3}
        if rank.get(b.kind, 0) > rank.get(a.kind, 0):
            a.kind = b.kind
        bld.rooms = [r for r in bld.rooms if r.id != b.id]
        return bld


class RemoveBlock(Command):
    kind = "remove_block"

    def apply(self, bld):
        bid = self.params["block_id"]
        if bid == "existing":
            raise CommandError(
                "the existing building cannot be deleted — this is a twin "
                "of a real house, not a blank canvas")
        gone = next((b for b in bld.blocks if b.id == bid), None)
        if gone is None:
            raise CommandError(f"no block {bid!r} to remove")
        # ROOMS GO BY GEOMETRY, NOT BY ANCHOR ID. A knocked-through room
        # spans two blocks under one block_id: deleting by id either
        # left it hanging 4 m in the open air (anchored to the block
        # that stays) or deleted the half that stands inside the house
        # (anchored to the block that goes). A room fully inside the
        # removed block goes with it; a room that STRADDLES the boundary
        # is the user's decision, so the command refuses and says which.
        for r in bld.rooms:
            if not (gone.base_level <= r.level
                    < gone.base_level + gone.storeys):
                continue
            inside = room_block_overlap(r, gone)
            if 1e-9 < inside < r.area() - 1e-9:
                raise CommandError(
                    f"{r.name} spans the wall between {gone.name} and the "
                    f"rest of the building — remove or shrink that room "
                    f"first, then remove the block")
        bld.blocks = [b for b in bld.blocks if b.id != bid]
        bld.openings = [o for o in bld.openings if o.block_id != bid]
        bld.rooms = [
            r for r in bld.rooms
            if not (gone.base_level <= r.level
                    < gone.base_level + gone.storeys
                    and room_block_overlap(r, gone) >= r.area() - 1e-9)]
        return bld


REGISTRY = {c.kind: c for c in (Extend, MoveWall, SetStoreys, SetRoof,
                                AddOpening, RemoveBlock, AutoLayout,
                                AddRoom, MovePartition, SetRoom,
                                RemoveRoom, MergeRooms)}


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

    if any(w in t for w in ("lay out", "layout", "add rooms", "draw rooms",
                            "room layout")):
        # "lay out the rooms" means the WHOLE building unless a level is
        # named. Pinning it to the existing block's ground floor left the
        # upper floor and the extension as solid lumps, which the gate
        # then reported as missing circulation and an inner room — a
        # refusal caused by the parser, not by the design.
        import re as _re
        m = _re.search(r"(?:floor|level)\s*(\d)", t)
        kw = {"label": "lay out standard rooms"}
        if m:
            kw["level"] = int(m.group(1))
        return make("auto_layout", **kw)

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
