import os

import bpy
import numpy as np
import phobos.blender.utils.selection as sUtils
import phobos.blender.utils.editing as eUtils
import phobos.blender.utils.naming as nUtils
import phobos.blender.utils.blender as bUtils
import phobos.blender.utils.io as ioUtils
from phobos.blender.utils.validation import validate
from phobos.blender.phoboslog import log
import phobos.blender.model.inertia as inertiamodel
from phobos.blender import reserved_keys

from phobos.io import representation, sensor_representations, xmlrobot
from phobos import core

"""
Factory functions for creating representation.* Instances from blender
"""


def deriveObjectPose(obj, logging=True):
    effectiveparent = sUtils.getEffectiveParent(obj)
    matrix = eUtils.getCombinedTransform(obj, effectiveparent)

    pose = representation.Pose.from_matrix(np.array(matrix))
    if logging:
        log(
            obj.name+": Location: " + str(pose.position) + " Rotation: " + str(pose.rotation),
            'DEBUG',
        )
    return pose


@validate("material")
def deriveMaterial(mat, logging=False, errors=None):
    if "No material defined." in errors:
        return None
    # textures
    diffuseTexture = None
    normalTexture = None
    diffuse_color = None
    specular_color = None
    emissive = None
    transparency = None
    shininess = None
    if mat.use_nodes:
        for tex in [node for node in mat.node_tree.nodes if "Image Texture" in node.name]:
            if tex.outputs["Color"].links[0].to_socket.name == "Base Color":
                diffuseTexture = representation.Texture(image=tex.image)
            elif tex.outputs["Color"].links[0].to_socket.node.name == "Normal Map":
                normalTexture = representation.Texture(image=tex.image)
        if "Specular BSDF" in mat.node_tree.nodes.keys():
            diffuse_color = mat.node_tree.nodes["Specular BSDF"].inputs["Base Color"].default_value
            specular_color = mat.node_tree.nodes["Specular BSDF"].inputs["Specular"].default_value
            emissive = mat.node_tree.nodes["Specular BSDF"].inputs["Emissive Color"].default_value
            shininess = 1-mat.node_tree.nodes["Specular BSDF"].inputs["Roughness"].default_value
            transparency = mat.node_tree.nodes["Specular BSDF"].inputs["Transparency"].default_value
        elif "Principled BSDF" in mat.node_tree.nodes.keys():
            diffuse_color = mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value
            specular_color = np.array(diffuse_color) * mat.node_tree.nodes["Principled BSDF"].inputs["Specular"].default_value
            emissive = np.array(mat.node_tree.nodes["Principled BSDF"].inputs["Emission"].default_value)
            shininess = 1-mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value
            transparency = 1-mat.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value
    if diffuse_color is None:
        diffuse_color = mat.diffuse_color
    if specular_color is None:
        specular_color = mat.specular_color
    if shininess is None:
        shininess = 1-mat.roughness

    return representation.Material(
        name=mat.name,
        diffuse=diffuse_color,
        specular=specular_color,
        shininess=shininess,
        emissive=emissive,
        diffuseTexture=diffuseTexture,
        normalTexture=normalTexture,
        transparency=transparency
    )


@validate('geometry_type')
def deriveGeometry(obj, **kwargs):
    gtype = obj['geometry/type']
    if gtype == 'box':
        return representation.Box(size=list(obj.dimensions))
    elif gtype == 'cylinder':
        return representation.Cylinder(
            radius=obj.dimensions[0] / 2,
            length=obj.dimensions[2]
        )
    elif gtype == 'sphere':
        return representation.Sphere(
            radius=obj.dimensions[0] / 2
        )
    elif gtype == 'mesh':
        return representation.Mesh(
            scale=list(obj.matrix_world.to_scale()),
            mesh=obj.data,
            meshname=obj.data.name
        )
    else:
        raise ValueError(f"Unknown geometry type: {gtype}")


def deriveCollision(obj, **kwargs):
    # bitmask
    bitmask = None
    # the bitmask is cut to length = 16 and reverted for int parsing
    if 'collision_groups' in dir(obj.rigid_body):
        bitmask = int(
            ''.join(['1' if group else '0' for group in obj.rigid_body.collision_groups[:16]])[::-1],
            2,
        )
        for group in obj.rigid_body.collision_groups[16:]:
            if group:
                log(f"Object {obj.name} is on a collision layer higher than 16. These layers are ignored when exporting."
                    'WARNING',)
                break

    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in reserved_keys.VISCOL_KEYS+reserved_keys.INTERNAL_KEYS:
            if "/" not in k:
                annotations[k] = v
            else:
                k1, k2 = k.split("/", 1)
                if k1 not in annotations.keys():
                    annotations[k1] = {}
                annotations[k1][k2] = v

    return representation.Collision(
        name=obj.name,
        geometry=deriveGeometry(obj),
        origin=deriveObjectPose(obj),
        bitmask=bitmask,
        **annotations
    )


@validate('visual')
def deriveVisual(obj, logging=True, **kwargs):
    # [TODO v2.1.0] REVIEW this was commented, is this applicable?
    # todo2.9: if obj.lod_levels:
    #     if 'lodmaxdistances' in obj:
    #         maxdlist = obj['lodmaxdistances']
    #     else:
    #         maxdlist = [obj.lod_levels[i + 1].distance for i in range(len(obj.lod_levels) - 1)] + [
    #             100.0
    #         ]
    #     lodlist = []
    #     for i in range(len(obj.lod_levels)):
    #         filename = obj.lod_levels[i].object.data.name + ioUtils.getOutputMeshtype()
    #         lodlist.append(
    #             {
    #                 'start': obj.lod_levels[i].distance,
    #                 'end': maxdlist[i],
    #                 'filename': os.path.join('meshes', filename),
    #             }
    #         )
    #     visual['lod'] = lodlist

    # material
    material = deriveMaterial(obj.active_material, logging=logging)

    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in reserved_keys.VISCOL_KEYS+reserved_keys.INTERNAL_KEYS:
            if "/" not in k:
                annotations[k] = v
            else:
                k1, k2 = k.split("/", 1)
                if k1 not in annotations.keys():
                    annotations[k1] = {}
                annotations[k1][k2] = v

    return representation.Visual(
        name=obj.name,
        geometry=deriveGeometry(obj),
        origin=deriveObjectPose(obj),
        material=material,
        **annotations
    )


@validate('inertia_data')
def deriveInertial(obj, logging=True, **kwargs):
    inertia = representation.Inertia(*obj["inertia"][0])

    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in ["mass", "inertia", "origin"]:
            if "/" not in k:
                annotations[k] = v
            else:
                k1, k2 = k.split("/", 1)
                if k1 not in annotations.keys():
                    annotations[k1] = {}
                annotations[k1][k2] = v

    return representation.Inertial(
        mass=obj["mass"],
        inertia=inertia,
        origin=deriveObjectPose(obj),
        **annotations
    )


# # [TODO v2.1.0] Add KCCD support in blender
# def deriveKCCDHull(obj):
#     effectiveparent = sUtils.getEffectiveParent(obj)
#
#     return representation.KCCDHull(
#         points=obj.data.vertices,
#         radius=obj["radius"],
#         frame=effectiveparent.name
#     )


# [TODO v2.1.0] Re-Add SRDF support
# def deriveApproxsphere(obj):
#     """This function derives an SRDF approximation sphere from a given blender object
#
#     Args:
#       obj(bpy_types.Object): The blender object to derive the approxsphere from.
#
#     Returns:
#       : tuple
#
#     """
#     try:
#         sphere = initObjectProperties(obj)
#         sphere['radius'] = obj.dimensions[0] / 2
#         pose = deriveObjectPose(obj)
#         sphere['center'] = pose['translation']
#     except KeyError:
#         log("Missing data in collision approximation object " + obj.name, "ERROR")
#         return None
#     return sphere
#
#
# def deriveGroupEntry(group):
#     """Derives a list of phobos link skeletons for a provided group object.
#
#     Args:
#       group(bpy_types.Group): The blender group to extract the links from.
#
#     Returns:
#       : list
#
#     """
#     links = []
#     for obj in group.objects:
#         if obj.phobostype == 'link':
#             links.append({'type': 'link', 'name': nUtils.getObjectName(obj)})
#         else:
#             log(
#                 "Group "
#                 + group.name
#                 + " contains "
#                 + obj.phobostype
#                 + ': '
#                 + nUtils.getObjectName(obj),
#                 "ERROR",
#             )
#     return links
#
#
# def deriveChainEntry(obj):
#     """Derives a phobos dict entry for a kinematic chain ending in the provided object.
#
#     Args:
#       obj: return:
#
#     Returns:
#
#     """
#     returnchains = []
#     if 'endChain' in obj:
#         chainlist = obj['endChain']
#     for chainName in chainlist:
#         chainclosed = False
#         parent = obj
#         chain = {'name': chainName, 'start': '', 'end': nUtils.getObjectName(obj), 'elements': []}
#         while not chainclosed:
#             # FIXME: use effectiveParent
#             if parent.parent is None:
#                 log("Unclosed chain, aborting parsing chain " + chainName, "ERROR")
#                 chain = None
#                 break
#             chain['elements'].append(parent.name)
#             # FIXME: use effectiveParent
#             parent = parent.parent
#             if 'startChain' in parent:
#                 startchain = parent['startChain']
#                 if chainName in startchain:
#                     chain['start'] = nUtils.getObjectName(parent)
#                     chain['elements'].append(nUtils.getObjectName(parent))
#                     chainclosed = True
#         if chain is not None:
#             returnchains.append(chain)
#     return returnchains


@validate('link')
def deriveLink(obj, objectlist=None, logging=True, errors=None):
    # use scene objects if no objects are defined
    if objectlist is None:
        objectlist = list(bpy.context.scene.objects)

    if logging:
        log("Deriving link from object " + obj.name + ".", 'DEBUG')

    visuals = []
    collisions = []
    annotations = {
        "approxcollision": []
    }

    # gather all visual/collision objects for the link from the objectlist
    for part in [item for item in objectlist if item.phobostype in ['visual', 'collision', 'approxsphere']]:
        effectiveparent = sUtils.getEffectiveParent(part)
        if effectiveparent == obj:
            if logging:
                log(
                    "  Adding " + part.phobostype + " '" + nUtils.getObjectName(part) + "' to link.",
                    'DEBUG',
                )
            if part.phobostype == "visual":
                visuals.append(deriveVisual(part, logging=logging))
            elif part.phobostype == "collision":
                collisions.append(deriveCollision(part, logging=logging))
            # [TODO v2.1.0] Re-add SRDF support
            # elif obj.phobostype == 'approxsphere':
            #     annotations['approxcollision'].append(deriveApproxsphere(obj))

    # gather the inertials for fusing the link inertia
    inertials = [inert for inert in obj.children if inert.phobostype == 'inertial']

    mass = None
    com = None
    inertia = None
    if len(inertials) > 0:
        # get inertia data
        mass, com, inertia = inertiamodel.fuse_inertia_data(inertials)

    inertial = None
    if not any([mass, com, inertia]):
        if logging:
            log("No inertia information for link object " + obj.name + ".", 'DEBUG')
    else:
        # add inertia to link
        inertial = representation.Inertial(
            mass=mass,
            inertia=representation.Inertia(*inertiamodel.inertiaMatrixToList(inertia)),
            origin=representation.Pose(xyz=list(com))
        )

    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in reserved_keys.JOINT_KEYS+reserved_keys.LINK_KEYS+reserved_keys.INTERNAL_KEYS and not k.startswith("joint/"):
            k = k.replace("link/", "")
            if "/" not in k:
                annotations[k] = v
            else:
                k1, k2 = k.split("/", 1)
                if k1 not in annotations.keys():
                    annotations[k1] = {}
                annotations[k1][k2] = v

    return representation.Link(
        name=obj.name,
        visuals=visuals,
        collisions=collisions,
        inertial=inertial,
        # [TODO v2.1.0] Add KCCD support
        kccd_hull=None,
        **annotations
    )


@validate('joint')
def deriveJoint(obj, logging=False, adjust=False, errors=None):

    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in reserved_keys.JOINT_KEYS+reserved_keys.LINK_KEYS+reserved_keys.INTERNAL_KEYS and not k.startswith("link/"):
            k = k.replace("joint/", "")
            if "/" not in k:
                annotations[k] = v
            else:
                k1, k2 = k.split("/", 1)
                if k1 not in annotations.keys():
                    annotations[k1] = {}
                annotations[k1][k2] = v


    # motor
    motor_children = sUtils.getChildren(obj, phobostypes=["motor"])
    assert len(motor_children) <= 1, f"More than one motor defined for {obj.name}"
    motor = motor_children[0] if len(motor_children) == 1 else None

    return representation.Joint(
        name=obj.get("joint/name", obj.name),
        parent=sUtils.getEffectiveParent(obj).name,
        child=obj.name,
        joint_type=obj["joint/type"],
        axis=obj["joint/axis"],
        origin=deriveObjectPose(obj),
        limit=representation.JointLimit(
            effort=obj.get("joint/limits/effort", None),
            velocity=obj.get("joint/limits/velocity", None),
            lower=obj.get("joint/limits/lower", None),
            upper=obj.get("joint/limits/upper", None)
        ) if any([k.startswith("joint/limits/") for k in obj.keys()]) else None,
        dynamics=representation.JointDynamics(
            damping=obj.get("joint/dynamics/springDamping", None),
            friction=obj.get("joint/dynamics/friction", None),
            spring_stiffness=obj.get("joint/dynamics/springStiffness", None),
            spring_reference=obj.get("joint/dynamics/springReference", None)
        ) if any([k.startswith("joint/dynamics/") for k in obj.keys()]) else None,
        # [TODO v2.1.0] Add possibility to depend on multiple joints
        mimic=representation.JointMimic(
            joint=obj["joint/mimic/joint"],
            multiplier=obj["joint/mimic/multiplier"],
            offset=obj["joint/mimic/offset"]
        ) if "joint/mimic/joint" in obj.keys() else None,
        motor=motor.name
    )


def deriveInterface(obj):
    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in reserved_keys.INTERFACE_KEYS+reserved_keys.INTERNAL_KEYS:
            if "/" not in k:
                annotations[k] = v
            else:
                k1, k2 = k.split("/", 1)
                if k1 not in annotations.keys():
                    annotations[k1] = {}
                annotations[k1][k2] = v

    # [TODO v2.0.0] validate direction
    return representation.Interface(
        name=obj.name,
        origin=deriveObjectPose(obj),
        parent=sUtils.getEffectiveParent(obj).name,
        type=obj["type"],
        direction=obj["direction"],
        **annotations
    )


# [TODO v2.0.0] Advance this
def deriveAnnotation(obj):
    """Derives the annotation info of an annotation object.
    """
    props = {
        "$pose": deriveObjectPose(obj),
        "$parent": sUtils.getEffectiveParent(obj).name,
        "$name": obj.name
    }
    props.update({
        k: v for k, v in obj.items() if k not in reserved_keys.INTERNAL_KEYS
    })
    return props


def deriveSensor(obj, logging=False):
    """This function derives a sensor from a given blender object

    Args:
      obj(bpy_types.Object): The blender object to derive the sensor from.
      names(bool, optional): return the link object name instead of an object link. (Default value = False)
      logging(bool, optional): whether to write log messages or not (Default value = False)

    Returns:
      : dict -- phobos representation of the sensor

    """

    if logging:
        log(
            "Deriving sensor from object " + nUtils.getObjectName(obj, phobostype='sensor') + ".",
            'DEBUG',
        )

    values = {k: v for k, v in obj.items() if k not in reserved_keys.INTERNAL_KEYS}
    values["parent"] = sUtils.getEffectiveParent(obj).name
    sensor_type = values.pop("type")

    if sensor_type.upper() in ["CAMERASENSOR", "CAMERA"]:
        return sensor_representations.CameraSensor(
             hud_height=240 if values.get('hud_height') is None else values.pop('hud_height'),
             hud_width=0 if values.get('hud_width') is None else values.pop('hud_width'),
             origin=deriveObjectPose(obj, logging),
             **values
        )
    else:
        return getattr(sensor_representations, sensor_type)(**values)


def deriveMotor(obj):
    parent = sUtils.getEffectiveParent(obj)
    assert parent.phobostype == "link"

    # further annotations
    annotations = {}
    for k, v in obj.items():
        if k not in reserved_keys.MOTOR_KEYS+reserved_keys.INTERNAL_KEYS:
            annotations[k] = v

    return representation.Motor(
        name=obj.name,
        joint=parent.get("joint/name", parent.name),
        **annotations
    )


# [TODO v2.0.0] Add submechanisms
def deriveSubmechanism(obj):
    raise NotImplementedError


# [TODO v2.1.0] Re-add light support
# def deriveLight(obj):
#     """This function derives a light from a given blender object
#
#     Args:
#       obj(bpy_types.Object): The blender object to derive the light from.
#
#     Returns:
#       : tuple
#
#     """
#     light = initObjectProperties(obj, phobostype='light')
#     light_data = obj.data
#     if light_data.use_diffuse:
#         light['color_diffuse'] = list(light_data.color)
#     if light_data.use_specular:
#         light['color_specular'] = copy.copy(light['color_diffuse'])
#     light['type'] = light_data.type.lower()
#     if light['type'] == 'SPOT':
#         light['size'] = light_data.size
#     pose = deriveObjectPose(obj)
#     light['position'] = pose['translation']
#     light['rotation'] = pose['rotation_euler']
#     try:
#         light['attenuation_linear'] = float(light_data.linear_attenuation)
#     except AttributeError:
#         # TODO handle this somehow
#         pass
#     try:
#         light['attenuation_quadratic'] = float(light_data.quadratic_attenuation)
#     except AttributeError:
#         pass
#     if light_data.energy:
#         light['attenuation_constant'] = float(light_data.energy)
#
#     light['parent'] = nUtils.getObjectName(sUtils.getEffectiveParent(obj))
#     return light


def deriveRepresentation(obj, logging=True, adjust=True):
    """Derives a phobos dictionary entry from the provided object.

    Args:
      obj(bpy_types.Object): The object to derive the dict entry (phobos data structure) from.
      names(bool, optional): use object names as dict entries instead of object links. (Default value = False)
      logging(bool, optional): whether to log messages or not (Default value = True)
      objectlist: (Default value = [])
      adjust: (Default value = True)

    Returns:
      : dict -- phobos representation of the object

    """
    repr_instance = None
    try:
        if obj.phobostype == 'inertial':
            repr_instance = deriveInertial(obj, adjust=adjust, logging=logging)
        elif obj.phobostype == 'visual':
            repr_instance = deriveVisual(obj)
        elif obj.phobostype == 'collision':
            repr_instance = deriveCollision(obj)
        # [TODO v2.1.0] Re-Add SRDF support
        # elif obj.phobostype == 'approxsphere':
        #     repr_instance = deriveApproxsphere(obj)
        elif obj.phobostype == 'sensor':
            repr_instance = deriveSensor(obj, logging=logging)
        # elif obj.phobostype == 'controller':
        #     repr_instance = deriveController(obj)
        # [TODO v2.1.0] Re-add light support
        # elif obj.phobostype == 'light':
        #     repr_instance = deriveLight(obj)
        elif obj.phobostype == 'motor':
            repr_instance = deriveMotor(obj)
        elif obj.phobostype == 'annotation':
            repr_instance = deriveAnnotation(obj)
    except KeyError:
        log("A KeyError occurred due to missing data in object" + obj.name, "DEBUG")
        return None
    return repr_instance


def deriveRobot(root, name='', objectlist=None):
    """
    Returns the phobos.core.Robot instance of a Phobos-Blender model.

    If name is not specified, it overrides the modelname in the root. If the modelname is not
    defined at all, 'unnamed' will be used instead.

    Args:
      root(bpy_types.Object): root object of the model
      name(str, optional): name for the derived model (Default value = '')
      objectlist(list: bpy_types.Object): objects to derive the model from (Default value = [])

    Returns:
        phobos.core.Robot
    """
    if root.phobostype != 'link':
        log(root.name + " is no valid 'link' object.", "ERROR")
        return None

    # get model name
    if name:
        modelname = name
    elif 'model/name' in root:
        modelname = root['model/name']
    else:
        modelname = 'unnamed'

    # create tuples of objects belonging to model
    if objectlist is None:
        objectlist = sUtils.getChildren(
            root, selected_only=ioUtils.getExpSettings().selectedOnly, include_hidden=False
        )

    # XMLVersion [TODO v2.1.0] Add matching constructor to phobos.core.Robot
    xml_robot = xmlrobot.XMLRobot(
        name=modelname,
        links=[deriveLink(obj) for obj in objectlist if obj.phobostype == 'link'],
        joints=[deriveJoint(obj) for obj in objectlist if obj.phobostype == 'link' and sUtils.getEffectiveParent(obj) is not None],
        sensors=[deriveSensor(obj) for obj in objectlist if obj.phobostype == 'sensor'],
        # [TODO v2.1.0] Add transmission support
    )

    # Full robot
    robot = core.Robot()
    robot.__dict__.update(xml_robot.__dict__)
    robot.description = bUtils.readTextFile('README.md')

    for motor in [deriveMotor(obj) for obj in objectlist if obj.phobostype == 'motor']:
        robot.add_motor(motor)

    for interface in [deriveInterface(obj) for obj in objectlist if obj.phobostype == 'interface']:
        robot.add_aggregate("interface", interface)

    # [TODO v2.0.0] Add submechanisms

    # Until here we have added all entities that are linkable
    robot.relink_entities()

    # [TODO v2.1.0] Re-add lights and SRDF support

    for named_annotation in [deriveAnnotation(obj) for obj in objectlist if obj.phobostype == 'annotation']:
        robot.add_named_annotation(named_annotation["$name"], {k: v for k, v in named_annotation.items() if k.startswith("$")})

    return robot