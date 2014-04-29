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


from django.db import models
from chroma_core.lib.job import DependOn, DependAll, Step, job_log
from chroma_core.models.target import ManagedTargetMount, ManagedMgs, FilesystemMember, ManagedTarget
from chroma_core.models.host import NoNidsPresent
from chroma_core.models.jobs import StatefulObject, StateChangeJob, StateLock, Job
from chroma_core.models.utils import DeletableDowncastableMetaclass, MeasuredEntity
from chroma_core.lib.cache import ObjectCache
from django.db.models import Q
from chroma_help.help import help_text


HSM_CONTROL_KEY = 'mdt.hsm_control'
HSM_CONTROL_PARAMS = {
    'disabled': {
        'verb': "Disable",
        'long_description': help_text['hsm_control_disabled']
    },
    'enabled': {
        'verb': "Enable",
        'long_description': help_text['hsm_control_enabled']
    },
    'shutdown': {
        'verb': "Shutdown",
        'long_description': help_text['hsm_control_shutdown']
    }
}


class ManagedFilesystem(StatefulObject, MeasuredEntity):
    __metaclass__ = DeletableDowncastableMetaclass

    name = models.CharField(max_length=8, help_text="Lustre filesystem name, up to 8\
            characters")
    mgs = models.ForeignKey('ManagedMgs')

    states = ['unavailable', 'stopped', 'available', 'removed', 'forgotten']
    initial_state = 'unavailable'

    mdt_next_index = models.IntegerField(default = 0)
    ost_next_index = models.IntegerField(default = 0)

    def get_label(self):
        return self.name

    def get_available_states(self, begin_state):
        if self.immutable_state:
            return ['forgotten']
        else:
            available_states = super(ManagedFilesystem, self).get_available_states(begin_state)
            available_states = list(set(available_states) - set(['forgotten']))

            # Exclude 'stopped' if we are in 'unavailable' and everything is stopped
            target_states = set([t.state for t in self.get_filesystem_targets()])
            if begin_state == 'unavailable' and not 'mounted' in target_states:
                available_states = list(set(available_states) - set(['stopped']))

            return available_states

    class Meta:
        app_label = 'chroma_core'
        unique_together = ('name', 'mgs')
        ordering = ['id']

    def get_targets(self):
        return ManagedTarget.objects.filter((Q(managedmdt__filesystem = self) | Q(managedost__filesystem = self)) | Q(id = self.mgs_id))

    def get_filesystem_targets(self):
        return ManagedTarget.objects.filter((Q(managedmdt__filesystem = self) | Q(managedost__filesystem = self)))

    def get_servers(self):
        from collections import defaultdict
        targets = self.get_targets()
        servers = defaultdict(list)
        for t in targets:
            for tm in t.managedtargetmount_set.all():
                servers[tm.host].append(tm)

        # NB converting to dict because django templates don't place nice with defaultdict
        # (http://stackoverflow.com/questions/4764110/django-template-cant-loop-defaultdict)
        return dict(servers)

    def mgs_spec(self):
        """Return a string which is foo in <foo>:/lustre for client mounts"""
        return ":".join([",".join(nids) for nids in self.mgs.nids()])

    def mount_path(self):
        try:
            return "%s:/%s" % (self.mgs_spec(), self.name)
        except NoNidsPresent:
            return None

    def __str__(self):
        return self.name

    def get_deps(self, state = None):
        if not state:
            state = self.state

        deps = []

        mgs = ObjectCache.get_one(ManagedTarget, lambda t: t.id == self.mgs_id)

        remove_state = 'forgotten' if self.immutable_state else 'removed'

        if state not in ['removed', 'forgotten']:
            deps.append(DependOn(mgs,
                'unmounted',
                acceptable_states = mgs.not_states(['removed', 'forgotten']),
                fix_state = remove_state))

        return DependAll(deps)

    @classmethod
    def filter_by_target(cls, target):
        if issubclass(target.downcast_class, ManagedMgs):
            result = ObjectCache.get(ManagedFilesystem, lambda mfs: mfs.mgs_id == target.id)
            return result
        elif issubclass(target.downcast_class, FilesystemMember):
            return ObjectCache.get(ManagedFilesystem, lambda mfs: mfs.id == target.downcast().filesystem_id)
        else:
            raise NotImplementedError(target.__class__)

    reverse_deps = {
        'ManagedTarget': lambda mt: ManagedFilesystem.filter_by_target(mt)
    }


class PurgeFilesystemStep(Step):
    idempotent = True

    def run(self, kwargs):
        host = kwargs['host']
        mgs_device_path = kwargs['path']
        fs = kwargs['filesystem']
        mgs = ObjectCache.get_one(ManagedTarget, lambda t: t.id == fs.mgs_id)

        initial_mgs_state = mgs.state

        # Whether the MGS was officially up or not, try stopping it (idempotent so will
        # succeed either way
        if initial_mgs_state in ['mounted', 'unmounted']:
            self.invoke_agent(host, "stop_target", {'ha_label': mgs.ha_label})
        self.invoke_agent(host, "purge_configuration", {
            'device': mgs_device_path,
            'filesystem_name': fs.name
        })

        if initial_mgs_state == 'mounted':
            result = self.invoke_agent(host, "start_target", {'ha_label': mgs.ha_label})
            # Update active_mount because it won't necessarily start the same place it was started to
            # begin with
            mgs.update_active_mount(result['location'])


class RemoveFilesystemJob(StateChangeJob):
    state_transition = (ManagedFilesystem, 'stopped', 'removed')
    stateful_object = 'filesystem'
    state_verb = "Remove"
    filesystem = models.ForeignKey('ManagedFilesystem')

    display_group = Job.JOB_GROUPS.COMMON
    display_order = 20

    def get_requires_confirmation(self):
        return True

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    @classmethod
    def long_description(cls, stateful_object):
        return help_text["remove_file_system"]

    def description(self):
        return "Remove file system %s from configuration" % self.filesystem.name

    def create_locks(self):
        locks = super(RemoveFilesystemJob, self).create_locks()
        locks.append(StateLock(
            job = self,
            locked_item = self.filesystem.mgs.managedtarget_ptr,
            begin_state = None,
            end_state = None,
            write = True))
        return locks

    def get_steps(self):
        steps = []

        # Only try to purge filesystem from MGT if the MGT has made it past
        # being formatted (case where a filesystem was created but is being
        # removed before it or its MGT got off the ground)
        mgt_setup = self.filesystem.mgs.state not in ['unformatted', 'formatted']

        if (not self.filesystem.immutable_state) and mgt_setup:
            mgs = ObjectCache.get_one(ManagedTarget, lambda t: t.id == self.filesystem.mgs_id)
            mgs_primary_mount = ObjectCache.get_one(ManagedTargetMount, lambda mtm: mtm.target_id == mgs.id and mtm.primary is True)

            steps.append((PurgeFilesystemStep, {
                'filesystem': self.filesystem,
                'path': mgs_primary_mount.volume_node.path,
                'host': mgs_primary_mount.host
            }))

        return steps

    def on_success(self):
        job_log.debug("on_success: mark_deleted on filesystem %s" % id(self.filesystem))

        from chroma_core.models.target import ManagedMdt, ManagedOst
        assert ManagedMdt.objects.filter(filesystem = self.filesystem).count() == 0
        assert ManagedOst.objects.filter(filesystem = self.filesystem).count() == 0
        self.filesystem.mark_deleted()

        super(RemoveFilesystemJob, self).on_success()


class FilesystemJob():
    stateful_object = 'filesystem'

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_steps(self):
        return []


class StartStoppedFilesystemJob(FilesystemJob, StateChangeJob):
    state_verb = "Start"
    state_transition = (ManagedFilesystem, 'stopped', 'available')
    filesystem = models.ForeignKey('ManagedFilesystem')

    display_group = Job.JOB_GROUPS.COMMON
    display_order = 10

    @classmethod
    def long_description(cls, stateful_object):
        return help_text["start_file_system"]

    def description(self):
        return "Start file system %s" % self.filesystem.name

    def get_deps(self):
        deps = []

        for t in ObjectCache.get_targets_by_filesystem(self.filesystem_id):
            deps.append(DependOn(t,
                'mounted',
                fix_state = 'unavailable'))
        return DependAll(deps)


class StartUnavailableFilesystemJob(FilesystemJob, StateChangeJob):
    state_verb = "Start"
    state_transition = (ManagedFilesystem, 'unavailable', 'available')
    filesystem = models.ForeignKey('ManagedFilesystem')

    display_group = Job.JOB_GROUPS.COMMON
    display_order = 20

    @classmethod
    def long_description(cls, stateful_object):
        return help_text["start_file_system"]

    def description(self):
        return "Start filesystem %s" % self.filesystem.name

    def get_deps(self):
        deps = []
        for t in ObjectCache.get_targets_by_filesystem(self.filesystem_id):
            deps.append(DependOn(t,
                'mounted',
                fix_state = 'unavailable'))
        return DependAll(deps)


class StopUnavailableFilesystemJob(FilesystemJob, StateChangeJob):
    state_verb = "Stop"
    state_transition = (ManagedFilesystem, 'unavailable', 'stopped')
    filesystem = models.ForeignKey('ManagedFilesystem')

    display_group = Job.JOB_GROUPS.INFREQUENT
    display_order = 30

    @classmethod
    def long_description(cls, stateful_object):
        return help_text["stop_file_system"]

    def description(self):
        return "Stop file system %s" % self.filesystem.name

    def get_deps(self):
        deps = []
        targets = ObjectCache.get_targets_by_filesystem(self.filesystem_id)
        targets = [t for t in targets if not issubclass(t.downcast_class, ManagedMgs)]
        for t in targets:
            deps.append(DependOn(t,
                'unmounted',
                acceptable_states = t.not_state('mounted'),
                fix_state = 'unavailable'))
        return DependAll(deps)


class MakeAvailableFilesystemUnavailable(FilesystemJob, StateChangeJob):
    state_verb = None
    state_transition = (ManagedFilesystem, 'available', 'unavailable')
    filesystem = models.ForeignKey('ManagedFilesystem')

    @classmethod
    def long_description(cls, stateful_object):
        return help_text['make_file_system_unavailable']

    def description(self):
        return "Make file system %s unavailable" % self.filesystem.name


class ForgetFilesystemJob(StateChangeJob):
    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    display_group = Job.JOB_GROUPS.RARE
    display_order = 40

    state_transition = (ManagedFilesystem, ['unavailable', 'stopped', 'available'], 'forgotten')
    stateful_object = 'filesystem'
    state_verb = "Forget"
    filesystem = models.ForeignKey(ManagedFilesystem)
    requires_confirmation = True

    @classmethod
    def long_description(cls, stateful_object):
        return help_text["remove_file_system"]

    def description(self):
        return "Forget unmanaged file system %s" % self.filesystem.name

    def on_success(self):
        super(ForgetFilesystemJob, self).on_success()

        from chroma_core.models.target import ManagedMdt, ManagedOst
        assert ManagedMdt.objects.filter(filesystem = self.filesystem).count() == 0
        assert ManagedOst.objects.filter(filesystem = self.filesystem).count() == 0
        self.filesystem.mark_deleted()
