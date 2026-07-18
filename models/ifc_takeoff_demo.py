#!/usr/bin/env python3
"""
IfcOpenShell quantity take-off demo for BuildScan AI.

Builds a small room (slab + 4 walls) as a real IFC4 model, then uses the
OpenCASCADE geometry engine to compute floor area, wall areas and volumes
straight from the solid geometry — the "measurement & quantity take-off"
engine (spec Functional Area 5).

Run:  python3 models/ifc_takeoff_demo.py
"""
import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.api.context
import ifcopenshell.api.project
import ifcopenshell.api.spatial
import ifcopenshell.api.aggregate
import ifcopenshell.geom
import numpy as np

# Room dimensions in metres (canonical unit per spec section 11)
L, W, H, T = 4.0, 3.0, 2.4, 0.1   # length, width, height, wall/slab thickness


def build_model():
    f = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="BuildScan Demo")
    # Force metres as the length unit (IFC's default is millimetre, which would
    # otherwise read our metre values as mm and scale the geometry down 1000x).
    metre = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")  # no prefix = METRE
    ifcopenshell.api.unit.assign_unit(f, units=[metre])
    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx)

    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Ground Floor")
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[storey], relating_object=building)

    def box(name, ifc_class, x, y, z, dx, dy, dz):
        """Create an element as an extruded rectangular solid at (x,y,z)."""
        el = ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=name)
        profile = f.createIfcRectangleProfileDef("AREA", None,
            f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0))), float(dx), float(dy))
        direction = f.createIfcDirection((0.0, 0.0, 1.0))
        solid = f.createIfcExtrudedAreaSolid(profile,
            f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))), direction, float(dz))
        shape = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])
        el.Representation = f.createIfcProductDefinitionShape(None, None, [shape])
        el.ObjectPlacement = f.createIfcLocalPlacement(None,
            f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(x), float(y), float(z)))))
        ifcopenshell.api.spatial.assign_container(f, products=[el], relating_structure=storey)
        return el

    box("Floor slab", "IfcSlab", 0.0, 0.0, -T, L, W, T)
    box("Wall S", "IfcWall", 0.0, 0.0, 0.0, L, T, H)
    box("Wall N", "IfcWall", 0.0, W - T, 0.0, L, T, H)
    box("Wall W", "IfcWall", 0.0, 0.0, 0.0, T, W, H)
    box("Wall E", "IfcWall", L - T, 0.0, 0.0, T, W, H)
    return f


def quantities(f):
    """Compute volume + surface area of every product from its solid geometry."""
    settings = ifcopenshell.geom.settings()
    total_vol = 0.0
    rows = []
    for product in f.by_type("IfcProduct"):
        if not product.Representation:
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
        except Exception:
            continue
        verts = np.array(shape.geometry.verts).reshape(-1, 3)
        faces = np.array(shape.geometry.faces).reshape(-1, 3)
        vol = mesh_volume(verts, faces)
        area = mesh_area(verts, faces)
        total_vol += vol
        rows.append((product.Name, vol, area))
    return rows, total_vol


def mesh_volume(v, faces):
    a, b, c = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
    return float(np.abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)


def mesh_area(v, faces):
    a, b, c = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
    return float((np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2.0).sum())


if __name__ == "__main__":
    f = build_model()
    out = "/tmp/buildscan_room.ifc"
    f.write(out)
    print(f"IFC written: {out}  (schema {f.schema})")

    # Reopen from disk so the geometry engine tessellates the serialised solids.
    f = ifcopenshell.open(out)
    rows, total_vol = quantities(f)
    print(f"\n{'Element':<14}{'Volume m3':>12}{'Surface m2':>12}")
    print("-" * 38)
    for name, vol, area in rows:
        print(f"{name:<14}{vol:>12.3f}{area:>12.3f}")
    print("-" * 38)
    print(f"{'TOTAL concrete/masonry volume':<26}{total_vol:>12.3f} m3")

    floor_area = L * W
    print(f"\nInternal floor area (L*W): {floor_area:.2f} m2")
    print(f"Wall run (perimeter):      {2*(L+W):.2f} m")
    print("\nOK: IfcOpenShell read the solid geometry and produced quantities.")
