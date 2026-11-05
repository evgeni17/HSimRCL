# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_inspect.py @ 1150d3e
"""Describe the visual materials of a USD asset as JSON.

Runs under a regular Python with `usd-core` installed, never inside Cinema 4D: the C4D importer
ignores UsdPreviewSurface networks and GeomSubsets of instanceable prims, and C4D ships no `pxr`.

Usage: python simready_inspect.py <usd-file> <pxr-site-dir> > asset.json
"""
import json
import os
import sys

PHYSICS_MARKER = "PhysicsMaterials"
SURFACE_INPUTS = ("diffuseColor", "metallic", "roughness", "normal", "opacity", "emissiveColor")


def to_ranges(indices):
    """Compress sorted face indices into [start, end] inclusive ranges to keep the JSON small."""
    ranges = []
    for index in sorted(indices):
        if ranges and index == ranges[-1][1] + 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    return ranges


def is_authored(shader_input):
    """True when the shader input exists; GetInput returns an invalid object, not None, for unauthored inputs."""
    return shader_input is not None and shader_input.GetAttr().IsValid()


def read_value(shader_input):
    """Return the authored value of a shader input, or None."""
    return shader_input.Get() if is_authored(shader_input) else None


def authoring_layer_dir(attribute):
    """Folder of the layer file that authored attribute, or None."""
    from pxr import Usd
    stack = attribute.GetPropertyStack(Usd.TimeCode.Default()) if attribute else None
    layer_path = stack[0].layer.realPath if stack else ""
    return os.path.dirname(layer_path) if layer_path else None


def asset_path(value, attribute=None):
    """Return the file path of an Sdf.AssetPath.

    USD leaves resolvedPath empty for <UDIM> templates, so the authored path stays relative
    ('../Textures/x.<UDIM>.png'); it is anchored here to the layer that authored it, as USD does for plain files.
    """
    if value is None:
        return None
    if value.resolvedPath:
        return value.resolvedPath
    path = value.path
    base = None if not path or os.path.isabs(path) else authoring_layer_dir(attribute)
    return os.path.normpath(os.path.join(base, path)) if base else (path or None)


def read_transform2d(uv_input):
    """Read scale/rotation/translation from a UsdTransform2d feeding a texture's st input."""
    if not is_authored(uv_input) or not uv_input.HasConnectedSource():
        return None
    source = uv_input.GetConnectedSource()[0].GetPrim()
    shader_id = source.GetAttribute("info:id").Get()
    if shader_id != "UsdTransform2d":
        return None
    get = lambda name, default: (source.GetAttribute("inputs:" + name).Get() or default)
    return {
        "scale": list(get("scale", (1.0, 1.0))),
        "rotation": float(get("rotation", 0.0)),
        "translation": list(get("translation", (0.0, 0.0))),
    }


def read_texture(shader, channel):
    """Describe a UsdUVTexture node as a plain dict, including which channel the consumer reads."""
    get = lambda name: read_value(shader.GetInput(name))
    return {
        "file": asset_path(get("file"), shader.GetInput("file").GetAttr()),
        "channel": channel,
        "color_space": str(get("sourceColorSpace") or "auto"),
        "scale": list(get("scale") or (1, 1, 1, 1)),
        "bias": list(get("bias") or (0, 0, 0, 0)),
        "wrap": [str(get("wrapS") or "useMetadata"), str(get("wrapT") or "useMetadata")],
        "uv": read_transform2d(shader.GetInput("st")),
    }


def producing_attribute(surface_input):
    """The attribute that really gives the input its value.

    A connection may lead to the Material's own interface input (URDF converters write the colours there) or
    through several of them; USD follows that chain and returns either a shader output or an authored input.
    """
    producers = surface_input.GetValueProducingAttributes(False)
    return producers[0] if producers else surface_input.GetAttr()


def texture_source(attribute):
    """(UsdUVTexture shader, output name) when attribute is a texture node's output with a file, else None."""
    from pxr import UsdShade
    base, kind = UsdShade.Utils.GetBaseNameAndType(attribute.GetName())
    if kind != UsdShade.AttributeType.Output:
        return None
    shader = UsdShade.Shader(attribute.GetPrim())
    if shader.GetIdAttr().Get() != "UsdUVTexture" or not read_value(shader.GetInput("file")):
        return None
    return shader, base


def read_input(shader, name):
    """Return {'texture': ...} for an input fed by an image, {'value': ...} for a constant, else None.

    A connection that ends anywhere else (a primvar reader, an empty texture node) falls back to the value
    authored on the input itself, if any, instead of a texture without a file (which rendered grey).
    """
    surface_input = shader.GetInput(name)
    if not is_authored(surface_input):
        return None
    attribute = producing_attribute(surface_input)
    texture = texture_source(attribute)
    if texture:
        return {"texture": read_texture(*texture)}
    value = attribute.Get()
    value = surface_input.Get() if value is None else value
    if value is None:
        return None
    return {"value": list(value) if hasattr(value, "__len__") else float(value)}


def read_material(material):
    """Return the UsdPreviewSurface inputs of a material, or None if it has no preview surface."""
    shader = material.ComputeSurfaceSource()[0]
    if not shader or shader.GetIdAttr().Get() != "UsdPreviewSurface":
        return None
    found = {name: read_input(shader, name) for name in SURFACE_INPUTS}
    return {name: spec for name, spec in found.items() if spec}


def material_name(material):
    """Short name used to match a material to GeomSubset names and C4D material names."""
    return material.GetPrim().GetName()


def bound_material(prim):
    """Return the material bound to prim (preview purpose), or None."""
    from pxr import UsdShade
    return UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0] or None


def read_mesh(prim):
    """Describe one mesh: face count, default material name and per-material face ranges."""
    from pxr import UsdGeom, UsdShade
    default = bound_material(prim)
    subsets = []
    for subset in UsdShade.MaterialBindingAPI(prim).GetMaterialBindSubsets():
        material = bound_material(subset.GetPrim())
        if material:
            subsets.append({"material": material_name(material),
                            "ranges": to_ranges(subset.GetIndicesAttr().Get())})
    return {
        "path": str(prim.GetPath()),
        "faces": len(UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get()),
        "default_material": material_name(default) if default else None,
        "subsets": subsets,
    }


def _joint_frame(joint, cache):
    """(body world transform, local position, local rotation) of the joint's frame: body0's side, else body1's."""
    stage = joint.GetPrim().GetStage()
    sides = ((joint.GetBody0Rel(), joint.GetLocalPos0Attr(), joint.GetLocalRot0Attr()),
             (joint.GetBody1Rel(), joint.GetLocalPos1Attr(), joint.GetLocalRot1Attr()))
    for rel, position, rotation in sides:
        targets = rel.GetTargets()
        body = stage.GetPrimAtPath(targets[0]) if targets else None
        if body is not None and body.IsValid() and position.Get() is not None:
            return cache.GetLocalToWorldTransform(body), position.Get(), rotation.Get()
    return None


def joint_anchor(frame):
    """World position of a joint in stage units, the point a hinge or wheel turns around; None when unknown."""
    from pxr import Gf
    if frame is None:
        return None
    world, position, _ = frame
    return list(world.Transform(Gf.Vec3d(*position)))


def joint_direction(frame, axis):
    """World direction (unit, stage space) of a joint's axis token X/Y/Z, or None."""
    from pxr import Gf
    if frame is None or axis not in ("X", "Y", "Z"):
        return None
    world, _, rotation = frame
    local = Gf.Vec3d(*[1.0 if name == axis else 0.0 for name in "XYZ"])
    if rotation is not None:
        local = Gf.Rotation(Gf.Quatd(rotation)).TransformDir(local)
    direction = world.TransformDir(local)
    return list(direction.GetNormalized()) if direction.GetLength() > 1e-12 else None


LIMIT_INFINITY = 1e6  # USD writes "no limit" as +-inf or as huge numbers


def joint_limits(prim):
    """(lower, upper) of a revolute (degrees) or prismatic (stage units) joint; None when it is free."""
    from pxr import UsdPhysics
    for schema in (UsdPhysics.RevoluteJoint, UsdPhysics.PrismaticJoint):
        if prim.IsA(schema):
            lower, upper = schema(prim).GetLowerLimitAttr().Get(), schema(prim).GetUpperLimitAttr().Get()
            finite = all(v is not None and abs(v) < LIMIT_INFINITY for v in (lower, upper))
            return [lower, upper] if finite and lower <= upper else None
    return None


def joint_axis_token(prim):
    """Axis token of a revolute, prismatic or spherical joint ('X', 'Y', 'Z'), else None."""
    from pxr import UsdPhysics
    for schema in (UsdPhysics.RevoluteJoint, UsdPhysics.PrismaticJoint, UsdPhysics.SphericalJoint):
        if prim.IsA(schema):
            return str(schema(prim).GetAxisAttr().Get())
    return None


def _side_matrix(stage, rel, position, rotation, cache):
    """World matrix of one side's joint frame (rotation, then position, in the body), scale removed; or None."""
    from pxr import Gf
    targets = rel.GetTargets()
    body = stage.GetPrimAtPath(targets[0]) if targets else None
    world = cache.GetLocalToWorldTransform(body) if body is not None and body.IsValid() else Gf.Matrix4d(1.0)
    local = Gf.Matrix4d(1.0)
    local.SetRotateOnly(Gf.Rotation(Gf.Quatd(rotation.Get() or Gf.Quatf(1.0))))
    local.SetTranslateOnly(Gf.Vec3d(*(position.Get() or (0.0, 0.0, 0.0))))
    return (local * world).RemoveScaleShear()


def joint_rest(joint, axis):
    """How far the joint is already turned (degrees) or slid (stage units) in the authored pose.

    Limits are measured from the joint's zero, which is where both sides' frames coincide, not from the pose
    the model is saved in (a desk lamp's upper arm rests at about 85 deg of its 20..150 range). Controllers
    start at 0 in the saved pose, so their limits must be shifted by this amount. None when unknown.
    """
    import math
    from pxr import Gf, UsdGeom, UsdPhysics
    if axis not in ("X", "Y", "Z"):
        return None
    prim, cache = joint.GetPrim(), UsdGeom.XformCache()
    stage = prim.GetStage()
    frame0 = _side_matrix(stage, joint.GetBody0Rel(), joint.GetLocalPos0Attr(), joint.GetLocalRot0Attr(), cache)
    frame1 = _side_matrix(stage, joint.GetBody1Rel(), joint.GetLocalPos1Attr(), joint.GetLocalRot1Attr(), cache)
    relative = frame1 * frame0.GetInverse()  # frame1 seen from frame0 (USD matrices act on row vectors)
    unit = Gf.Vec3d(*[1.0 if name == axis else 0.0 for name in "XYZ"])
    if prim.IsA(UsdPhysics.PrismaticJoint):
        return float(Gf.Dot(relative.ExtractTranslation(), unit))
    quat = relative.ExtractRotationQuat()
    twist = 2.0 * math.degrees(math.atan2(Gf.Dot(quat.GetImaginary(), unit), quat.GetReal()))
    return (twist + 180.0) % 360.0 - 180.0


def read_joint(prim, cache):
    """One joint as {'parent', 'child', 'kind', 'anchor', 'direction', 'limits', 'rest'}, or None without body1."""
    from pxr import UsdPhysics
    joint = UsdPhysics.Joint(prim)
    parents, children = joint.GetBody0Rel().GetTargets(), joint.GetBody1Rel().GetTargets()
    if not children:
        return None
    frame, axis = _joint_frame(joint, cache), joint_axis_token(prim)
    rest = joint_rest(joint, axis) if prim.IsA(UsdPhysics.RevoluteJoint) or prim.IsA(UsdPhysics.PrismaticJoint) else None
    return {"parent": str(parents[0]) if parents else None, "child": str(children[0]), "kind": prim.GetTypeName(),
            "anchor": joint_anchor(frame), "direction": joint_direction(frame, axis),
            "limits": joint_limits(prim), "rest": rest}


def read_joints(prims):
    """The physics joints: body0 carries body1, which is the model's kinematic hierarchy (parent is None for a
    joint to the world). anchor and direction are in stage world space; limits in degrees or stage units."""
    from pxr import UsdGeom, UsdPhysics
    cache = UsdGeom.XformCache()
    found = (read_joint(prim, cache) for prim in prims if prim.IsA(UsdPhysics.Joint))
    return [joint for joint in found if joint]


def read_xforms(prims):
    """{prim path: local matrix (4 rows of 4) relative to the parent prim} of every prim with transform ops.

    The matrix is taken from the composed world transforms, so it honours "!resetXformStack!": a ForgeCAD
    desk lamp places each arm in world space that way, Cinema 4D's importer ignores the reset and stacks the
    parts on their parents (the arm and head came in torn off). The importer in Cinema 4D compares its result
    with these matrices and corrects the parts that differ.
    """
    from pxr import UsdGeom
    cache, found = UsdGeom.XformCache(), {}
    for prim in prims:
        xformable = UsdGeom.Xformable(prim) if prim.IsA(UsdGeom.Xformable) else None
        if xformable is None or not (xformable.GetOrderedXformOps() or xformable.GetResetXformStack()):
            continue
        parent_world = cache.GetLocalToWorldTransform(prim.GetParent())
        local = cache.GetLocalToWorldTransform(prim) * parent_world.GetInverse()
        found[str(prim.GetPath())] = [list(local.GetRow(row)) for row in range(4)]
    return found


def is_visual_material(prim):
    """True for UsdShade.Material prims outside the physics material scope."""
    return prim.GetTypeName() == "Material" and PHYSICS_MARKER not in str(prim.GetPath())


def traverse(stage):
    """Walk the stage including instance proxies, which hold the content of instanceable prims."""
    from pxr import Usd
    return Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())


def inspect(stage):
    """Build the JSON-serialisable description of the stage."""
    from pxr import UsdGeom, UsdShade
    prims = list(traverse(stage))
    materials = {}
    for prim in filter(is_visual_material, prims):
        spec = read_material(UsdShade.Material(prim))
        if spec:
            materials[prim.GetName()] = spec
    return {
        "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
        "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
        "meshes": [read_mesh(p) for p in prims if p.IsA(UsdGeom.Mesh)],
        "materials": materials,
        "joints": read_joints(prims),
        "xforms": read_xforms(prims),
    }


def main(argv):
    """CLI entry point: argv = [usd_file, pxr_site_dir]."""
    if len(argv) != 2:
        sys.exit(__doc__)
    sys.path.insert(0, argv[1])
    from pxr import Usd
    stage = Usd.Stage.Open(argv[0])
    json.dump(inspect(stage), sys.stdout, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
