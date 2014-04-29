#
# INTEL CONFIDENTIAL
#
# Copyright 2013-2014 Intel Corporation All Rights Reserved.
#
# The source code contained or described herein and all documents related
# to the source code ("Material") are owned by Intel Corporation or its
# suppliers or licensors. Title to the Material remains with Intel Corporation
# or its suppliers and licensors. The Material contains trade secrets and
# proprietary and confidential information of Intel or its suppliers and
# licensors. The Material is protected by worldwide copyright and trade secret
# laws and treaty provisions. No part of the Material may be used, copied,
# reproduced, modified, published, uploaded, posted, transmitted, distributed,
# or disclosed in any way without Intel's prior express written permission.
#
# No license under any patent, copyright, trade secret or other intellectual
# property right is granted to or conferred upon you by disclosure or delivery
# of the Materials, either expressly, by implication, inducement, estoppel or
# otherwise. Any license under such intellectual property rights must be
# express and approved by Intel in writing.


from django.core.management.base import CommandError
from djcelery.management.commands.celeryd import Command as DjangoCeleryCommand
from chroma_core.lib.service_config import ServiceConfig
from chroma_core.services.log import log_set_filename, log_enable_stdout


class Command(DjangoCeleryCommand):
    def handle(self, *args, **options):
        if not ServiceConfig().configured():
            raise CommandError("Chroma is not configured, please run chroma-config setup")

        log_set_filename('worker.log')
        log_enable_stdout()

        super(Command, self).handle(*args, **options)
