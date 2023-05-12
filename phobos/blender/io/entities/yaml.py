#!/usr/bin/python3
# coding=utf-8

# -------------------------------------------------------------------------------
# This file is part of Phobos, a Blender Add-On to edit robot models.
# Copyright (C) 2020 University of Bremen & DFKI GmbH Robotics Innovation Center
#
# You should have received a copy of the 3-Clause BSD License in the LICENSE file.
# If not, see <https://opensource.org/licenses/BSD-3-Clause>.
# -------------------------------------------------------------------------------

import json
import os
from datetime import datetime
import phobos.blender.defs as defs
from phobos.blender.phoboslog import log


def exportYAML(model, path):
    """This function exports a given robot model to a specified filepath as YAML.

    Args:
      model(dict): Phobos robot model dictionary
      path(str): filepath to export the robot to (*WITH* filename)

    Returns:

    """
    log(f"phobos YAML export: Writing model data to {path}", "INFO")
    with open(os.path.join(path, model['name'] + '.yaml'), 'w') as outputfile:
        outputfile.write(
            f"""# YAML dump of robot model '{model['name']}', {datetime.now().strftime("%Y%m%d_%H:%M")}\n"""
        )
        outputfile.write(
            f"# created with Phobos {defs.version} - https://github.com/dfki-ric/phobos\n\n"
        )

        # write the yaml dump to the file
        outputfile.write(json.dumps(model))


# registering export functions of types with Phobos
entity_type_dict = {'yaml': {'export': exportYAML, 'extensions': ('yaml', 'yml')}}
