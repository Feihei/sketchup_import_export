import math
import os
import shutil
import tempfile
import time
from collections import defaultdict

import bpy
import numpy as np
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, Operator
from bpy_extras.io_utils import (
    ExportHelper,
    ImportHelper,
    unpack_face_list,
    unpack_list,
)
from mathutils import Matrix, Quaternion, Vector

__author__ = "Martijn Berger"
__license__ = "GPL"

"""
This program is free software; you can redistribute it and
or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 3
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, see http://www.gnu.org/licenses
"""

from . import sketchup
from .SKPutil import *

bl_info = {
    "name": "SketchUp Importer",
    "author": "Martijn Berger, Sanjay Mehta, Arindam Mondal, Peter Kirkham",
    "version": (0, 28, 0),
    "blender": (3, 2, 0),
    "description": "Import of native SketchUp (.skp) files",
    "wiki_url": "https://github.com/martijnberger/pyslapi",
    "doc_url": "https://github.com/arindam-m/pyslapi/wiki",
    "tracker_url": "https://github.com/arindam-m/pyslapi/wiki/Bug-Report",
    "category": "Import-Export",
    "location": "File > Import",
}

DEBUG = False

LOGS = True

MIN_LOGS = False

if not LOGS:
    MIN_LOGS = True


class SketchupAddonPreferences(AddonPreferences):
    bl_idname = __name__

    camera_far_plane: FloatProperty(name="Camera Clip Ends At :", default=250, unit="LENGTH")

    draw_bounds: IntProperty(name="Draw Similar Objects As Bounds When It's Over :", default=1000)

    def draw(self, context):
        layout = self.layout
        layout.label(text="- Basic Import Options -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "camera_far_plane")
        layout = self.layout
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "draw_bounds")


def skp_log(*args):
    # Log output by pre-pending "SU |"
    if len(args) > 0:
        print("SU | " + " ".join(["%s" % a for a in args]))


def create_nested_collection(coll_name):
    context = bpy.context
    main_coll_name = "SKP Imported Data"  # data imported into this collection

    # Check if the main import collection exists and create it if missing
    if not bpy.data.collections.get(main_coll_name):
        skp_main_coll = bpy.data.collections.new(main_coll_name)
        context.scene.collection.children.link(skp_main_coll)

    # Check if the named collection being created exists and create if missing
    if not bpy.data.collections.get(coll_name):
        skp_nested_coll = bpy.data.collections.new(coll_name)
        bpy.data.collections[main_coll_name].children.link(skp_nested_coll)

    # Set active layer to the named collection just created
    view_layer_coll = context.view_layer.layer_collection
    main_parent_coll = view_layer_coll.children[main_coll_name]
    coll_set_to_active = main_parent_coll.children[coll_name]
    context.view_layer.active_layer_collection = coll_set_to_active


def hide_one_level():
    context = bpy.context

    outliners = [a for a in context.screen.areas if a.type == "OUTLINER"]
    c = context.copy()
    for ol in outliners:
        c["area"] = ol
        bpy.ops.outliner.show_one_level(c, open=False)
        ol.tag_redraw()

    # context.view_layer.update()


class SceneImporter:
    def __init__(self):
        self.filepath = "/tmp/untitled.skp"
        self.name_mapping = {}
        self.component_meshes = {}
        self.scene = None
        self.layers_skip = []

    def set_filename(self, filename):
        self.filepath = filename
        self.basepath, self.skp_filename = os.path.split(self.filepath)
        return self  # allow chaining

    def load(self, context, **options):
        """Load a SketchUp file"""

        # Blender settings
        self.context = context
        self.reuse_material = options["reuse_material"]
        self.reuse_group = options["reuse_existing_groups"]
        self.max_instance = options["max_instance"]
        # self.render_engine = options['render_engine']
        self.component_stats = defaultdict(list)
        self.component_skip = proxy_dict()
        self.component_depth = proxy_dict()
        self.group_written = {}
        ren_res_x = context.scene.render.resolution_x
        ren_res_y = context.scene.render.resolution_y
        self.aspect_ratio = ren_res_x / ren_res_y

        # Start stopwatch for overall import
        _time_main = time.time()

        # Log filename being imported
        if LOGS:
            skp_log(f"Importing: {self.filepath}")
        addon_name = __name__.split(".")[0]
        self.prefs = context.preferences.addons[addon_name].preferences

        # Open the SketchUp file and access the model using SketchUp API
        try:
            self.skp_model = sketchup.Model.from_file(self.filepath)
        except Exception as e:
            if LOGS:
                skp_log(f"Error reading input file: {self.filepath}")
                skp_log(e)
            return {"FINISHED"}

        # Start stopwatch for camera import
        if not MIN_LOGS:
            skp_log("")
            skp_log("=== Importing Sketchup scenes and views as Blender Cameras ===")
        _time_camera = time.time()

        # Create collection for cameras
        create_nested_collection("SKP Scenes (as Cameras)")

        # Import a specific named SketchUp scene as a Blender camera and hide
        # the layers associated with that specific scene
        if options["import_scene"]:
            options["scenes_as_camera"] = False
            options["import_camera"] = True
            for s in self.skp_model.scenes:
                if s.name == options["import_scene"]:
                    if not MIN_LOGS:
                        skp_log(f"Importing named SketchUp scene '{s.name}'")
                    self.scene = s

                    # Skip s.layers which are the invisible layers
                    self.layers_skip = [l for l in s.layers]
            if not self.layers_skip and not MIN_LOGS:
                skp_log("Scene: '{}' didn't have any invisible layers.".format(options["import_scene"]))
            if self.layers_skip != [] and not MIN_LOGS:
                hidden_layers = sorted([l.name for l in self.layers_skip])
                print("SU | Invisible Layer(s)/Tag(s): \n     ", end="")
                print(*hidden_layers, sep=", ")

        # Import each scene as a Blender camera
        if options["scenes_as_camera"]:
            if not MIN_LOGS:
                skp_log("Importing all SketchUp scenes as Blender cameras")
            for s in self.skp_model.scenes:
                self.write_camera(s.camera, s.name)

        # Set the active camera and use for 3D view
        if options["import_camera"]:
            if not MIN_LOGS:
                skp_log("Importing last SketchUp view as Blender camera")
            if self.scene:
                active_cam = self.write_camera(self.scene.camera, name=self.scene.name)
                context.scene.camera = bpy.data.objects[active_cam]
            else:
                active_cam = self.write_camera(self.skp_model.camera)
                context.scene.camera = bpy.data.objects[active_cam]
            for area in bpy.context.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces[0].region_3d.view_perspective = "CAMERA"
                    break
        SKP_util.layers_skip = self.layers_skip
        if not MIN_LOGS:
            skp_log(f"Cameras imported in {(time.time() - _time_camera):.4f} sec.")

        # Start stopwatch for material imports
        if not MIN_LOGS:
            skp_log("")
            skp_log("=== Importing Sketchup materials into Blender ===")
        _time_material = time.time()
        self.write_materials(self.skp_model.materials)
        if not MIN_LOGS:
            skp_log(f"Materials imported in {(time.time() - _time_material):.4f} sec.")

        # Start stopwatch for component import
        if not MIN_LOGS:
            skp_log("")
            skp_log("=== Importing Sketchup components into Blender ===")
        _time_analyze_depth = time.time()

        # Create collection for components
        create_nested_collection("SKP Components")

        # Determine the number of components that exist in the SketchUp model
        self.skp_components = proxy_dict(self.skp_model.component_definition_as_dict)
        u_comps = [k for k, v in self.skp_components.items()]
        if not MIN_LOGS:
            print(f"SU | Contains {len(u_comps)} components: \n     ", end="")
            print(*u_comps, sep=", ")

        # Analyse component depths
        D = SKP_util()
        for c in self.skp_model.component_definitions:
            self.component_depth[c.name] = D.component_deps(c.entities)
            if DEBUG:
                print(f"     -- ({c.name}) --\n        Depth: {self.component_depth[c.name]}\n", end="")
                print(f"        Instances (Used): {c.numInstances} ({c.numUsedInstances})")
        if not MIN_LOGS:
            skp_log(f"Component depths analyzed in {(time.time() - _time_analyze_depth):.4f} sec.")

        # Import the components as duplicated groups then hide components
        self.write_duplicateable_groups()
        bpy.data.collections["SKP Components"].hide_viewport = True
        for vl in context.scene.view_layers:
            for l in vl.active_layer_collection.children:
                if l.name == "SKP Components":
                    l.exclude = True  # hide component collection in view layer
        if options["dedub_only"]:
            return {"FINISHED"}

        self.write_duplicateable_groups()

        if options["dedub_only"]:
            return {"FINISHED"}

        # self.component_stats = defaultdict(list)

        # Start stopwatch for mesh objects import
        if not MIN_LOGS:
            skp_log("")
            skp_log("=== Importing Sketchup mesh objects into Blender ===")
        _time_mesh_data = time.time()

        # Create collection for mesh objects
        create_nested_collection("SKP Mesh Objects")

        # Import mesh objects into structure that matches the SketchUp outliner
        self.write_entities(self.skp_model.entities, "_(Loose Entity)", Matrix.Identity(4))
        for k, _v in self.component_stats.items():
            name, mat = k
            if options["dedub_type"] == "VERTEX":
                self.instance_group_dupli_vert(name, mat, self.component_stats)
            else:
                self.instance_group_dupli_face(name, mat, self.component_stats)
        if not MIN_LOGS:
            skp_log(f"Entities imported in {(time.time() - _time_mesh_data):.4f} sec.")

        # Importing has completed
        if LOGS:
            skp_log("Finished entire importing process in %.4f sec.\n" % (time.time() - _time_main))

        # hide_one_level()

        # release model and terminate api
        # self.skp_model.close()

        return {"FINISHED"}

    #
    # Write components as groups that can be duplicated later.
    #
    def write_duplicateable_groups(self):
        component_stats = self.analyze_entities(
            self.skp_model.entities, "Sketchup", Matrix.Identity(4), component_stats=defaultdict(list)
        )
        instance_when_over = self.max_instance
        max_depth = max(self.component_depth.values(), default=0)

        # Filter out components from list if the total number of instances
        # is lower than the minimum threshold for creating duplicated mesh
        # objects.
        component_stats = {k: v for k, v in component_stats.items() if len(v) >= instance_when_over}
        for i in range(max_depth + 1):
            for k, v in component_stats.items():
                name, mat = k
                depth = self.component_depth[name]
                comp_def = self.skp_components[name]
                if comp_def and depth == 1:
                    # self.component_skip[(name, mat)] = comp_def.entities
                    pass
                elif comp_def and depth == i:
                    gname = group_name(name, mat)
                    if self.reuse_group and gname in bpy.data.collections:
                        skp_log(f"Group {gname} already defined")
                        self.component_skip[(name, mat)] = comp_def.entities
                        self.group_written[(name, mat)] = bpy.data.collections[gname]
                    else:
                        group = bpy.data.collections.new(name=gname)
                        skp_log(f"Component {gname} written as group")
                        self.component_def_as_group(
                            comp_def.entities, name, Matrix(), default_material=mat, etype=EntityType.outer, group=group
                        )
                        self.component_skip[(name, mat)] = comp_def.entities
                        self.group_written[(name, mat)] = group

    def analyze_entities(
        self,
        entities,
        name,
        transform,
        default_material="DefaultMaterial",
        etype=EntityType.none,
        component_stats=None,
        component_skip=None,
    ):
        if component_skip is None:
            component_skip = []
        if etype == EntityType.component:
            component_stats[(name, default_material)].append(transform)
        for group in entities.groups:
            if self.layers_skip and group.layer in self.layers_skip:
                continue
            if DEBUG:
                print(f"     |G {group.name}")
                print(f"     {Matrix(group.transform)}")
            self.analyze_entities(
                group.entities,
                "G-" + group.name,
                transform @ Matrix(group.transform),
                default_material=inherent_default_mat(group.material, default_material),
                etype=EntityType.group,
                component_stats=component_stats,
            )
        for instance in entities.instances:
            if self.layers_skip and instance.layer in self.layers_skip:
                continue
            mat = inherent_default_mat(instance.material, default_material)
            cdef = self.skp_components[instance.definition.name]
            if cdef is None:
                continue
            if (cdef.name, mat) in component_skip:
                continue
            if DEBUG:
                print(f"     |C {cdef.name}")
                print(f"     {Matrix(instance.transform)}")
            self.analyze_entities(
                cdef.entities,
                cdef.name,
                transform @ Matrix(instance.transform),
                default_material=mat,
                etype=EntityType.component,
                component_stats=component_stats,
            )
        return component_stats

    #
    # Import materials from SketchUp into Blender.
    #
    def write_materials(self, materials):
        if self.context.scene.render.engine != "CYCLES":
            self.context.scene.render.engine = "CYCLES"
        self.materials = {}
        self.materials_scales = {}
        if self.reuse_material and "DefaultMaterial" in bpy.data.materials:
            self.materials["DefaultMaterial"] = bpy.data.materials["DefaultMaterial"]
        else:
            bmat = bpy.data.materials.new("DefaultMaterial")
            bmat.diffuse_color = (0.8, 0.8, 0.8, 0)
            # if self.render_engine == 'CYCLES':
            # this modthed will remove 6.0.0
            if bpy.app.version < (6, 0, 0):
                bmat.use_nodes = True

            nodes = bmat.node_tree.nodes
            links = bmat.node_tree.links
            nodes.clear()
            output_shader = nodes.new("ShaderNodeOutputMaterial")
            output_shader.location = (0, 0)
            principled_bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            principled_bsdf.location = (-300, 0)
            links.new(principled_bsdf.outputs[0], output_shader.inputs["Surface"])
            
            self.materials["DefaultMaterial"] = bmat
        for mat in materials:
            name = mat.name
            if mat.texture:
                self.materials_scales[name] = mat.texture.dimensions[2:]
            else:
                self.materials_scales[name] = (1.0, 1.0)
            if self.reuse_material and name in bpy.data.materials:
                self.materials[name] = bpy.data.materials[name]
            else:
                bmat = bpy.data.materials.new(name)
                r, g, b, a = mat.color
                tex = mat.texture
                bmat.diffuse_color = (
                    math.pow((r / 255.0), 2.2),
                    math.pow((g / 255.0), 2.2),
                    math.pow((b / 255.0), 2.2),
                    round((a / 255.0), 2),
                )  # sRGB to Linear

                if round((a / 255.0), 2) < 1:
                    bmat.blend_method = "BLEND"
                    
                if bpy.app.version < (6, 0, 0):
                    bmat.use_nodes = True

                nodes = bmat.node_tree.nodes
                links = bmat.node_tree.links
                nodes.clear()
                output_shader = nodes.new("ShaderNodeOutputMaterial")
                output_shader.location = (0, 0)
                principled_bsdf = nodes.new("ShaderNodeBsdfPrincipled")
                principled_bsdf.location = (-300, 0)
                links.new(principled_bsdf.outputs[0], output_shader.inputs["Surface"])

                default_shader = nodes["Principled BSDF"]
                default_shader_base_color = default_shader.inputs["Base Color"]
                default_shader_base_color.default_value = bmat.diffuse_color
                default_shader_alpha = default_shader.inputs["Alpha"]
                default_shader_alpha.default_value = round((a / 255.0), 2)
                if tex:
                    tex_name = tex.name.split(os.path.sep)[-1]
                    temp_dir = tempfile.gettempdir()
                    skp_fname = self.filepath.split(os.path.sep)[-1].split(".")[0]
                    temp_dir += os.path.sep + skp_fname
                    if not os.path.isdir(temp_dir):
                        os.mkdir(temp_dir)
                    temp_file_path = os.path.join(temp_dir, tex_name)
                    # skp_log(f"Texture saved temporarily at {temp_file_path}")
                    tex.write(temp_file_path)
                    img = bpy.data.images.load(temp_file_path)
                    img.pack()
                    # os.remove(temp_file_path)
                    shutil.rmtree(temp_dir)
                    # if self.render_engine == 'CYCLES':
                    #    bmat.use_nodes = True
                    tex_node = nodes.new("ShaderNodeTexImage")
                    tex_node.image = img
                    tex_node.location = Vector((-600, 0))
                    links.new(tex_node.outputs["Color"], default_shader_base_color)
                    if img.file_format in ("PNG", "TARGA"):
                        links.new(tex_node.outputs["Alpha"], default_shader_alpha)
                # else:
                #    btex = bpy.data.textures.new(tex_name, 'IMAGE')
                #    btex.image = img
                #    slot = bmat.texture_slots.add()
                #    slot.texture = btex
                self.materials[name] = bmat
            if not MIN_LOGS:
                print(f"     {name}")

    def write_mesh_data(self, entities=None, name="", default_material="DefaultMaterial"):
        mesh_key = (name, default_material)
        if mesh_key in self.component_meshes:
            return self.component_meshes[mesh_key]
        verts = []
        loops_vert_idx = []
        mat_index = []
        smooth = []
        mats = keep_offset()
        seen = keep_offset()
        uv_list = []
        alpha = False
        uvs_used = False

        for f in entities.faces:
            if f.material:
                mat_number = mats[f.material.name]
            else:
                mat_number = mats[default_material]
                if default_material != "DefaultMaterial":
                    try:
                        f.st_scale = self.materials_scales[default_material]
                    except KeyError as _e:
                        pass

            vs, tri, uvs = f.tessfaces
            num_loops = 0

            mapping = {}
            for i, (v, uv) in enumerate(zip(vs, uvs)):
                l = len(seen)
                mapping[i] = seen[v]
                if len(seen) > l:
                    verts.append(v)
                uvs.append(uv)

            smooth_edge = False

            for edge in f.edges:
                if edge.GetSmooth() == True:
                    smooth_edge = True
                    break

            for face in tri:
                f0, f1, f2 = face[0], face[1], face[2]
                num_loops += 1

                if mapping[f2] == 0:
                    loops_vert_idx.extend([mapping[f2], mapping[f0], mapping[f1]])

                    uv_list.append(
                        (
                            uvs[f2][0],
                            uvs[f2][1],
                            uvs[f0][0],
                            uvs[f0][1],
                            uvs[f1][0],
                            uvs[f1][1],
                        )
                    )

                else:
                    loops_vert_idx.extend([mapping[f0], mapping[f1], mapping[f2]])

                    uv_list.append(
                        (
                            uvs[f0][0],
                            uvs[f0][1],
                            uvs[f1][0],
                            uvs[f1][1],
                            uvs[f2][0],
                            uvs[f2][1],
                        )
                    )

                smooth.append(smooth_edge)
                mat_index.append(mat_number)

        if len(verts) == 0:
            return None, False

        me = bpy.data.meshes.new(name)

        if len(mats) >= 1:
            mats_sorted = OrderedDict(sorted(mats.items(), key=lambda x: x[1]))
            for k in mats_sorted.keys():
                try:
                    bmat = self.materials[k]
                except KeyError as _e:
                    bmat = self.materials["DefaultMaterial"]
                me.materials.append(bmat)
                # if bmat.alpha < 1.0:
                #     alpha = True
                try:
                    # if self.render_engine == 'CYCLES':
                    if "Image Texture" in bmat.node_tree.nodes.keys():
                        uvs_used = True
                    # else:
                    #     for ts in bmat.texture_slots:
                    #         if ts is not None and ts.texture_coords is not None:
                    #             uvs_used = True
                except AttributeError as _e:
                    uvs_used = False
        else:
            skp_log(f"WARNING: Object {name} has no material!")

        tri_faces = list(zip(*[iter(loops_vert_idx)] * 3))
        tri_face_count = len(tri_faces)

        loop_start = []
        i = 0
        for f in tri_faces:
            loop_start.append(i)
            i += len(f)

        loop_total = list(map(lambda f: len(f), tri_faces))

        me.vertices.add(len(verts))
        me.vertices.foreach_set("co", unpack_list(verts))

        me.loops.add(len(loops_vert_idx))
        me.loops.foreach_set("vertex_index", loops_vert_idx)

        me.polygons.add(tri_face_count)
        me.polygons.foreach_set("loop_start", loop_start)
        me.polygons.foreach_set("loop_total", loop_total)
        me.polygons.foreach_set("material_index", mat_index)
        me.polygons.foreach_set("use_smooth", smooth)

        if uvs_used:
            k, l = 0, 0
            me.uv_layers.new()
            for i in range(len(tri_faces)):
                for j in range(3):
                    uv_cordinates = (uv_list[i][l], uv_list[i][l + 1])
                    me.uv_layers[0].data[k].uv = Vector(uv_cordinates)
                    k += 1
                    if j != 2:
                        l += 2
                    else:
                        l = 0

        me.update(calc_edges=True)
        me.validate()
        self.component_meshes[mesh_key] = me, alpha

        return me, alpha

    #
    # Recursively import all the mesh objects. Groups containing no mesh
    # information are imported as empty objects and can contain nested
    # groups or components. This approach preserves the hierarchy from the
    # SketchUp outliner.
    #
    def write_entities(
        self,
        entities,
        name,
        parent_transform,
        default_material="DefaultMaterial",
        etype=None,
        parent_name=None,
        parent_location=Vector((0, 0, 0)),
    ):
        # Check if this is a component that has already been duplicated. We
        # can skip writing this if it is already contained in a duplication
        # group.
        if etype == EntityType.component and (name, default_material) in self.component_skip:
            self.component_stats[(name, default_material)].append(parent_transform)
            return

        # Get the mesh data for this object
        me, alpha = self.write_mesh_data(entities=entities, name=name, default_material=default_material)

        # If there are no further nested groups or components, then we can
        # create an object containing the mesh. Otherwise we create a new
        # empty object and place an object containing the loose geometry as
        # a mesh within this group.
        nested_groups = 0
        for group in entities.groups:
            nested_groups += 1  # count groups (brute force approach)
        nested_comps = 0
        for comp in entities.instances:
            nested_comps += 1  # count components (brute force approach)
        nested_count = nested_groups + nested_comps
        hide_empty = False
        if nested_count == 0 or name == "_(Loose Entity)":
            ob = bpy.data.objects.new(name, me)
            ob.matrix_world = parent_transform
            if 0.01 < alpha < 1.0:
                ob.show_transparent = True
            if me:
                me.update(calc_edges=True)
        else:
            ob = bpy.data.objects.new(name, None)  # empty object to hold group
            ob.matrix_world = parent_transform
            # ob.hide_viewport = True  # disable empties in viewport
            hide_empty = True
            if me:
                ob_mesh = bpy.data.objects.new("_" + name + " (Loose Mesh)", me)
                ob_mesh.matrix_world = parent_transform
                if 0.01 < alpha < 1.0:
                    ob_mesh.show_transparent = True
                me.update(calc_edges=True)
                ob_mesh.parent = ob
                ob_mesh.location = Vector((0, 0, 0))
                bpy.context.collection.objects.link(ob_mesh)

        # Nested adjustments to the world matrix
        loc = ob.location
        nested_location = Vector((loc[0], loc[1], loc[2]))

        # Nest the object by assigning it to the parent object
        if parent_name is not None and parent_name != "_(Loose Entity)":
            ob.parent = bpy.data.objects[parent_name]
            ob.location -= parent_location
        if nested_count > 0:
            ob.rotation_mode = "QUATERNION"  # change from default mode of xyz
            ob.rotation_quaternion = Vector((1, 0, 0, 0))
            ob.scale = Vector((1, 1, 1))
        bpy.context.collection.objects.link(ob)
        ob.hide_set(hide_empty)  # enable but do not show empties in viewport

        for group in entities.groups:
            if group.hidden:
                continue
            if self.layers_skip and group.layer in self.layers_skip:
                continue
            temp_ob = bpy.data.objects.new(group.name, None)
            gname = "G-" + group_safe_name(temp_ob.name)
            if DEBUG:
                print(f"     Grp: {gname} in {ob.name}")
            self.write_entities(
                group.entities,
                gname,
                parent_transform @ Matrix(group.transform),
                default_material=inherent_default_mat(group.material, default_material),
                etype=EntityType.group,
                parent_name=ob.name,
                parent_location=nested_location,
            )

        for instance in entities.instances:
            if instance.hidden:
                continue
            if self.layers_skip and instance.layer in self.layers_skip:
                continue
            mat_name = inherent_default_mat(instance.material, default_material)
            cdef = self.skp_components[instance.definition.name]
            if cdef is None:
                continue
            if instance.name == "":
                cname = "C-" + cdef.name
            else:
                cname = instance.name + " (C-" + cdef.name + ")"
            if DEBUG:
                print(f"     Cmp: {cname} in {ob.name}")
            self.write_entities(
                cdef.entities,
                cname,
                parent_transform @ Matrix(instance.transform),
                default_material=mat_name,
                etype=EntityType.component,
                parent_name=ob.name,
                parent_location=nested_location,
            )

    def instance_object_or_group(self, name, default_material):
        try:
            group = self.group_written[(name, default_material)]
            ob = bpy.data.objects.new(name=name, object_data=None)
            ob.instance_type = "COLLECTION"
            ob.instance_collection = group
            ob.empty_display_size = 0.01
            return ob
        except KeyError as _e:
            me, alpha = self.component_meshes[(name, default_material)]
            ob = bpy.data.objects.new(name, me)
            if alpha:
                ob.show_transparent = True
            me.update(calc_edges=True)
            return ob

    def component_def_as_group(
        self, entities, name, parent_transform, default_material="DefaultMaterial", etype=None, group=None
    ):
        if etype == EntityType.outer:
            if (name, default_material) in self.component_skip:
                return
            else:
                if DEBUG:
                    skp_log(f"Write instance definition as group {group.name} {default_material}")
                self.component_skip[(name, default_material)] = True
        if etype == EntityType.component and (name, default_material) in self.component_skip:
            ob = self.instance_object_or_group(name, default_material)
            ob.matrix_world = parent_transform
            self.context.collection.objects.link(ob)
            try:
                ob.layers = 18 * [False] + [True] + [False]
            except:
                pass  # capture AttributeError
            group.objects.link(ob)
            return
        else:
            me, alpha = self.write_mesh_data(entities=entities, name=name, default_material=default_material)
        if me:
            ob = bpy.data.objects.new(name, me)
            ob.matrix_world = parent_transform
            if alpha:
                ob.show_transparent = True
            me.update(calc_edges=True)
            self.context.collection.objects.link(ob)
            try:
                ob.layers = 18 * [False] + [True] + [False]
            except:
                pass  # capture AttributeError
            group.objects.link(ob)
        for g in entities.groups:
            if self.layers_skip and g.layer in self.layers_skip:
                continue
            self.component_def_as_group(
                g.entities,
                "G-" + g.name,
                parent_transform @ Matrix(g.transform),
                default_material=inherent_default_mat(g.material, default_material),
                etype=EntityType.group,
                group=group,
            )
        for instance in entities.instances:
            if self.layers_skip and instance.layer in self.layers_skip:
                continue
            cdef = self.skp_components[instance.definition.name]
            if cdef is None:
                continue
            self.component_def_as_group(
                cdef.entities,
                cdef.name,
                parent_transform @ Matrix(instance.transform),
                default_material=inherent_default_mat(instance.material, default_material),
                etype=EntityType.component,
                group=group,
            )

    #
    # Creates a single group in a collection that contains duplicated
    # instances of a component. Scaling and rotations are used to identify
    # similar components. Each duplicate group contains components with the
    # same scale and rotation applied.
    #
    def instance_group_dupli_vert(self, name, default_material, component_stats):
        def get_orientations(v):
            orientations = defaultdict(list)
            for transform in v:
                loc, rot, scale = Matrix(transform).decompose()
                scale = (scale[0], scale[1], scale[2])
                rot = (rot[0], rot[1], rot[2], rot[3])
                orientations[(scale, rot)].append((loc[0], loc[1], loc[2]))
            for key, locs in orientations.items():
                scale, rot = key
                yield scale, rot, locs

        # Create a new group with duplicated components as a linked object.
        # Each duplicated group has a specific location, scale and rotation
        # applied.
        for scale, rot, locs in get_orientations(component_stats[(name, default_material)]):
            verts = []
            main_loc = Vector(locs[0])
            for c in locs:
                verts.append(Vector(c) - main_loc)
            dme = bpy.data.meshes.new("DUPLI-" + name)
            dme.vertices.add(len(verts))
            dme.vertices.foreach_set("co", unpack_list(verts))
            dme.update(calc_edges=True)  # update mesh with new data
            dme.validate()
            dob = bpy.data.objects.new("DUPLI-" + name, dme)
            dob.location = main_loc
            dob.instance_type = "VERTS"
            ob = self.instance_object_or_group(name, default_material)
            ob.scale = scale
            ob.rotation_mode = "QUATERNION"  # change from default mode of xyz
            ob.rotation_quaternion = Quaternion((rot[0], rot[1], rot[2], rot[3]))
            ob.parent = dob
            self.context.collection.objects.link(ob)
            self.context.collection.objects.link(dob)
            skp_log(
                f"Complex group {name} {default_material} instanced {len(verts)} times, scale -> {scale}, rot -> {rot}"
            )
        return

    def instance_group_dupli_face(self, name, default_material, component_stats):
        def get_orientations(v):
            orientations = defaultdict(list)
            for transform in v:
                _loc, _rot, scale = Matrix(transform).decompose()
                scale = (scale[0], scale[1], scale[2])
                orientations[scale].append(transform)
            for scale, transforms in orientations.items():
                yield scale, transforms

        for _scale, transforms in get_orientations(component_stats[(name, default_material)]):
            main_loc, _real_rot, real_scale = Matrix(transforms[0]).decompose()
            verts = []
            faces = []
            f_count = 0
            for c in transforms:
                l_loc, l_rot, _l_scale = Matrix(c).decompose()
                mat = Matrix.Translation(l_loc) * l_rot.to_matrix().to_4x4()
                verts.append(Vector((mat * Vector((-0.05, -0.05, 0, 1.0)))[0:3]) - main_loc)
                verts.append(Vector((mat * Vector((0.05, -0.05, 0, 1.0)))[0:3]) - main_loc)
                verts.append(Vector((mat * Vector((0.05, 0.05, 0, 1.0)))[0:3]) - main_loc)
                verts.append(Vector((mat * Vector((-0.05, 0.05, 0, 1.0)))[0:3]) - main_loc)
                faces.append((f_count + 0, f_count + 1, f_count + 2, f_count + 3))
                f_count += 4
            dme = bpy.data.meshes.new("DUPLI-" + name)
            dme.vertices.add(len(verts))
            dme.vertices.foreach_set("co", unpack_list(verts))
            dme.tessfaces.add(f_count / 4)
            dme.tessfaces.foreach_set("vertices_raw", unpack_face_list(faces))
            dme.update(calc_edges=True)  # Update mesh with new data
            dme.validate()
            dob = bpy.data.objects.new("DUPLI-" + name, dme)
            dob.instance_type = "FACES"
            dob.location = main_loc
            # dob.use_dupli_faces_scale = True
            # dob.dupli_faces_scale = 10
            ob = self.instance_object_or_group(name, default_material)
            ob.scale = real_scale
            ob.parent = dob
            self.context.collection.objects.link(ob)
            self.context.collection.objects.link(dob)
            skp_log(f"Complex group {name} {default_material} instanced {f_count / 4} times")
        return

    def write_camera(self, camera, name="Last View"):
        skp_log(f"Writing camera: {name}")
        pos, target, up = camera.GetOrientation()
        bpy.ops.object.add(type="CAMERA", location=pos)
        ob = self.context.object
        ob.name = "Cam: " + name
        z = Vector(pos) - Vector(target)
        x = Vector(up).cross(z)
        y = z.cross(x)
        x.normalize()
        y.normalize()
        z.normalize()
        ob.matrix_world.col[0] = x.resized(4)
        ob.matrix_world.col[1] = y.resized(4)
        ob.matrix_world.col[2] = z.resized(4)
        cam = ob.data
        aspect_ratio = camera.aspect_ratio
        fov = camera.fov
        if aspect_ratio == False:
            skp_log(f"Cam: '{name}' uses dynamic/screen aspect ratio.")
            aspect_ratio = self.aspect_ratio
        if fov == False:
            skp_log(f"Cam: '{name}' is in Orthographic Mode.")
            cam.type = "ORTHO"
        # cam.ortho_scale = 3.0
        else:
            cam.angle = (math.pi * fov / 180) * aspect_ratio
        cam.clip_end = self.prefs.camera_far_plane
        cam.name = "Cam: " + name
        return cam.name


def _rgba_to_int(rgba):
    """Blender linear RGBA floats (0-1) → SketchUp 8-bit RGBA, with gamma correction."""
    def to_byte(v):
        return round(math.sqrt(max(0.0, min(1.0, v))) * 255.0)  # linear → sRGB

    r, g, b = to_byte(rgba[0]), to_byte(rgba[1]), to_byte(rgba[2])
    a = 255 if len(rgba) < 4 else round(max(0.0, min(1.0, rgba[3])) * 255.0)
    return (r, g, b, a)


def _boundary_loop(halfedges):
    """把共面块的有向边界半边 (a→b) 头尾相接串成一个闭合环; 不是恰好一个简单环时返回 []。

    按半边前进方向 (a→b) 串接, 环的绕向与原三角一致, 法向不翻转。
    """
    nxt = {}
    for a, b in halfedges:
        if a == b or a in nxt:
            return []
        nxt[a] = b  # 从 a 出发的边界半边到达 b
    loop = []
    start = next(iter(nxt))
    cur = start
    while True:
        loop.append(cur)
        if cur not in nxt:
            return []
        cur = nxt.pop(cur)
        if cur == start:
            break
    return loop if len(nxt) == 0 and len(loop) >= 3 else []


def merge_coplanar_tris(verts, tris, normal_eps=1e-6, dist_eps=1e-6):
    """把三角形网格按共面且共边连通合并为 N 边面。

    verts: (n,3) float64; tris: (m,3) 顶点索引。
    返回 [(面顶点索引列表)]; 出现孔洞/非流形等无法合并的块时整体回退为原始三角。
    """
    tris = np.asarray(tris, dtype=np.int64)
    if len(tris) == 0:
        return []
    v0, v1, v2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    area2 = np.linalg.norm(n, axis=1)
    norms = n / np.maximum(area2, 1e-300)[:, None]
    d = np.einsum("ij,ij->i", norms, v0)

    # 无向边 → (三角, 有向半边); 两个三角相邻 = 共享一条无向边且半边方向相反
    edge_map = defaultdict(list)
    for ti, (a, b, c) in enumerate(tris):
        for a, b in ((a, b), (b, c), (c, a)):
            edge_map[(min(a, b), max(a, b))].append((ti, a, b))

    adj = defaultdict(list)
    for entries in edge_map.values():
        if len(entries) != 2:
            continue
        (t1, a1, b1), (t2, a2, b2) = entries
        if (a1, b1) != (b2, a2):
            continue  # 同向重叠边: 非流形, 不合并
        if abs(norms[t1] @ norms[t2] - 1.0) > normal_eps or abs(d[t1] - d[t2]) > dist_eps:
            continue
        adj[t1].append(t2)
        adj[t2].append(t1)

    faces = []  # 每个共面连通块的面顶点环; 复杂块记 None
    visited = np.zeros(len(tris), dtype=bool)
    for i in range(len(tris)):
        if visited[i]:
            continue
        stack, comp = [i], []
        visited[i] = True
        while stack:
            t = stack.pop()
            comp.append(t)
            for nb in adj[t]:
                if not visited[nb]:
                    visited[nb] = True
                    stack.append(nb)
        # 块内有向半边中, 无向边只出现一次的是边界; 出现两次以上为非流形
        cnt = defaultdict(list)
        for t in comp:
            a, b, c = tris[t]
            for a, b in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
                cnt[(min(a, b), max(a, b))].append((a, b))
        if any(len(e) > 2 for e in cnt.values()):
            faces.append(None)
            continue
        boundary = [e[0] for e in cnt.values() if len(e) == 1]
        # 边界必须是简单环: 每个边界顶点恰好出现在两条边界边中
        bverts = [v for e in boundary for v in e]
        if not boundary or len(bverts) != 2 * len(set(bverts)):
            faces.append(None)  # 孔洞或开边界
            continue
        loop = _boundary_loop(boundary)
        faces.append(loop if loop else None)

    if any(f is None for f in faces):
        # 有无法合并的块时整体回退为三角面, 保证输出始终是有效几何
        return [[int(a), int(b), int(c)] for a, b, c in tris]
    return faces


class SceneExporter:
    def __init__(self):
        self.filepath = "/tmp/untitled.skp"
        self.context = None
        self.only_selected = False
        self.export_materials = True
        self.temp_files = []
        self.material_map = {}
        self.component_map = {}
        self.textured_mats = set()  # 带纹理的材质名 (Material.type 只写不可读)

    def set_filename(self, filename):
        self.filepath = filename
        self.basepath, self.skp_filename = os.path.split(self.filepath)
        return self

    def save(self, context, **options):
        self.context = context
        self.only_selected = options.get("only_selected", False)
        self.export_materials = options.get("export_materials", True)
        skp_model = sketchup.Model()
        saved = False
        try:
            self.export_objects(context, skp_model)
            skp_model.save(self.filepath)
            saved = True
            skp_log(f"Finished exporting: {self.filepath}")
            return {"FINISHED"}
        except Exception as ex:
            # 只清理本次导出实际写出的半成品文件, 不碰导出前已存在的文件
            if saved and os.path.exists(self.filepath):
                try:
                    os.remove(self.filepath)
                except OSError:
                    pass
            skp_log(f"Export failed: {ex}")
            raise
        finally:
            try:
                skp_model.close()
            except RuntimeError:
                pass
            self.cleanup_temp_files()

    def cleanup_temp_files(self):
        for f in self.temp_files:
            try:
                os.remove(f)
            except OSError:
                pass
        self.temp_files = []

    def get_export_objects(self, context):
        depsgraph = context.evaluated_depsgraph_get()
        objects = context.selected_objects if self.only_selected else context.scene.objects
        return [ob for ob in objects if ob.type == "MESH" and ob.visible_get()], depsgraph

    def export_objects(self, context, skp_model):
        objects, depsgraph = self.get_export_objects(context)
        if not objects:
            return

        # 按 mesh data 分组: users>1 → ComponentDefinition + instances; users==1 → Group
        shared = {}
        for ob in objects:
            if ob.data.users > 1 and not ob.data.name.startswith("."):
                shared.setdefault(ob.data.name, []).append(ob)

        model_entities = skp_model.entities
        for ob in objects:
            eval_ob = ob.evaluated_get(depsgraph)
            mesh = eval_ob.to_mesh()
            try:
                mesh.calc_loop_triangles()
                n_verts = len(mesh.vertices)
                if n_verts == 0 or len(mesh.loop_triangles) == 0:
                    continue
                verts = np.empty(n_verts * 3, dtype=np.float64)
                mesh.vertices.foreach_get("co", verts)
                verts = verts.reshape(-1, 3)
                loops = np.empty(len(mesh.loops), dtype=np.int32)
                mesh.loops.foreach_get("vertex_index", loops)

                # 按面材质槽分组: 同一 mesh 的不同面可属于不同材质槽
                slot_mats = {}
                for slot_idx, slot in enumerate(ob.material_slots):
                    if slot.material:
                        slot_mats[slot_idx] = self.export_material(slot.material, skp_model) if self.export_materials else None
                tris_by_slot = defaultdict(list)
                for t in mesh.loop_triangles:
                    tri = [int(loops[t.loops[0]]), int(loops[t.loops[1]]), int(loops[t.loops[2]])]
                    tris_by_slot[t.material_index].append(tri)
                # (材质, 三角列表) 组; 无材质槽的面归到 None 材质
                groups = [(slot_mats.get(idx), tris) for idx, tris in sorted(tris_by_slot.items())]
                # 每组独立判断能否合并: 带纹理的材质需要逐顶点 UV, 合并成 N 边面会丢失纹理坐标
                groups = [
                    (mat, merge_coplanar_tris(verts, tris) if not (mat is not None and mat.name in self.textured_mats) else tris)
                    for mat, tris in groups
                ]

                use_component = ob.data.users > 1
                if use_component:
                    comp = self.get_or_create_component(ob, verts, groups, skp_model)
                    instance = comp.createInstance()
                    instance.name = ob.name
                    instance.transform = ob.matrix_world
                    model_entities.addInstance(instance, ob.name)
                else:
                    group = sketchup.Group.create()
                    group.name = ob.name
                    group.transform = ob.matrix_world
                    # 必须先把 group 附加到模型, 再向其 entities 填充带材质的几何;
                    # 反序会导致材质引用悬空 (SU_ERROR_SERIALIZATION / 崩溃)
                    model_entities.addGroup(group)
                    geom = sketchup.GeometryInput()
                    geom.AddVertices(verts)
                    for mat, faces in groups:
                        for face in faces:
                            geom.add_face(face, material=mat)
                    group.entities.addGeometryInput(geom)
            finally:
                eval_ob.to_mesh_clear()

    def get_or_create_component(self, ob, verts, groups, skp_model):
        """users>1 的 mesh: 首次遇到时建 definition(局部坐标), 之后直接复用。

        groups: [(材质, 面顶点索引列表), ...], 面可能是三角或合并后的 N 边面。
        """
        key = ob.data.name
        if key in self.component_map:
            return self.component_map[key]

        comp = sketchup.Component.create()
        comp.name = key
        # definition 先附加到模型, 再填带材质的几何 (同 group 的顺序要求)
        skp_model.addComponentDefinitions([comp])
        geom = sketchup.GeometryInput()
        geom.AddVertices(verts)
        for mat, faces in groups:
            for face in faces:
                geom.add_face(face, material=mat)
        comp.entities.addGeometryInput(geom)
        self.component_map[key] = comp
        return comp

    def export_material(self, bmat, skp_model):
        """导出材质 (v1: diffuse 颜色 + 可选纹理), 按材质名去重。"""
        if not bmat:
            return None
        if bmat.name in self.material_map:
            return self.material_map[bmat.name]

        su_mat = sketchup.Material.create()
        su_mat.name = bmat.name
        su_mat.color = _rgba_to_int(list(bmat.diffuse_color))
        if len(bmat.diffuse_color) >= 4 and bmat.diffuse_color[3] < 1.0:
            su_mat.use_opacity = True
            su_mat.opacity = float(bmat.diffuse_color[3])
        self.export_texture(bmat, su_mat)
        skp_model.addMaterials([su_mat])
        self.material_map[bmat.name] = su_mat
        return su_mat

    def export_texture(self, bmat, su_mat):
        """有 image texture 的材质: image 存临时 PNG 再 SUTextureCreateFromFile(v1 取第一个 image 节点)。"""
        image = None
        if bmat.use_nodes:
            for node in bmat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    image = node.image
                    break
        if not image:
            return
        try:
            png_path = os.path.join(
                tempfile.gettempdir(), f"skp_export_{os.getpid()}_{len(self.temp_files)}_{image.name}.png")
            _write_png(image, png_path)
            texture = sketchup.Texture.create_from_file(png_path)
            su_mat.set_texture(texture)
            su_mat.type = 1  # SUMaterialType_Textured
            self.textured_mats.add(bmat.name)
            self.temp_files.append(png_path)
        except Exception as ex:
            skp_log(f"Texture export failed for {bmat.name}: {ex}")


def _write_png(image, filepath):
    """Save a copy of a Blender image to filepath as PNG, without mutating the original datablock."""
    copy = image.copy()
    try:
        copy.filepath_raw = filepath
        copy.file_format = "PNG"
        copy.save()
    finally:
        bpy.data.images.remove(copy)


class ImportSKP(Operator, ImportHelper):
    """Load a Trimble SketchUp .skp file"""

    bl_idname = "import_scene.skp"
    bl_label = "Import SKP"
    bl_options = {"PRESET", "REGISTER", "UNDO"}
    filename_ext = ".skp"

    filter_glob: StringProperty(
        default="*.skp",
        options={"HIDDEN"},
    )

    scenes_as_camera: BoolProperty(
        name="Scene(s) As Camera(s)",
        description="Import SketchUp Scenes As Blender Camera.",
        default=True,
    )

    import_camera: BoolProperty(
        name="Last View In SketchUp As Camera View",
        description="Import last saved view in SketchUp as a Blender Camera.",
        default=False,
    )

    reuse_material: BoolProperty(
        name="Use Existing Materials",
        description="Doesn't copy material IDs already in the Blender Scene.",
        default=True,
    )

    dedub_only: BoolProperty(name="Groups Only", description="Import instantiated groups only.", default=False)

    reuse_existing_groups: BoolProperty(
        name="Reuse Groups", description="Use existing Blender groups to instance components with.", default=False
    )

    # Altered from initial default of 50 so as to force import all
    # components to be imported as duplicated objects.
    max_instance: IntProperty(name="Instantiation Threshold :", default=1)

    dedub_type: EnumProperty(
        name="Instancing Type :",
        items=(
            ("FACE", "Faces", ""),
            ("VERTEX", "Vertices", ""),
        ),
        default="VERTEX",
    )

    import_scene: StringProperty(name="Import A Scene :", description="Import a specific SketchUp Scene", default="")

    # render_engine: EnumProperty(
    #    name="Default Shaders In :",
    #    items=(('CYCLES', "Cycles", ""),
    #           #    ('BLENDER_RENDER', "Blender Render", "")
    #           ),
    #    default='CYCLES'
    # )

    def execute(self, context):
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob", "split_mode"))
        return SceneImporter().set_filename(keywords["filepath"]).load(context, **keywords)

    def draw(self, context):
        layout = self.layout
        layout.label(text="- Primary Import Options -")
        row = layout.row()
        row.prop(self, "scenes_as_camera")
        row = layout.row()
        row.prop(self, "import_camera")
        row = layout.row()
        row.prop(self, "reuse_material")
        row = layout.row()
        row.prop(self, "dedub_only")
        row = layout.row()
        row.prop(self, "reuse_existing_groups")
        col = layout.column()
        col.label(text="- Instantiate components, if they are more than -")
        # split = col.split(factor=0.5)
        # col = split.column()
        col.prop(self, "max_instance")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "dedub_type")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "import_scene")
        # row = layout.row()
        # row.use_property_split = True
        # row.prop(self, "render_engine")


class ExportSKP(Operator, ExportHelper):
    """Export .blend into .skp file"""

    bl_idname = "export_scene.skp"
    bl_label = "Export SKP"
    bl_options = {"PRESET", "UNDO"}
    filename_ext = ".skp"

    filter_glob: StringProperty(
        default="*.skp",
        options={"HIDDEN"},
    )

    only_selected: BoolProperty(
        name="Selection Only",
        description="Export only selected mesh objects instead of the whole scene",
        default=False,
    )

    export_materials: BoolProperty(
        name="Export Materials",
        description="Export diffuse color / opacity of the first material slot",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "only_selected")
        layout.prop(self, "export_materials")

    def execute(self, context):
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob", "split_mode", "check_existing"))
        try:
            return SceneExporter().set_filename(keywords["filepath"]).save(context, **keywords)
        except Exception as ex:
            self.report({"ERROR"}, f"SKP export failed: {ex}")
            return {"CANCELLED"}


def menu_func_import(self, context):
    self.layout.operator(ImportSKP.bl_idname, text="SketchUp (.skp)")


def menu_func_export(self, context):
    self.layout.operator(ExportSKP.bl_idname, text="SketchUp (.skp)")


def register():
    bpy.utils.register_class(SketchupAddonPreferences)
    bpy.utils.register_class(ImportSKP)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.utils.register_class(ExportSKP)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_class(ImportSKP)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ExportSKP)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(SketchupAddonPreferences)
